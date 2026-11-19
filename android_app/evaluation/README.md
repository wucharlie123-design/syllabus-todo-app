# 辨識評估與優化

目前包含一張既有海報的實機 OCR 紀錄，以及三個人工整理文字的開發案例。
它們不是獨立測試集，也不是四張新圖片。請勿將結果當成一般辨識準確率。

## 執行

在共用專案根目錄：

```bash
python3 android_app/evaluation/evaluate.py --output android_app/evaluation/reports/current.json
python3 -m unittest discover -s android_app/tests -v
```

輸出 JSON 與同名 Markdown，列出每案欄位正確數、完全正確活動數、漏抓／多抓及主機解析耗時。
`--parser /path/mobile_core.py` 可指定另一版本的 Python 解析器，用同一份資料比較。

## 正確理解分數

- 活動先做一對一最佳配對，順序不影響結果，重複預測不能重複領分。
- 欄位只做 Unicode 全半形與空白正規化；錯字不會因「很像」就算對。
- 完整活動 precision = 所有已標註欄位皆正確的活動數 / 預測活動數。
- 完整活動 recall = 所有已標註欄位皆正確的活動數 / 標準活動數。
- 欄位表同時顯示非空答案分數，避免大量空欄位使結果看起來很好。
- 多抓活動另外列出並降低完整活動 precision；欄位分數本身不懲罰多抓。
- `historical_recorded_prediction` 是當時存下的結果；`current_parser_replay` 是現行解析器重播同一份 OCR 文字。
- 重播沒有重新執行 OCR，不能聲稱 OCR 本身改善；主機 Python 耗時也不是手機整體耗時。

## 收集新圖片

1. 收集30至50張一般活動海報，涵蓋清晰截圖、實拍、花體字與多活動版面。
2. 在看程式輸出前，依原圖人工寫好事件名稱、日期、時間、地點及活動數量。
3. 將圖片分組：調整程式用 development，最後保留未用來調整的 holdout。相同海報的照片／截圖必須在同一組。
4. 在手機匯入圖片。辨識完成時就記錄，人工改完的資料不可當作模型原始輸出。
5. 新版App把解碼加OCR、Python處理及總耗時記在 `last_ocr.json` 的 `metrics` 中；總耗時不含人工確認。初次啟動與後續辨識分開比較。

USB已授權時匯出（只有開發測試APK支援 run-as）：

```bash
python3 android_app/evaluation/capture_last.py --output android_app/evaluation/local_data/image-001-record.json
```

每次辨識會覆蓋手機的 last_ocr.json，下一張前先匯出。工具不覆寫既有電腦紀錄。
含私人圖片文字的 local_data 及 reports 目錄預設不加入 Git。

建立 `local_data/cases/image-001.json`，內容參照下例。標準答案須由人對照原圖填寫；沒有提供的欄位填空字串，未標註的欄位可省略。

```json
{
  "id": "image-001",
  "split": "holdout",
  "input_kind": "recorded_phone_ocr",
  "reference_date": "2026-11-19",
  "record": "../image-001-record.json",
  "expected": [{
    "title": "依原圖填寫",
    "date": "2026-12-05",
    "start_time": "14:00",
    "end_time": "16:00",
    "location": "依原圖填寫"
  }]
}
```

`reference_date` 請使用該次紀錄中的參考日期。沒有寫年份的海報應另外標註月日與年份推定評估；不要把建議年份當作原圖真實年份。現行評分器以完整 date 比對，尚未另算月日分數。

```bash
python3 android_app/evaluation/evaluate.py --cases android_app/evaluation/local_data/cases --output android_app/evaluation/reports/holdout.json
```

若要比較其他OCR引擎，保留相同圖片與標準答案，分別產生相同 `text`/`events` 格式的紀錄，再比較。現階段沒有自動訓練、替換OCR引擎或呼叫雲端API。

## 這次修正

雙活動開發案例原先把第一筆的時間和地點複製到第二筆，修正為依活動文字區段取值。
該案例完全正確活動由1/2變為2/2，另加測後一筆缺少時間／地點時保持空白。
既有海報的標題錯字仍未修正；不以規則猜字冒充OCR改善。
