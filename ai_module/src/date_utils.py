from datetime import date


def make_iso_date(year, month, day, calendar):
    """將已確認曆法的年月日轉成 YYYY-MM-DD。"""
    year = int(year)
    month = int(month)
    day = int(day)

    if calendar == "roc":
        if year < 1:
            raise ValueError("民國年份必須大於 0")
        year += 1911
    elif calendar != "gregorian":
        raise ValueError("必須明確指定 roc 或 gregorian")

    # 同時驗證月份與日期，避免接受 2 月 30 日。
    return date(year, month, day).isoformat()


if __name__ == "__main__":
    print("民國101年7月12日：",
          make_iso_date(101, 7, 12, "roc"))
    print("民國101年7月31日：",
          make_iso_date(101, 7, 31, "roc"))
    print("西元2026年11月24日：",
          make_iso_date(2026, 11, 24, "gregorian"))

    try:
        make_iso_date(2026, 2, 30, "gregorian")
    except ValueError:
        print("無效日期測試：成功攔截 2 月 30 日")


def validate_year_evidence(value, reference=None):
    """檢查 year 是否符合原始日期中的年份。"""
    import re

    raw = value.get("raw")
    if not isinstance(raw, str):
        raise ValueError("缺少原始日期文字")

    match = re.search(r"(?<!\d)(\d{1,4})\s*年", raw)

    if match is None:
        # 結束日期省略年份時，檢查同一活動的開始日期。
        if not isinstance(reference, dict):
            raise ValueError("原文缺少年份，無法確認")

        ref_raw = reference.get("raw")
        if not isinstance(ref_raw, str):
            raise ValueError("缺少可沿用年份的原文")

        match = re.search(r"(?<!\d)(\d{1,4})\s*年", ref_raw)

        if match is None:
            raise ValueError("開始日期原文也缺少年份")

        if value.get("calendar") != reference.get("calendar"):
            raise ValueError("起訖日期的曆法不一致")

    source_year = int(match.group(1))
    if value.get("year") != source_year:
        raise ValueError(
            f"年份矛盾：原文為 {source_year} 年，"
            f"模型卻填 {value.get('year')}"
        )


def parse_date_evidence(value, reference=None):
    """從日期原文解析年月日；省略年份時參考開始日期。"""
    import re

    if not isinstance(value, dict):
        raise ValueError("日期資料必須是物件")

    raw = value.get("raw")
    if not isinstance(raw, str):
        raise ValueError("缺少原始日期文字")

    cleaned = re.sub(r"\s+", "", raw)

    match = re.fullmatch(
        r"(?:(民國|西元))?"
        r"(?:(\d{1,4})年)?"
        r"(\d{1,2})月(\d{1,2})日(?:止)?",
        cleaned
    )

    if match:
        era, year, month, day = match.groups()
        calendar = (
            {"民國": "roc", "西元": "gregorian"}.get(era)
            or value.get("calendar")
        )

        if year is None:
            if reference is None:
                raise ValueError("缺少年份，需人工確認")

            start = parse_date_evidence(reference)
            year = start["year"]

            if calendar is None:
                calendar = start["calendar"]
            elif calendar != start["calendar"]:
                raise ValueError("起訖日期曆法不一致")
    else:
        match = re.fullmatch(
            r"(\d{4})-(\d{1,2})-(\d{1,2})",
            cleaned
        )
        if not match:
            raise ValueError(f"尚未支援的日期格式：{raw}")

        year, month, day = match.groups()
        calendar = "gregorian"

    parsed = dict(value)
    parsed.update(
        year=int(year),
        month=int(month),
        day=int(day),
        calendar=calendar
    )

    make_iso_date(
        parsed["year"], parsed["month"], parsed["day"],
        parsed["calendar"]
    )
    return parsed
