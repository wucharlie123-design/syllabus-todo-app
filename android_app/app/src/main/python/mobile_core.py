"""On-device business logic. Standard-library Python only; no server or network."""
import json
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta


def _json(value):
    return json.dumps(value, ensure_ascii=False)


@contextmanager
def _db(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(path):
    with _db(path) as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL, event_date TEXT NOT NULL,
            start_time TEXT, end_time TEXT, location TEXT,
            completed INTEGER NOT NULL DEFAULT 0,
            source_text TEXT NOT NULL DEFAULT '',
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            fire_at INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'normal',
            delivered INTEGER NOT NULL DEFAULT 0, cancelled INTEGER NOT NULL DEFAULT 0
        );
        ''')
    return _json({'ok': True})


def _clock(value):
    value = str(value or '').strip()
    if not value:
        return None
    if not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('時間請填 HH:MM，例如 14:00')
    datetime.strptime(value, '%H:%M')
    return value


def _day(value):
    value = str(value or '').strip()
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('日期請填 YYYY-MM-DD')
    return parsed


def _validated(payload, editing=False):
    if payload.get('confirmed') is not True:
        raise ValueError('請先確認日期、時間與地點')
    title = str(payload.get('title') or '').strip()
    if not title or len(title) > 500:
        raise ValueError('請填事件名稱（最多500字）')
    try:
        start = _day(payload.get('date'))
        end = _day(payload['end_date']) if payload.get('end_date') else start
    except (ValueError, TypeError):
        raise ValueError('請填有效的完整日期 YYYY-MM-DD') from None
    if end < start or (end-start).days > 365:
        raise ValueError('日期範圍需在366天內，結束不可早於開始')
    raw_days = payload.get('weekdays')
    if isinstance(raw_days, str):
        try:
            raw_days = [int(x.strip()) for x in raw_days.split(',') if x.strip()]
        except ValueError:
            raise ValueError('每週活動日請填1到7，以逗號分隔') from None
    days = set(raw_days or [])
    if any(type(x) is not int or x not in range(1, 8) for x in days):
        raise ValueError('每週活動日請填1到7，以逗號分隔')
    if days and not payload.get('end_date'):
        raise ValueError('每週活動需填結束日期，限定匯入範圍')
    if editing and (end != start or days):
        raise ValueError('目前編輯單筆任務；重複活動請逐筆修改')
    if (end != start or days) and payload.get('expand_range') is not True:
        raise ValueError('請確認將日期範圍展開為單日任務')
    begin, finish = _clock(payload.get('start_time')), _clock(payload.get('end_time'))
    if finish and (not begin or finish <= begin):
        raise ValueError('請確認同日活動的開始與結束時間')
    current, rows = start, []
    while current <= end:
        if not days or current.isoweekday() in days:
            rows.append((title, current.isoformat(), begin, finish,
                         str(payload.get('location') or '').strip()[:2000] or None,
                         str(payload.get('source_text') or '')[:50000]))
        current += timedelta(days=1)
    if not rows:
        raise ValueError('日期範圍沒有符合每週規則的日期')
    return rows


def list_tasks(path):
    with _db(path) as conn:
        rows = conn.execute('''SELECT t.*,
            (SELECT MIN(fire_at) FROM reminders r WHERE r.task_id=t.id
             AND r.delivered=0 AND r.cancelled=0 AND t.completed=0) AS next_reminder
            FROM tasks t ORDER BY completed,event_date,COALESCE(start_time,'23:59'),id''').fetchall()
        return _json([dict(row) for row in rows])


def get_task(path, task_id):
    with _db(path) as conn:
        row = conn.execute('SELECT * FROM tasks WHERE id=?', (int(task_id),)).fetchone()
        return _json(dict(row) if row else None)


def save_task(path, payload_json):
    payload = json.loads(payload_json)
    rows = _validated(payload)
    now = int(time.time()*1000)
    ids = []
    with _db(path) as conn:
        for row in rows:
            cursor = conn.execute('''INSERT INTO tasks
                (title,event_date,start_time,end_time,location,source_text,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)''', (*row, now, now))
            ids.append(cursor.lastrowid)
    return _json({'task_ids': ids})


def update_task(path, task_id, payload_json):
    row = _validated(json.loads(payload_json), editing=True)[0]
    task_id = int(task_id)
    cancelled = []
    with _db(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if old is None:
            raise ValueError('任務不存在')
        if (old['event_date'], old['start_time'], old['end_time']) != row[1:4]:
            cancelled = [r[0] for r in conn.execute('SELECT id FROM reminders WHERE task_id=? AND delivered=0 AND cancelled=0', (task_id,))]
            conn.execute('UPDATE reminders SET cancelled=1 WHERE task_id=? AND delivered=0', (task_id,))
        conn.execute('UPDATE tasks SET title=?,event_date=?,start_time=?,end_time=?,location=?,source_text=?,updated_at=? WHERE id=?', (*row, int(time.time()*1000), task_id))
    return _json({'cancelled_reminders': cancelled})


def set_completed(path, task_id, completed):
    completed = int(bool(completed))
    task_id = int(task_id)
    with _db(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        ids = [r[0] for r in conn.execute('SELECT id FROM reminders WHERE task_id=? AND delivered=0 AND cancelled=0', (task_id,))] if completed else []
        cursor = conn.execute('UPDATE tasks SET completed=?,updated_at=? WHERE id=?', (completed, int(time.time()*1000), task_id))
        if not cursor.rowcount:
            raise ValueError('任務不存在')
        if completed:
            conn.execute('UPDATE reminders SET cancelled=1 WHERE task_id=? AND delivered=0', (task_id,))
    return _json({'cancelled_reminders': ids})


def delete_task(path, task_id):
    with _db(path) as conn:
        ids = [r[0] for r in conn.execute('SELECT id FROM reminders WHERE task_id=? AND delivered=0 AND cancelled=0', (int(task_id),))]
        conn.execute('DELETE FROM tasks WHERE id=?', (int(task_id),))
    return _json({'cancelled_reminders': ids})


def schedule_reminder(path, task_id, fire_at, kind='normal'):
    fire_at, task_id = int(fire_at), int(task_id)
    if fire_at <= int(time.time()*1000):
        raise ValueError('提醒時間必須晚於現在')
    if kind not in ('normal', 'test'):
        raise ValueError('不支援的提醒種類')
    with _db(path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        task = conn.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if task is None or task['completed']:
            raise ValueError('請選擇尚未完成的任務')
        cancelled = []
        if kind == 'normal':
            cancelled = [r[0] for r in conn.execute('SELECT id FROM reminders WHERE task_id=? AND delivered=0 AND cancelled=0 AND kind=?', (task_id, 'normal'))]
            conn.execute('UPDATE reminders SET cancelled=1 WHERE task_id=? AND delivered=0 AND kind=?', (task_id, 'normal'))
        cursor = conn.execute('INSERT INTO reminders(task_id,fire_at,kind) VALUES (?,?,?)', (task_id, fire_at, kind))
        rid = cursor.lastrowid
    return _json({'reminder_id': rid, 'fire_at': fire_at, 'cancelled_reminders': cancelled})


def cancel_reminders(path, task_id):
    with _db(path) as conn:
        ids = [r[0] for r in conn.execute('SELECT id FROM reminders WHERE task_id=? AND delivered=0 AND cancelled=0', (int(task_id),))]
        conn.execute('UPDATE reminders SET cancelled=1 WHERE task_id=? AND delivered=0', (int(task_id),))
    return _json({'cancelled_reminders': ids})


def pending_reminders(path):
    with _db(path) as conn:
        rows = conn.execute('''SELECT r.*,t.title,t.location FROM reminders r JOIN tasks t ON t.id=r.task_id
            WHERE r.cancelled=0 AND r.delivered=0 AND t.completed=0 ORDER BY r.fire_at''').fetchall()
    return _json([dict(r) for r in rows])


def reminder_for_delivery(path, reminder_id):
    with _db(path) as conn:
        row = conn.execute('''SELECT r.*,t.title,t.location,t.event_date,t.start_time
            FROM reminders r JOIN tasks t ON t.id=r.task_id
            WHERE r.id=? AND r.cancelled=0 AND r.delivered=0 AND t.completed=0''', (int(reminder_id),)).fetchone()
        return _json(dict(row) if row else None)


def mark_delivered(path, reminder_id):
    with _db(path) as conn:
        conn.execute('UPDATE reminders SET delivered=1 WHERE id=? AND cancelled=0', (int(reminder_id),))
    return _json({'ok': True})


DATE_PATTERN = re.compile(r'(?<!\d)(?:(?P<era>民國|中華民國|西元)\s*)?(?:(?P<year>\d{3,4})\s*(?:年|[./-])\s*)?(?P<month>\d{1,2})\s*(?:月|[./-])\s*(?P<day>\d{1,2})\s*日?(?!\d)')
WEEKDAY = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'日':7,'天':7}


def _resolve_date(match, text, reference, inherited=None):
    year = match.group('year')
    month, day = int(match.group('month')), int(match.group('day'))
    after = text[match.end():match.end()+18]
    wm = re.match(r'\s*[（(]?\s*(?:星期|週|周)([一二三四五六日天])', after)
    weekday = WEEKDAY[wm.group(1)] if wm else None
    notes = []
    inferred = False
    if year:
        year = int(year)
        era = match.group('era')
        if era in ('民國','中華民國'):
            year += 1911
        elif year < 1911:
            if len(match.group('year')) == 3 and re.search(r'臺|台灣|屏東|縣|國中|國小|民國', text):
                year += 1911
                notes.append('依地區文字推定為民國年份，請確認')
            else:
                return None, False, ['曆法不明確，請補完整西元日期']
        resolved = date(year, month, day)
    elif inherited:
        year = inherited.year
        resolved = date(year, month, day)
        if resolved < inherited:
            resolved = date(year+1, month, day)
            notes.append('結束日期推定為下一年，請確認')
    else:
        resolved = None
        for candidate_year in range(reference.year, reference.year+12):
            try:
                candidate = date(candidate_year, month, day)
            except ValueError:
                continue
            if candidate >= reference and (weekday is None or candidate.isoweekday() == weekday):
                resolved = candidate
                break
        if resolved is None:
            raise ValueError('無法推定日期')
        inferred = True
        notes.append('圖片未寫年份，建議最近的未來日期，請確認')
    if weekday and resolved.isoweekday() != weekday:
        notes.append('日期與圖片星期不一致，請確認')
    return resolved, inferred, notes


def _title(lines, before_line=None):
    candidates = []
    for index, line in enumerate(lines):
        if len(line) < 2 or len(line) > 100:
            continue
        if DATE_PATTERN.search(line) or re.search(r'\d{1,2}:\d{2}|https?://|@|電話|地點[:：]|地址[:：]', line):
            continue
        if re.match(r'^(免費|報名|時間|日期|主辦|承辦|協辦|招生|演講嘉賓|地點|地址)', line):
            continue
        score = 20 if re.search(r'活動|講座|音樂營|書展|展覽|研討會|工作坊|演唱會|音樂會|讀書會|聚會|workshop|seminar|concert|conference|meetup',line,re.I) else 0
        if before_line is not None and index < before_line:
            score += max(0, 20-3*(before_line-index))
        score += max(0, 5-index)
        candidates.append((score, -index, line))
    if candidates:
        return max(candidates)[2]
    short = [x for x in lines[:5] if len(x) == 1]
    return ''.join(short) if short else ''


def _times(text):
    matches = list(re.finditer(r'(?P<period>上午|下午|晚上|中午|AM|PM)?\s*(?P<h>\d{1,2})\s*[:：]\s*(?P<m>\d{2})(?!\d)', text, re.I))
    result, last_period = [], None
    for match in matches[:2]:
        h,m = int(match.group('h')), int(match.group('m'))
        period = match.group('period') or last_period
        last_period = period
        if period and period.lower() in ('下午','晚上','中午','pm') and h < 12:
            h += 12
        if period and period.lower() in ('上午','am') and h == 12:
            h = 0
        if 0 <= h < 24 and 0 <= m < 60:
            result.append(f'{h:02d}:{m:02d}')
    return (result+[None,None])[:2]


def _location(lines):
    for i,line in enumerate(lines):
        match = re.search(r'(?:地點|地址|場地|Location|Venue)\s*[:：]\s*(.*)', line, re.I)
        if match:
            return match.group(1).strip() or (lines[i+1] if i+1<len(lines) else '')
    for line in lines:
        if re.search(r'(?:路|街|道|巷)\s*\d+\s*號',line):
            return line
    return ''


def extract_events(text, reference_date=''):
    text = unicodedata.normalize('NFKC', str(text))[:50000]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = '\n'.join(lines)
    reference = date.fromisoformat(reference_date) if reference_date else date.today()
    clock_spans = [m.span() for m in re.finditer(r'\d{1,2}\s*:\s*\d{2}', text)]
    matches = [m for m in DATE_PATTERN.finditer(text)
               if not any(m.start() < stop and m.end() > begin for begin, stop in clock_spans)]
    start_time, end_time = _times(text)
    location = _location(lines)
    repeated = re.search(r'(?:每週|每周|每星期)\s*([一二三四五六日天])(?:\s*(?:到|至|~|～|-)\s*(?:週|周|星期)?\s*([一二三四五六日天]))?',text)
    if not repeated:
        repeated = re.search(r'(?:週|周|星期)([一二三四五六日天])\s*(?:到|至|~|～|-)\s*(?:週|周|星期)([一二三四五六日天])',text)
    weekdays = []
    if repeated:
        first = WEEKDAY[repeated.group(1)]
        last = WEEKDAY[repeated.group(2)] if repeated.group(2) else first
        weekdays = list(range(first,last+1)) if last>=first else list(range(first,8))+list(range(1,last+1))
    events, date_offsets, i = [], [], 0
    while i < len(matches):
        match = matches[i]
        notes = []
        try:
            start, inferred, notes = _resolve_date(match,text,reference)
        except ValueError:
            start, inferred = None, False
            notes.append('日期無效或不完整，請手動確認')
        end = None
        if i+1 < len(matches) and re.fullmatch(r'\s*(?:~|～|至|到|[-–—])\s*',text[match.end():matches[i+1].start()]):
            try:
                end, _, end_notes = _resolve_date(matches[i+1],text,reference,start)
                notes.extend(end_notes)
            except ValueError:
                notes.append('結束日期需手動確認')
            i += 1
        before_line = text[:match.start()].count('\n')
        title = _title(lines,before_line)
        if len(matches) > 1 and end is None:
            notes.append('圖片含多個日期，請確認事件與時間的對應')
        events.append({'title':title,'date':start.isoformat() if start else '',
                       'end_date':end.isoformat() if end else '',
                       'weekdays':','.join(map(str,weekdays)) if end else '',
                       'start_time':start_time or '', 'end_time':end_time or '',
                       'location':location,'year_inferred':inferred,'notes':notes,
                       'needs_review':True,'source_text':text})
        date_offsets.append(match.start())
        i += 1
    if len(events) > 1:
        # Associate fields with each event block, never copy the first event's
        # clock/location to all later dates. Missing local evidence stays blank.
        starts, cursor = [], 0
        for line in lines:
            starts.append(cursor)
            cursor += len(line) + 1
        boundaries = []
        for event, offset in zip(events, date_offsets):
            date_line = text[:offset].count('\n')
            titles = [index for index in range(date_line + 1)
                      if lines[index] == event['title']]
            boundary = starts[titles[-1]] if titles else starts[date_line]
            if boundaries and boundary <= boundaries[-1]:
                boundary = starts[date_line]
            boundaries.append(boundary)
        for index, event in enumerate(events):
            left = 0 if index == 0 else boundaries[index]
            right = boundaries[index+1] if index+1 < len(events) else len(text)
            local = text[left:right]
            begin, finish = _times(local)
            event['start_time'], event['end_time'] = begin or '', finish or ''
            event['location'] = _location(local.splitlines())
    if not events:
        events=[{'title':_title(lines),'date':'','end_date':'','weekdays':'',
                 'start_time':start_time or '', 'end_time':end_time or '',
                 'location':location,'year_inferred':False,
                 'notes':['未找到完整日期，請手動補填'],'needs_review':True,'source_text':text}]
    return _json({'events':events[:30],'text':text,'truncated':len(events)>30})
