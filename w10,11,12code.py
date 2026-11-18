import json
import os
import platform
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Union


# =====================================================================
# 資料模型定義 (ORM-like Data Models)
# =====================================================================
@dataclass
class TaskItem:
    title: str
    due_date: str  # 格式: YYYY-MM-DD
    start_time: Optional[str] = None  # 格式: HH:MM
    end_time: Optional[str] = None  # 格式: HH:MM
    location: Optional[str] = None
    priority: str = "Medium"  # High, Medium, Low
    status: str = "Pending"  # Pending, Completed
    task_id: str = ""
    created_at: Optional[str] = None
    is_synced: int = 0

    def __post_init__(self):
        if not self.task_id:
            self.task_id = str(uuid.uuid4())
        if self.priority not in ("High", "Medium", "Low"):
            self.priority = "Medium"
        if self.status not in ("Pending", "Completed"):
            self.status = "Pending"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =====================================================================
# 核心後端引擎 (Week 10 Storage + Week 11 Mapping + Week 12 Push)
# =====================================================================
class BackendEngine:
    def __init__(self, db_path: str = "offline_assistant.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._notifier_thread: Optional[threading.Thread] = None
        self.init_database()

    @contextmanager
    def _get_connection(self):
        """Week 10 資料安全機制：確保連線正確開啟、啟用外鍵與自動 Commit/Rollback"""
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def init_database(self) -> None:
        """初始化 SQLite 資料表結構 (銜接 Week 9 設計)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. 待辦事項與事件主表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Tasks (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    due_date TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    location TEXT,
                    priority TEXT DEFAULT 'Medium',
                    status TEXT DEFAULT 'Pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_synced INTEGER DEFAULT 0
                )
            """)
            # 2. 本地提醒排程表 (Week 12)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Reminders (
                    reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    alert_time TEXT NOT NULL,
                    message TEXT NOT NULL,
                    is_triggered INTEGER DEFAULT 0,
                    FOREIGN KEY (task_id) REFERENCES Tasks(task_id) ON DELETE CASCADE
                )
            """)
            # 3. 衝堂紀錄表 (預留給 Week 13)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS Schedule_Conflicts (
                    conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id_1 TEXT NOT NULL,
                    task_id_2 TEXT NOT NULL,
                    conflict_date TEXT NOT NULL,
                    is_resolved INTEGER DEFAULT 0,
                    FOREIGN KEY (task_id_1) REFERENCES Tasks(task_id) ON DELETE CASCADE,
                    FOREIGN KEY (task_id_2) REFERENCES Tasks(task_id) ON DELETE CASCADE
                )
            """)

    # -----------------------------------------------------------------
    # Week 10: Local Data Storage Engine (完整 CRUD 操作)
    # -----------------------------------------------------------------
    def create_task(
        self,
        title: str,
        due_date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        location: Optional[str] = None,
        priority: str = "Medium",
        auto_remind: bool = True,
    ) -> str:
        """新增單筆任務，並可選擇自動產生預設提醒"""
        task = TaskItem(
            title=title.strip(),
            due_date=due_date.strip(),
            start_time=start_time.strip() if start_time else None,
            end_time=end_time.strip() if end_time else None,
            location=location.strip() if location else None,
            priority=priority,
        )
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO Tasks (task_id, title, due_date, start_time, end_time, location, priority, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.title,
                    task.due_date,
                    task.start_time,
                    task.end_time,
                    task.location,
                    task.priority,
                    task.status,
                ),
            )

        if auto_remind:
            self._generate_default_reminders(task)

        return task.task_id

    def get_all_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """讀取所有待辦事項 (供 main_ui.py 渲染列表)，預設依日期與時間排序"""
        query = "SELECT * FROM Tasks"
        params: tuple = ()
        if status in ("Pending", "Completed"):
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY due_date ASC, COALESCE(start_time, '23:59') ASC"

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """依 task_id 查詢單筆任務"""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM Tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def update_task(self, task_id: str, **fields) -> bool:
        """更新任務欄位 (支援標題、日期、時間、地點、優先級、狀態編輯)"""
        allowed_fields = {
            "title",
            "due_date",
            "start_time",
            "end_time",
            "location",
            "priority",
            "status",
        }
        updates = {k: v for k, v in fields.items() if k in allowed_fields}
        if not updates:
            return False

        set_clause = ", ".join(f"{col} = ?" for col in updates.keys())
        values = list(updates.values()) + [task_id]

        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE Tasks SET {set_clause} WHERE task_id = ?", values
            )
            return cursor.rowcount > 0

    def toggle_task_status(self, task_id: str) -> Optional[str]:
        """切換任務完成狀態 (Pending <-> Completed)，供 UI 勾選框呼叫"""
        task = self.get_task_by_id(task_id)
        if not task:
            return None
        new_status = "Completed" if task["status"] == "Pending" else "Pending"
        self.update_task(task_id, status=new_status)
        return new_status

    def delete_task(self, task_id: str) -> bool:
        """刪除任務 (透過 ON DELETE CASCADE 自動連帶清除該任務的提醒)"""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM Tasks WHERE task_id = ?", (task_id,))
            return cursor.rowcount > 0

    # -----------------------------------------------------------------
    # Week 11: Extraction & Task Mapping MVP (串接 AI 輸出至資料庫)
    # -----------------------------------------------------------------
    def import_from_ai_json(
        self, ai_output: Union[str, Dict[str, Any], List[Dict[str, Any]]]
    ) -> List[str]:
        """
        接收 ai_parser.py 輸出的 JSON 字串或字典/陣列，清洗格式後持久化存入資料庫。
        回傳成功寫入的 task_id 列表。
        """
        parsed_data = self._parse_ai_payload(ai_output)

        # 統一轉換為事件列表 (支援單筆 dict、多筆 list 或 {"events": [...]})
        if isinstance(parsed_data, dict):
            events = parsed_data.get("events", [parsed_data])
        elif isinstance(parsed_data, list):
            events = parsed_data
        else:
            raise ValueError("無法辨識的 AI JSON 資料結構")

        created_ids: List[str] = []
        today_str = datetime.now().strftime("%Y-%m-%d")

        for item in events:
            if not isinstance(item, dict):
                continue

            # 欄位名稱相容映射 (防呆處理不同 VLM/OCR 輸出命名差異)
            title = item.get("title") or item.get("event") or item.get("name")
            if not title:
                continue  # 缺乏事件標題則跳過

            raw_date = item.get("due_date") or item.get("date") or today_str
            due_date = self._normalize_date(str(raw_date), fallback=today_str)

            start_time = self._normalize_time(item.get("start_time") or item.get("time"))
            end_time = self._normalize_time(item.get("end_time"))
            location = item.get("location") or item.get("room") or item.get("place")
            priority = item.get("priority", "Medium")

            task_id = self.create_task(
                title=str(title),
                due_date=due_date,
                start_time=start_time,
                end_time=end_time,
                location=str(location) if location else None,
                priority=str(priority),
                auto_remind=True,
            )
            created_ids.append(task_id)

        return created_ids

    @staticmethod
    def _parse_ai_payload(payload: Union[str, Dict, List]) -> Any:
        """清除模型輸出可能夾帶的 ```json ... ``` 標記並解析 JSON"""
        if isinstance(payload, (dict, list)):
            return payload
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", payload.strip(), flags=re.IGNORECASE)
        return json.loads(cleaned)

    @staticmethod
    def _normalize_date(date_str: str, fallback: str) -> str:
        """將常見日期格式標準化為 YYYY-MM-DD"""
        date_str = date_str.strip().replace("/", "-")
        for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        # 處理只有月-日的情況 (例如 "11-15")，自動補上今年年份
        try:
            dt = datetime.strptime(date_str, "%m-%d")
            return dt.replace(year=datetime.now().year).strftime("%Y-%m-%d")
        except ValueError:
            return fallback

    @staticmethod
    def _normalize_time(time_val: Optional[Any]) -> Optional[str]:
        """將時間格式標準化為 HH:MM"""
        if not time_val:
            return None
        t_str = str(time_val).strip()
        match = re.search(r"(\d{1,2}):(\d{2})", t_str)
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        return None

    # -----------------------------------------------------------------
    # Week 12: Notification & Push Logic (本地排程與背景自動推播)
    # -----------------------------------------------------------------
    def add_reminder(self, task_id: str, alert_time: str, message: str) -> int:
        """手動新增一筆提醒排程 (alert_time 格式: YYYY-MM-DD HH:MM)"""
        with self._lock, self._get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO Reminders (task_id, alert_time, message, is_triggered)
                VALUES (?, ?, ?, 0)
                """,
                (task_id, alert_time, message),
            )
            return cursor.lastrowid

    def _generate_default_reminders(self, task: TaskItem) -> None:
        """根據任務日期與時間，自動建立倒數與行前提醒"""
        try:
            if task.start_time:
                event_dt = datetime.strptime(
                    f"{task.due_date} {task.start_time}", "%Y-%m-%d %H:%M"
                )
                # 1. 活動開始前 15 分鐘提醒 (對應 UI Mockup: "CS191 in 15 mins (Rm 302)")
                remind_15m = event_dt - timedelta(minutes=15)
                loc_info = f" ({task.location})" if task.location else ""
                if remind_15m > datetime.now():
                    self.add_reminder(
                        task.task_id,
                        remind_15m.strftime("%Y-%m-%d %H:%M"),
                        f"UPCOMING: {task.title} in 15 mins{loc_info}",
                    )
                # 2. 活動前 1 天提醒
                remind_1d = event_dt - timedelta(days=1)
                if remind_1d > datetime.now():
                    self.add_reminder(
                        task.task_id,
                        remind_1d.strftime("%Y-%m-%d %H:%M"),
                        f"1 Day Left: {task.title}{loc_info}",
                    )
            else:
                # 若只有截止日期無具體時間，預設當天早上 09:00 提醒
                due_morning = datetime.strptime(f"{task.due_date} 09:00", "%Y-%m-%d %H:%M")
                if due_morning > datetime.now():
                    self.add_reminder(
                        task.task_id,
                        due_morning.strftime("%Y-%m-%d %H:%M"),
                        f"ALERT: {task.title} is due today!",
                    )
        except ValueError:
            pass

    def get_upcoming_reminders(self) -> List[Dict[str, Any]]:
        """取得所有尚未觸發的提醒列表"""
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT r.*, t.title, t.status
                FROM Reminders r
                JOIN Tasks t ON r.task_id = t.task_id
                WHERE r.is_triggered = 0 AND t.status = 'Pending'
                ORDER BY r.alert_time ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def check_and_trigger_due_reminders(
        self, ui_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> List[Dict[str, Any]]:
        """檢查並觸發所有已到期的提醒，回傳本次觸發的提醒清單"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        triggered_list: List[Dict[str, Any]] = []

        with self._lock, self._get_connection() as conn:
            due_rows = conn.execute(
                """
                SELECT r.reminder_id, r.task_id, r.alert_time, r.message, t.title, t.status
                FROM Reminders r
                JOIN Tasks t ON r.task_id = t.task_id
                WHERE r.is_triggered = 0
                  AND r.alert_time <= ?
                  AND t.status = 'Pending'
                """,
                (now_str,),
            ).fetchall()

            for row in due_rows:
                item = dict(row)
                conn.execute(
                    "UPDATE Reminders SET is_triggered = 1 WHERE reminder_id = ?",
                    (item["reminder_id"],),
                )
                triggered_list.append(item)

        # 在資料庫鎖之外發送通知，避免阻塞
        for item in triggered_list:
            self._send_os_notification(title="Syllabus AI Reminder", message=item["message"])
            if ui_callback:
                try:
                    ui_callback(item)
                except Exception as e:
                    print(f"[UI Callback Error] {e}")

        return triggered_list

    def start_notification_daemon(
        self,
        check_interval: int = 15,
        ui_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        """啟動背景守護執行緒，定期檢查到期提醒並推播"""
        if self._notifier_thread and self._notifier_thread.is_alive():
            return

        self._stop_event.clear()

        def _worker():
            while not self._stop_event.is_set():
                self.check_and_trigger_due_reminders(ui_callback=ui_callback)
                self._stop_event.wait(check_interval)

        self._notifier_thread = threading.Thread(target=_worker, daemon=True)
        self._notifier_thread.start()

    def stop_notification_daemon(self) -> None:
        """停止背景提醒執行緒"""
        self._stop_event.set()
        if self._notifier_thread:
            self._notifier_thread.join(timeout=2.0)

    @staticmethod
    def _send_os_notification(title: str, message: str) -> None:
        """零外部依賴的跨平台桌面彈窗通知"""
        print(f"\n🔔 [NOTIFICATION] {title}: {message}")
        system_name = platform.system()
        try:
            if system_name == "Darwin":  # macOS
                script = f'display notification "{message}" with title "{title}"'
                subprocess.run(["osascript", "-e", script], check=False)
            elif system_name == "Linux":
                subprocess.run(["notify-send", title, message], check=False)
            elif system_name == "Windows":
                ps_script = (
                    f"[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
                    f"$n=New-Object System.Windows.Forms.NotifyIcon;"
                    f"$n.Icon=[System.Drawing.SystemIcons]::Information;"
                    f"$n.Visible=$true;"
                    f"$n.ShowBalloonTip(5000,'{title}','{message}',[System.Windows.Forms.ToolTipIcon]::Info)"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
        except Exception:
            pass  # 若無桌面環境則維持終端機 log 輸出


# =====================================================================
# 端到端整合測試 (直接執行 python backend_db.py 即可驗證 Week 10~12)
# =====================================================================
if __name__ == "__main__":
    test_db = "test_mvp.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    engine = BackendEngine(db_path=test_db)

    # 1. 模擬 Week 11：接收 ai_parser.py 解析出的 JSON (支援單筆或陣列)
    sample_ai_json = """
    ```json
    [
        {
            "title": "CS101 Midterm",
            "date": "2026-11-25",
            "start_time": "14:00",
            "end_time": "16:00",
            "location": "Rm 101",
            "priority": "High"
        },
        {
            "title": "Physics Quiz 2",
            "due_date": "2026-11-28",
            "priority": "Medium"
        }
    ]
    ```
    """
    imported_ids = engine.import_from_ai_json(sample_ai_json)
    print(f"[Week 11] 成功匯入 {len(imported_ids)} 筆 AI 事件: {imported_ids}")

    # 2. 模擬 Week 10：CRUD 讀取、編輯與勾選完成
    all_tasks = engine.get_all_tasks()
    print(f"[Week 10] 目前資料庫待辦清單 ({len(all_tasks)} 筆):")
    for t in all_tasks:
        print(f"  - [{t['status']}] {t['title']} | Due: {t['due_date']} {t['start_time'] or ''} @ {t['location']}")

    engine.update_task(imported_ids[1], location="Science Bldg 204")
    new_status = engine.toggle_task_status(imported_ids[1])
    print(f"[Week 10] 切換 '{all_tasks[1]['title']}' 狀態為: {new_status}")

    # 3. 模擬 Week 12：測試立即到期的本地推播通知
    now_due = datetime.now().strftime("%Y-%m-%d %H:%M")
    engine.add_reminder(
        task_id=imported_ids[0],
        alert_time=now_due,
        message="ALERT: CS101 Midterm starts in 15 mins (Rm 101)!",
    )
    triggered = engine.check_and_trigger_due_reminders(
        ui_callback=lambda rem: print(f"[Week 12 UI 彈窗觸發] 收到通知物件: {rem['message']}")
    )
    print(f"[Week 12] 本次觸發推播數量: {len(triggered)}")

    # 清理測試資料庫
    os.remove(test_db)