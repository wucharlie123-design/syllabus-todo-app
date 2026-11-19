"""Persistent local reminders; the Tk main thread displays and acknowledges them."""
from datetime import datetime, timedelta


def parse_alert_time(text):
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            value = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if value.strftime(fmt) == text:
            return value
    raise ValueError("提醒時間請使用 YYYY-MM-DD HH:MM，例如 2027-04-23 13:45")


class ReminderService:
    def __init__(self, engine, now=None):
        self.engine = engine
        self.now = now or datetime.now

    def schedule_at(self, task_id, text, replace=True, test=False):
        at = parse_alert_time(text)
        if at <= self.now():
            raise ValueError("提醒時間必須晚於現在")
        with self.engine._lock, self.engine._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            task = conn.execute("SELECT * FROM Tasks WHERE task_id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError("任務不存在")
            if task["status"] != "Pending":
                raise ValueError("已完成任務不會提醒；請先切換為待辦")
            if replace:
                conn.execute("DELETE FROM Reminders WHERE task_id = ? AND is_triggered = 0", (task_id,))
            message = ("測試提醒：" if test else "任務提醒：") + task["title"]
            location = task["location"]
            if location:
                message += "\n地點：" + location
            cursor = conn.execute(
                "INSERT INTO Reminders (task_id,alert_time,message,is_triggered) VALUES (?,?,?,0)",
                (task_id, at.strftime("%Y-%m-%d %H:%M:%S"), message),
            )
            return cursor.lastrowid

    def schedule_test(self, task_id):
        at = self.now().replace(microsecond=0) + timedelta(seconds=10)
        return self.schedule_at(task_id, at.strftime("%Y-%m-%d %H:%M:%S"), replace=False, test=True)

    def pending(self, task_id=None):
        query = ("SELECT r.*, t.title FROM Reminders r JOIN Tasks t ON r.task_id=t.task_id "
                 "WHERE r.is_triggered=0 AND t.status='Pending'")
        params = ()
        if task_id is not None:
            query += " AND r.task_id=?"
            params = (task_id,)
        query += " ORDER BY r.alert_time, r.reminder_id"
        with self.engine._get_connection() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def due(self):
        cutoff = self.now()
        # Parse times instead of depending on lexical ordering of minute/second strings.
        return [row for row in self.pending() if parse_alert_time(row["alert_time"]) <= cutoff]

    def acknowledge(self, reminder_ids):
        if not reminder_ids:
            return
        with self.engine._lock, self.engine._get_connection() as conn:
            conn.executemany("UPDATE Reminders SET is_triggered=1 WHERE reminder_id=?", [(rid,) for rid in reminder_ids])

    def cancel(self, task_id):
        with self.engine._lock, self.engine._get_connection() as conn:
            cursor = conn.execute("DELETE FROM Reminders WHERE task_id=? AND is_triggered=0", (task_id,))
            return cursor.rowcount
