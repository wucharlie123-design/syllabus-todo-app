import base64
import json
import time
import urllib.request
from datetime import date
from pathlib import Path

from date_pipeline import normalize_events
from test_vlm import PROMPT

MODEL = "qwen2.5vl:3b"


def extract_events(image_path, reference_date=None):
    """
    讀取圖片，回傳事件草稿及原始模型輸出。
    reference_date 可填 YYYY-MM-DD，供測試重現。
    所有事件都需要使用者確認後才能儲存。
    """
    image = Path(image_path).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(f"找不到圖片：{image}")

    if image.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("目前支援 PNG、JPG、JPEG")

    reference = (
        date.fromisoformat(reference_date)
        if reference_date is not None
        else None
    )

    payload = {
        "model": MODEL,
        "prompt": PROMPT,
        "images": [
            base64.b64encode(image.read_bytes()).decode("ascii")
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "num_ctx": 4096,
            "num_predict": 2048
        }
    }

    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=600) as response:
        reply = json.load(response)

    elapsed = time.perf_counter() - started

    if reply.get("done_reason") == "length":
        raise ValueError("模型輸出被截斷，不能當成完整辨識結果")

    raw_result = json.loads(reply["response"])
    normalized = normalize_events(
        raw_result,
        reference_date=reference
    )

    return {
        "events": normalized["events"],
        "raw_result": raw_result,
        "metadata": {
            "model": MODEL,
            "image": image.name,
            "elapsed_seconds": round(elapsed, 2),
            "review_required": True
        }
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--reference-date")
    args = parser.parse_args()

    result = extract_events(args.image, args.reference_date)

    output_dir = Path(__file__).resolve().parents[1] / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output = output_dir / f"api-{Path(args.image).stem}-{stamp}.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("結果已儲存：", output)
