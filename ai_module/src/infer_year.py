from datetime import date


def infer_upcoming_date(month, day, reference_date, weekday=None):
    """
    找最近的未來日期，包含今天。
    weekday：週一=1，週日=7；未提供則不限制星期。
    最多搜尋到參考年份之後的第10年。
    """
    if weekday is not None and weekday not in range(1, 8):
        raise ValueError("星期必須是 1 到 7")

    for year in range(reference_date.year, reference_date.year + 11):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue

        if candidate < reference_date:
            continue

        if weekday is not None and candidate.isoweekday() != weekday:
            continue

        return {
            "date": candidate.isoformat(),
            "year_inferred": True,
            "reference_date": reference_date.isoformat(),
            "inference_reason": (
                "最近的未來日期，且符合圖片星期"
                if weekday is not None
                else "最近的未來日期，圖片未提供星期"
            ),
            "needs_review": True
        }

    raise ValueError("搜尋範圍內沒有符合日期，需人工確認")


if __name__ == "__main__":
    import json

    result = infer_upcoming_date(
        month=4,
        day=23,
        weekday=5,
        reference_date=date(2026, 11, 18)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
