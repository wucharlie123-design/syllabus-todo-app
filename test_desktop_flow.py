"""Headless integration checks. No model download, GUI or OS notifications."""
import io
import json
import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from backend_db import BackendEngine
from desktop_bridge import extract_image, prepare_tasks, save_confirmed, update_confirmed
from desktop_reminders import ReminderService


class DesktopFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.db"
        self.engine = BackendEngine(str(self.path))
        self.fields = dict(title="書展", date="2027-04-23", end_date="", weekdays="",
                           start_time="", end_time="", location="展場")

    def test_manual_correction_persists_across_reopen(self):
        fields = dict(self.fields, title="已確認的書展", date="2027-04-24")
        ids = save_confirmed(self.engine, fields)
        stored = BackendEngine(str(self.path)).get_task_by_id(ids[0])
        self.assertEqual(stored["due_date"], "2027-04-24")
        self.assertEqual(stored["title"], "已確認的書展")
        self.assertEqual(self.engine.get_upcoming_reminders(), [])

    def test_missing_date_never_defaults_to_today(self):
        with self.assertRaises(ValueError):
            save_confirmed(self.engine, dict(self.fields, date=""))
        self.assertEqual(self.engine.get_all_tasks(), [])

    def test_invalid_dates_and_times_rejected(self):
        for fields in (dict(self.fields, date="2027-02-30"),
                       dict(self.fields, start_time="25:00"),
                       dict(self.fields, start_time="17:00", end_time="14:00")):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                save_confirmed(self.engine, fields)
        self.assertEqual(self.engine.get_all_tasks(), [])

    def test_range_requires_explicit_expansion(self):
        fields = dict(self.fields, end_date="2027-04-26")
        with self.assertRaises(ValueError):
            save_confirmed(self.engine, fields)
        self.assertEqual(len(save_confirmed(self.engine, fields, True)), 4)

    def test_recurring_camp_expands_weekdays(self):
        fields = dict(self.fields, date="2012-07-12", end_date="2012-07-31", weekdays="1,2,3,4,5")
        ids = save_confirmed(self.engine, fields, True)
        self.assertEqual(len(ids), 14)
        tasks = self.engine.get_all_tasks()
        self.assertTrue(all(date.fromisoformat(t["due_date"]).isoweekday() < 6 for t in tasks))
        self.assertEqual(tasks[-1]["due_date"], "2012-07-31")

    def test_unbounded_or_invalid_recurrence_rejected(self):
        for fields in (dict(self.fields, weekdays="5"),
                       dict(self.fields, end_date="2027-04-30", weekdays="0,8")):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                save_confirmed(self.engine, fields, True)

    def test_transaction_rolls_back_partial_date_range(self):
        fields = dict(self.fields, end_date="2027-04-25")
        with patch("desktop_bridge.uuid.uuid4", return_value="same-id"):
            with self.assertRaises(sqlite3.IntegrityError):
                save_confirmed(self.engine, fields, True)
        self.assertEqual(self.engine.get_all_tasks(), [])

    def test_model_bridge_returns_drafts_without_saving_tasks(self):
        image = Path(self.temp.name) / "sample.png"
        image.write_bytes(b"mock image bytes")
        raw = {"events": [{"title": "書展", "date": {"raw": "4月23日 (星期五)"}, "weekdays": None}]}
        response = {"response": json.dumps(raw, ensure_ascii=False), "done_reason": "stop"}
        with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(response).encode())), patch.dict("os.environ", {"EVENT_REFERENCE_DATE": "2026-11-18"}):
            result = extract_image(image)
        self.assertEqual(result["events"][0]["date"], "2027-04-23")
        self.assertTrue(result["events"][0]["needs_review"])
        self.assertEqual(self.engine.get_all_tasks(), [])

    def test_unreachable_model_does_not_save_tasks(self):
        image = Path(self.temp.name) / "sample.png"
        image.write_bytes(b"mock image bytes")
        from urllib.error import URLError
        with patch("urllib.request.urlopen", side_effect=URLError("offline service")):
            with self.assertRaises(URLError):
                extract_image(image)
        self.assertEqual(self.engine.get_all_tasks(), [])

    def test_edit_time_cancels_stale_reminders_and_preserves_task_id(self):
        task_id = save_confirmed(self.engine, self.fields)[0]
        reminders = ReminderService(self.engine, now=lambda: datetime(2026, 11, 19))
        reminders.schedule_at(task_id, '2027-04-23 09:00')
        self.assertEqual(update_confirmed(self.engine, task_id, dict(self.fields, date='2027-04-24')), 1)
        self.assertEqual(self.engine.get_task_by_id(task_id)['due_date'], '2027-04-24')
        self.assertEqual(reminders.pending(task_id), [])

    def test_edit_name_updates_reminder_message_without_changing_time(self):
        task_id = save_confirmed(self.engine, self.fields)[0]
        reminders = ReminderService(self.engine, now=lambda: datetime(2026, 11, 19))
        rid = reminders.schedule_at(task_id, '2027-04-23 09:00')
        self.assertEqual(update_confirmed(self.engine, task_id, dict(self.fields, title='新名稱', location='新地點')), 0)
        pending = reminders.pending(task_id)
        self.assertEqual(pending[0]['reminder_id'], rid)
        self.assertIn('新名稱', pending[0]['message'])
        self.assertIn('新地點', pending[0]['message'])

    def test_edit_preserves_completed_status(self):
        task_id = save_confirmed(self.engine, self.fields)[0]
        self.engine.toggle_task_status(task_id)
        update_confirmed(self.engine, task_id, dict(self.fields, title='已修改'))
        self.assertEqual(self.engine.get_task_by_id(task_id)['status'], 'Completed')

    def test_invalid_edit_preserves_task_and_reminders(self):
        task_id = save_confirmed(self.engine, self.fields)[0]
        reminders = ReminderService(self.engine, now=lambda: datetime(2026, 11, 19))
        reminders.schedule_at(task_id, '2027-04-23 09:00')
        with self.assertRaises(ValueError):
            update_confirmed(self.engine, task_id, dict(self.fields, date=''))
        self.assertEqual(self.engine.get_task_by_id(task_id)['due_date'], self.fields['date'])
        self.assertEqual(len(reminders.pending(task_id)), 1)

    def test_edit_and_reminder_cancellation_rollback_together(self):
        task_id = save_confirmed(self.engine, self.fields)[0]
        self.engine.add_reminder(task_id, '2027-04-23 09:00', 'keep')
        with self.engine._get_connection() as conn:
            conn.execute("CREATE TRIGGER prevent_test_delete BEFORE DELETE ON Reminders BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            update_confirmed(self.engine, task_id, dict(self.fields, date='2027-04-24'))
        self.assertEqual(self.engine.get_task_by_id(task_id)['due_date'], '2027-04-23')
        self.assertEqual(len(self.engine.get_upcoming_reminders()), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
