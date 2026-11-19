import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

SRC=Path(__file__).resolve().parents[1]/'app/src/main/python/mobile_core.py'
spec=importlib.util.spec_from_file_location('mobile_core',SRC)
core=importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

class MobileCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=str(Path(self.temp.name)/'mobile.db')
        core.initialize(self.path)
        self.payload={'title':'書展','date':'2027-04-23','location':'展場','confirmed':True}
    def save(self, **fields):
        return json.loads(core.save_task(self.path,json.dumps(dict(self.payload,**fields))))['task_ids']
    def task(self, task_id): return json.loads(core.get_task(self.path,task_id))
    def test_save_reopen_and_list(self):
        tid=self.save()[0]
        core.initialize(self.path)
        self.assertEqual(self.task(tid)['title'],'書展')
        self.assertEqual(len(json.loads(core.list_tasks(self.path))),1)
    def test_manual_confirmation_required(self):
        with self.assertRaises(ValueError): self.save(confirmed=False)
        self.assertEqual(json.loads(core.list_tasks(self.path)),[])
    def test_invalid_and_missing_date_rejected(self):
        for value in ('','2027-02-30','20270423','2027-4-23'):
            with self.subTest(value=value),self.assertRaises(ValueError): self.save(date=value)
    def test_invalid_times_rejected(self):
        for fields in ({'start_time':'25:00'},{'start_time':'17:00','end_time':'14:00'},{'end_time':'14:00'}):
            with self.subTest(fields=fields),self.assertRaises(ValueError): self.save(**fields)
    def test_range_requires_confirmation(self):
        with self.assertRaises(ValueError): self.save(end_date='2027-04-25')
        self.assertEqual(len(self.save(end_date='2027-04-25',expand_range=True)),3)
    def test_weekdays_and_multiday_camp(self):
        ids=self.save(date='2012-07-12',end_date='2012-07-31',weekdays='1,2,3,4,5',expand_range=True)
        self.assertEqual(len(ids),14)
    def test_long_or_reverse_range_rejected(self):
        for fields in ({'end_date':'2027-04-22','expand_range':True},{'end_date':'2029-04-23','expand_range':True}):
            with self.subTest(fields=fields),self.assertRaises(ValueError): self.save(**fields)
    def test_reminder_is_persistent_and_delivery_is_recorded(self):
        tid=self.save()[0]
        r=json.loads(core.schedule_reminder(self.path,tid,int(time.time()*1000)+10000))
        rid=r['reminder_id']
        self.assertEqual(len(json.loads(core.pending_reminders(self.path))),1)
        self.assertEqual(json.loads(core.reminder_for_delivery(self.path,rid))['title'],'書展')
        core.mark_delivered(self.path,rid)
        self.assertEqual(json.loads(core.pending_reminders(self.path)),[])
        self.assertIsNone(json.loads(core.reminder_for_delivery(self.path,rid)))
    def test_reminder_replace_and_test_does_not_replace_real(self):
        tid=self.save()[0]
        at=int(time.time()*1000)+100000
        first=json.loads(core.schedule_reminder(self.path,tid,at))
        second=json.loads(core.schedule_reminder(self.path,tid,at+1000))
        self.assertEqual(second['cancelled_reminders'],[first['reminder_id']])
        core.schedule_reminder(self.path,tid,at+2000,'test')
        self.assertEqual(len(json.loads(core.pending_reminders(self.path))),2)
    def test_completed_task_cancels_alarm_and_cannot_schedule(self):
        tid=self.save()[0]
        reminder=json.loads(core.schedule_reminder(self.path,tid,int(time.time()*1000)+100000))
        result=json.loads(core.set_completed(self.path,tid,1))
        self.assertEqual(result['cancelled_reminders'],[reminder['reminder_id']])
        self.assertIsNone(json.loads(core.reminder_for_delivery(self.path,reminder['reminder_id'])))
        with self.assertRaises(ValueError):core.schedule_reminder(self.path,tid,int(time.time()*1000)+100000)
        core.set_completed(self.path,tid,0)
        self.assertEqual(json.loads(core.pending_reminders(self.path)),[])
    def test_delete_cascades_and_returns_alarm_ids(self):
        tid=self.save()[0]
        reminder=json.loads(core.schedule_reminder(self.path,tid,int(time.time()*1000)+100000))
        result=json.loads(core.delete_task(self.path,tid))
        self.assertEqual(result['cancelled_reminders'],[reminder['reminder_id']])
        self.assertIsNone(self.task(tid))
        self.assertEqual(json.loads(core.pending_reminders(self.path)),[])
    def test_edit_cancels_only_when_time_changes(self):
        tid=self.save()[0]
        reminder=json.loads(core.schedule_reminder(self.path,tid,int(time.time()*1000)+100000))
        result=json.loads(core.update_task(self.path,tid,json.dumps(dict(self.payload,title='新書展'))))
        self.assertEqual(result['cancelled_reminders'],[])
        self.assertEqual(json.loads(core.reminder_for_delivery(self.path,reminder['reminder_id']))['title'],'新書展')
        result=json.loads(core.update_task(self.path,tid,json.dumps(dict(self.payload,date='2027-04-24'))))
        self.assertEqual(result['cancelled_reminders'],[reminder['reminder_id']])
    def test_invalid_edit_does_not_change_task(self):
        tid=self.save()[0]
        with self.assertRaises(ValueError):core.update_task(self.path,tid,json.dumps(dict(self.payload,date='')))
        self.assertEqual(self.task(tid)['event_date'],'2027-04-23')
    def test_alarm_schedule_past_does_not_replace(self):
        tid=self.save()[0]
        core.schedule_reminder(self.path,tid,int(time.time()*1000)+100000)
        with self.assertRaises(ValueError):core.schedule_reminder(self.path,tid,1)
        self.assertEqual(len(json.loads(core.pending_reminders(self.path))),1)
    def test_missing_task_rejected(self):
        with self.assertRaises(ValueError):core.schedule_reminder(self.path,999,int(time.time()*1000)+100000)
    def test_yearless_poster_uses_weekday_and_future_date(self):
        out=json.loads(core.extract_events('世界圖書日慶祝活動\n4月23日 (星期五)\n地址:圖龍道31號希爾大樓2樓','2026-11-19'))
        event=out['events'][0]
        self.assertEqual(event['date'],'2027-04-23')
        self.assertTrue(event['year_inferred'])
        self.assertEqual(event['weekdays'],'')
        self.assertEqual(event['location'],'圖龍道31號希爾大樓2樓')
    def test_explicit_roc_camp_range(self):
        out=json.loads(core.extract_events('屏東縣潮州鎮暑期兒童音樂營\n日期:101年07月12日-07月31日\n每週一到週五\n時間:下午14:00~17:10\n地點:潮州國中活動中心','2026-11-19'))
        event=out['events'][0]
        self.assertEqual(event['date'],'2012-07-12')
        self.assertEqual(event['end_date'],'2012-07-31')
        self.assertEqual(event['weekdays'],'1,2,3,4,5')
        self.assertEqual(event['start_time'],'14:00')
        self.assertEqual(event['end_time'],'17:10')
    def test_western_date_and_english_poster(self):
        event=json.loads(core.extract_events('AI Workshop\n2027-05-14\n14:00-16:00\nLocation: Room 101','2026-11-19'))['events'][0]
        self.assertEqual(event['title'],'AI Workshop')
        self.assertEqual(event['date'],'2027-05-14')
        self.assertEqual(event['location'],'Room 101')
        self.assertFalse(event['year_inferred'])
    def test_missing_date_kept_for_review_not_today(self):
        event=json.loads(core.extract_events('社區聚會\n地點:活動中心','2026-11-19'))['events'][0]
        self.assertEqual(event['date'],'')
        self.assertTrue(event['needs_review'])
    def test_impossible_date_does_not_crash(self):
        event=json.loads(core.extract_events('讀書會\n2027年2月30日','2026-11-19'))['events'][0]
        self.assertEqual(event['date'],'')
        self.assertTrue(event['notes'])
    def test_multiple_dates_produce_multiple_reviewable_events(self):
        out=json.loads(core.extract_events('社區活動\n2027-04-23\n2027-04-24','2026-11-19'))
        self.assertEqual(len(out['events']),2)
        self.assertTrue(all(x['needs_review'] for x in out['events']))
    def test_unknown_calendar_not_silently_converted(self):
        event=json.loads(core.extract_events('活動\n101年7月12日','2026-11-19'))['events'][0]
        self.assertEqual(event['date'],'')
    def test_cancel_reminder_does_not_delete_task(self):
        tid=self.save()[0]
        core.schedule_reminder(self.path,tid,int(time.time()*1000)+100000)
        core.cancel_reminders(self.path,tid)
        self.assertIsNotNone(self.task(tid))
        self.assertEqual(json.loads(core.pending_reminders(self.path)),[])
    def test_same_date_for_two_activities_is_not_discarded(self):
        events=json.loads(core.extract_events('活動A\n2027-04-23\n活動B\n2027-04-23','2026-11-19'))['events']
        self.assertEqual(len(events),2)
        self.assertEqual([e['title'] for e in events],['活動A','活動B'])
    def test_weekday_range_without_every_prefix(self):
        event=json.loads(core.extract_events('屏東縣音樂營\n101年7月12日-7月31日\n週一到週五','2026-11-19'))['events'][0]
        self.assertEqual(event['weekdays'],'1,2,3,4,5')
    def test_time_range_is_not_an_extra_date(self):
        events=json.loads(core.extract_events('讀書會\n日期:2026年12月5日\n時間:14:00-16:00','2026-11-19'))['events']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['date'],'2026-12-05')
    def test_multiple_events_keep_their_own_times_and_locations(self):
        text='AI 工作坊\n2026年12月5日\n時間:14:00-16:00\n地點:A教室\n攝影講座\n2026年12月6日\n時間:09:00-11:00\n地點:B教室'
        events=json.loads(core.extract_events(text,'2026-11-19'))['events']
        self.assertEqual([(e['title'],e['start_time'],e['end_time'],e['location']) for e in events],
                         [('AI 工作坊','14:00','16:00','A教室'),('攝影講座','09:00','11:00','B教室')])
    def test_later_event_does_not_inherit_missing_clock_or_location(self):
        text='攝影講座\n2026年12月5日\n時間:14:00-16:00\n地點:A教室\n音樂會\n2026年12月6日'
        events=json.loads(core.extract_events(text,'2026-11-19'))['events']
        self.assertEqual((events[1]['start_time'],events[1]['end_time'],events[1]['location']),('','',''))

if __name__=='__main__':unittest.main(verbosity=2)
