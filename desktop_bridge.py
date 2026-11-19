"""Model invocation and validation for the desktop draft confirmation workflow."""
import importlib.util
import json
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def extract_image(path):
    src = ROOT / "ai_module" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    spec = importlib.util.spec_from_file_location("_syllabus_local_ai", src / "ai_parser.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.extract_events(path)


def save_extraction(result):
    folder = ROOT / "integration_results"
    folder.mkdir(exist_ok=True)
    output = folder / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def iso_date(text, label):
    text = text.strip()
    try:
        parsed = date.fromisoformat(text)
    except (ValueError, TypeError):
        raise ValueError(f"{label}請填完整 YYYY-MM-DD，例如 2027-04-23") from None
    if parsed.isoformat() != text:
        raise ValueError(f"{label}請使用 YYYY-MM-DD")
    return parsed


def clock(text, label):
    text = text.strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError:
        raise ValueError(f"{label}請使用24小時制 HH:MM") from None
    if parsed.strftime("%H:%M") != text:
        raise ValueError(f"{label}請使用 HH:MM，例如 09:00")
    return text


def prepare_tasks(fields, expand_range=False):
    title = fields.get("title", "").strip()
    if not title:
        raise ValueError("請填寫事件名稱")
    start = iso_date(fields.get("date", ""), "開始日期")
    end_text = fields.get("end_date", "").strip()
    end = iso_date(end_text, "結束日期") if end_text else start
    if end < start:
        raise ValueError("結束日期不能早於開始日期")
    if (end - start).days > 365:
        raise ValueError("一次最多匯入366天，請縮短日期範圍")
    days = None
    raw_days = fields.get("weekdays", "").strip()
    if raw_days:
        try:
            days = {int(part.strip()) for part in raw_days.split(",")}
        except ValueError:
            raise ValueError("每週活動日請填1至7，以逗號分隔") from None
        if not days or not days <= set(range(1, 8)):
            raise ValueError("每週活動日必須是1至7")
        if not end_text:
            raise ValueError("有每週規則時，請填結束日期")
    if (end != start or days) and not expand_range:
        raise ValueError("請勾選將日期範圍展開為任務，或改成單日活動")
    begin = clock(fields.get("start_time", ""), "開始時間")
    finish = clock(fields.get("end_time", ""), "結束時間")
    if finish and not begin:
        raise ValueError("請補開始時間，或清空結束時間")
    if begin and finish and finish <= begin:
        raise ValueError("目前支援同日活動，結束時間須晚於開始時間")
    tasks = []
    current = start
    while current <= end:
        if days is None or current.isoweekday() in days:
            tasks.append(dict(title=title, due_date=current.isoformat(), start_time=begin,
                              end_time=finish, location=fields.get("location", "").strip() or None))
        current += timedelta(days=1)
    if not tasks:
        raise ValueError("日期範圍沒有符合每週規則的日期")
    return tasks


def save_confirmed(engine, fields, expand_range=False):
    tasks = prepare_tasks(fields, expand_range)
    ids = []
    # An entire date range is saved or rolled back together. No automatic date fallback.
    with engine._lock, engine._get_connection() as conn:
        for task in tasks:
            task_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO Tasks (task_id,title,due_date,start_time,end_time,location) VALUES (?,?,?,?,?,?)",
                (task_id, task["title"], task["due_date"], task["start_time"], task["end_time"], task["location"]),
            )
            ids.append(task_id)
    return ids
