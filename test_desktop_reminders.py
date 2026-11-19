"""Reminder lifecycle tests: no waiting and no OS notification delivery."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend_db import BackendEngine
from desktop_reminders import ReminderService


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "reminders.db")
        self.engine = BackendEngine(self.path)
        self.now = datetime(2026, 11, 19, 9, 0, 0)
        self.service = ReminderService(self.engine, now=lambda: self.now)
        self.task = self.engine.create_task("書展", "2027-04-23", auto_remind=False)

    def test_ten_second_test_is_not_early_and_is_acknowledged_once(self):
        self.service.schedule_test(self.task)
        self.now += timedelta(seconds=9)
        self.assertEqual(self.service.due(), [])
        self.now += timedelta(seconds=1)
        due = self.service.due()
        self.assertEqual(len(due), 1)
        self.assertIn("測試提醒", due[0]["message"])
        self.service.acknowledge([due[0]["reminder_id"]])
        self.assertEqual(self.service.due(), [])

    def test_pending_and_overdue_survive_reopening(self):
        self.service.schedule_test(self.task)
        self.now += timedelta(seconds=20)
        reopened = ReminderService(BackendEngine(self.path), now=lambda: self.now)
        self.assertEqual(len(reopened.due()), 1)

    def test_reading_without_ack_does_not_lose_reminder(self):
        self.service.schedule_test(self.task)
        self.now += timedelta(seconds=20)
        self.assertEqual(len(self.service.due()), 1)
        self.assertEqual(len(self.service.due()), 1)

    def test_completed_task_is_not_reminded(self):
        self.service.schedule_test(self.task)
        self.engine.toggle_task_status(self.task)
        self.now += timedelta(seconds=20)
        self.assertEqual(self.service.due(), [])
        with self.assertRaises(ValueError):
            self.service.schedule_test(self.task)

    def test_cancelled_completed_reminder_does_not_return_on_reactivation(self):
        self.service.schedule_test(self.task)
        self.engine.toggle_task_status(self.task)
        self.assertEqual(self.service.cancel(self.task), 1)
        self.engine.toggle_task_status(self.task)
        self.now += timedelta(seconds=20)
        self.assertEqual(self.service.due(), [])

    def test_deleted_task_has_no_remaining_reminders(self):
        self.service.schedule_test(self.task)
        self.engine.delete_task(self.task)
        self.now += timedelta(seconds=20)
        self.assertEqual(self.service.due(), [])
        with self.engine._get_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM Reminders").fetchone()[0], 0)

    def test_replace_changes_pending_time(self):
        self.service.schedule_at(self.task, "2026-11-19 10:00")
        self.service.schedule_at(self.task, "2026-11-19 11:00")
        pending = self.service.pending(self.task)
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["alert_time"], "2026-11-19 11:00:00")

    def test_test_reminder_does_not_replace_real_reminder(self):
        self.service.schedule_at(self.task, "2026-11-19 10:00")
        self.service.schedule_test(self.task)
        self.assertEqual(len(self.service.pending(self.task)), 2)

    def test_invalid_or_past_schedule_preserves_existing_reminder(self):
        self.service.schedule_at(self.task, "2026-11-19 10:00")
        for value in ("2026-11-19 08:59", "2026-02-30 10:00", "not a date", "2026-11-19 25:00"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.service.schedule_at(self.task, value)
        self.assertEqual(len(self.service.pending(self.task)), 1)

    def test_legacy_minute_precision_reminders_are_supported(self):
        self.engine.add_reminder(self.task, "2026-11-19 09:00", "existing reminder")
        self.assertEqual(len(self.service.due()), 1)

    def test_missing_task_cannot_be_scheduled(self):
        with self.assertRaises(ValueError):
            self.service.schedule_at("missing", "2026-11-19 10:00")


if __name__ == "__main__":
    unittest.main(verbosity=2)
