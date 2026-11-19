"""Export the app's last OCR record over an already-authorized USB connection.

Reads only this debug app's last_ocr.json; never uploads data or scans the gallery.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--adb', default=shutil.which('adb') or str(Path.home()/'Library/Android/sdk/platform-tools/adb'))
    cli.add_argument('--output', type=Path, required=True)
    args = cli.parse_args()
    result = subprocess.run([args.adb, 'exec-out', 'run-as', 'com.group7.eventtodo',
                             'cat', 'files/last_ocr.json'], check=True,
                            capture_output=True, text=True, timeout=30)
    record = json.loads(result.stdout)
    if not isinstance(record.get('events'), list) or not isinstance(record.get('text'), str):
        raise ValueError('App紀錄格式不符，請先在手機完成一次辨識')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError('不覆寫既有測試紀錄，請用新的輸出檔名')
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('已匯出至', args.output)
    print('耗時紀錄：', json.dumps(record.get('metrics'), ensure_ascii=False))


if __name__ == '__main__':
    main()
