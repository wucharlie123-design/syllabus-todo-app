
import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from date_utils import parse_date_evidence, make_iso_date
from infer_year import infer_upcoming_date

DAY_MAP = dict(zip("一二三四五六日", range(1, 8)))
DAY_MAP["天"] = 7


def read_date(value, reference_date, fallback_weekday=None, start=None):
    if not isinstance(value, dict) or not isinstance(value.get("raw"), str):
        raise ValueError("缺少原始日期文字")
    raw = value["raw"]
    text = re.sub(r"\s+", "", raw).replace("（", "(").replace("）", ")")
    matches = re.findall(r"(?:星期|週|周)([一二三四五六日天])", text)
    if len(set(matches)) > 1:
        raise ValueError("日期原文包含多個星期，需確認")
    weekday = DAY_MAP[matches[0]] if matches else None
    if weekday is not None and (type(weekday) is not int or weekday not in range(1, 8)):
        raise ValueError("星期必須是1至7")
    weekday_note = (
        "模型提供星期，但日期原文沒有星期佐證；未用於日期驗證，需人工確認"
        if not matches and fallback_weekday is not None
        else None
    )
    if matches and fallback_weekday is not None and weekday != fallback_weekday:
        weekday_note = (
            f"模型星期欄位為 {fallback_weekday}，"
            f"與原文不符；依原文採用 {weekday}，需人工確認"
        )
    text = re.sub(r"\(?(?:星期|週|周)[一二三四五六日天]\)?", "", text)
    chinese = re.fullmatch(r"(?:(民國|西元))?(?:(\d{1,4})年)?(\d{1,2})月(\d{1,2})日(?:止)?", text)
    numeric = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    short = re.fullmatch(r"(\d{1,2})/(\d{1,2})", text)
    if not (chinese or numeric or short):
        raise ValueError(f"尚未支援的日期原文：{raw}")
    year_present = bool(numeric or (chinese and chinese.group(2)))
    inferred = False
    if year_present:
        evidence = dict(value, raw=text)
        if numeric:
            y, m, d = numeric.groups()
            evidence.update(year=int(y), month=int(m), day=int(d), calendar="gregorian")
            iso = make_iso_date(int(y), int(m), int(d), "gregorian")
        else:
            parsed = parse_date_evidence(evidence)
            iso = make_iso_date(parsed["year"], parsed["month"], parsed["day"], parsed["calendar"])
        reason = None
    else:
        if chinese:
            _, _, m, d = chinese.groups()
        else:
            m, d = short.groups()
        m, d = int(m), int(d)
        if start is not None:
            # Only inherit within the same year; do not silently infer a cross-year range.
            start_date = date.fromisoformat(start["date"])
            candidate = date(start_date.year, m, d)
            if candidate < start_date:
                raise ValueError("無年份的結束日期早於開始日期，需確認是否跨年")
            iso = candidate.isoformat()
            inferred = start["year_inferred"]
            reason = "沿用同一活動的開始年份"
        else:
            result = infer_upcoming_date(m, d, reference_date, weekday)
            iso = result["date"]
            inferred = True
            reason = result["inference_reason"]
    if weekday is not None and date.fromisoformat(iso).isoweekday() != weekday:
        raise ValueError("日期與圖片星期不符，需人工確認")
    return {"date": iso, "year_inferred": inferred, "weekday": weekday, "reason": reason, "weekday_note": weekday_note}


def normalize_events(extracted, reference_date=None):
    if reference_date is None:
        configured = os.environ.get("EVENT_REFERENCE_DATE")
        reference_date = date.fromisoformat(configured) if configured else datetime.now(ZoneInfo("Asia/Taipei")).date()
    if not isinstance(extracted, dict) or not isinstance(extracted.get("events"), list):
        raise ValueError("模型輸出必須包含 events 陣列")
    events = []
    for item in extracted["events"]:
        if not isinstance(item, dict):
            raise ValueError("每筆活動必須是物件")
        event = dict(item)
        issues, notes = [], []
        event.update(date=None, end_date=None, year_inferred=False,
                     reference_date=reference_date.isoformat(), inference_reason=None,
                     date_weekday=None, needs_review=True)
        start = None
        for field in ("date", "end_date"):
            value = item.get(field)
            if value is None:
                if field == "date":
                    issues.append("缺少開始日期")
                continue
            try:
                if field == "end_date" and start is None:
                    raise ValueError("開始日期未確認，無法處理日期範圍")
                resolved = read_date(value, reference_date,
                                     item.get("date_weekday") if field == "date" else None,
                                     start if field == "end_date" else None)
                if field == "end_date" and resolved["date"] < start["date"]:
                    raise ValueError("結束日期早於開始日期")
                event[field] = resolved["date"]
                if field == "date":
                    start = resolved
                    event.update(year_inferred=resolved["year_inferred"],
                                 date_weekday=resolved["weekday"],
                                 inference_reason=resolved["reason"])
                if resolved.get("weekday_note"):
                    notes.append(f"{field}: {resolved['weekday_note']}")
                notes.append(f"{field}: 依原始日期文字解析；" + (resolved["reason"] or "原文明確提供年份"))
            except (ValueError, TypeError, OverflowError) as error:
                issues.append(f"{field}: {error}")
        # A weekday beside a date is not sufficient evidence of weekly recurrence.
        days = item.get("weekdays")
        evidence = item.get("recurrence_raw")
        evidence_ok = isinstance(evidence, str) and bool(re.search(r"每|(?:週|周|星期)[一二三四五六日天].*(?:到|至|～|~|－|-).*(?:週|周|星期)[一二三四五六日天]", evidence))
        if days is not None:
            valid = isinstance(days, list) and bool(days) and all(type(d) is int and 1 <= d <= 7 for d in days)
            if evidence_ok and valid:
                event["weekdays"] = sorted(set(days))
            else:
                event["weekdays"] = None
                event["unconfirmed_weekdays"] = days
                issues.append("每週重複規則缺少明確原文佐證或格式錯誤，需確認")
        else:
            event["weekdays"] = None
            if evidence_ok:
                issues.append("原文有重複規則，但模型未提供 weekdays，需確認")
        event.update(date_issues=issues, date_notes=notes)
        events.append(event)
    return {"events": events}
