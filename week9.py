import json
import uuid

# 模擬 AI 擷取後傳遞的 JSON 格式
json_payload = '''
{
    "title": "CS101 Midterm",
    "due_date": "2026-11-15",
    "start_time": "14:00",
    "end_time": "16:00",
    "location": "Rm 101",
    "priority": "High"
}
'''

# 解析 JSON 資料
extracted_data = json.loads(json_payload)
# 為該事件生成唯一的 task_id，供資料庫使用
extracted_data['task_id'] = str(uuid.uuid4())
import sqlite3

def init_database(db_name="offline_assistant.db"):
    # 連線至 SQLite 本地資料庫 (若不存在則自動建立)
    conn = sqlite3.connect(db_name)
    
    # 啟用外部鍵 (Foreign Key) 支援
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # 建立 Tasks 資料表 (儲存所有擷取的事件與手動新增的任務)[cite: 9]
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Tasks (
            task_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            due_date DATE NOT NULL,
            start_time TIME,
            end_time TIME,
            location TEXT,
            priority TEXT DEFAULT 'Medium', 
            status TEXT DEFAULT 'Pending', 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_synced INTEGER DEFAULT 0 
        )
    ''')

    # 建立 Reminders 資料表 (供後續 Week 12 提醒推播使用)[cite: 9]
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Reminders (
            reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            alert_time DATETIME NOT NULL,
            message TEXT NOT NULL,
            is_triggered INTEGER DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES Tasks(task_id) ON DELETE CASCADE
        )
    ''')

    # 建立 Schedule_Conflicts 資料表 (供後續 Week 13 衝堂偵測使用)[cite: 9]
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Schedule_Conflicts (
            conflict_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id_1 TEXT NOT NULL,
            task_id_2 TEXT NOT NULL,
            conflict_date DATE NOT NULL,
            is_resolved INTEGER DEFAULT 0,
            FOREIGN KEY (task_id_1) REFERENCES Tasks(task_id) ON DELETE CASCADE,
            FOREIGN KEY (task_id_2) REFERENCES Tasks(task_id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    print(f"資料庫 {db_name} 初始化成功，Schemas 建立完成。")
    
    return conn

if __name__ == "__main__":
    # 執行初始化
    db_conn = init_database()
    db_conn.close()