# AI 事件擷取模組 v1

## 定位
Mac 本地執行的事件草稿擷取模組，尚未完成 Android 部署。
使用者必須確認、修改及勾選事件後，才能儲存或排程提醒。

## 環境
Python 3.12；Python 程式使用標準函式庫。
另外安裝並啟動 Ollama，執行：
ollama pull qwen2.5vl:3b

## 命令列
python src/ai_parser.py /完整圖片路徑/image.png

固定測試參考日期：
python src/ai_parser.py /完整圖片路徑/image.png --reference-date 2026-11-18

## Python 呼叫
import sys
sys.path.insert(0, "src")
from ai_parser import extract_events
result = extract_events("/完整圖片路徑/image.png")

## 回傳
events：處理後草稿。
raw_result：原始模型輸出。
metadata：模型、圖片及完整呼叫耗時。

## 串接要求
- 辨識應放在背景工作，避免介面停住。
- 先顯示草稿，讓使用者修改或刪除多餘事件。
- 確認後將 date 對應後端 due_date。
- date=null 時必須補填，不可自動填今天。
- 日期範圍與重複規則不能直接當成單日任務匯入。
- year_inferred=true 表示建議年份，並非圖片提供的年份。
- date_issues、date_notes、unconfirmed_weekdays 應供確認畫面參考。

## 已知限制
- 可能把報名文案誤判為另一筆活動。
- 星期與重複規則可能擷取錯誤或缺漏。
- 日期原文 raw 也是模型產生，仍可能讀錯。
- 日期、時間、地點及活動數量仍須人工確認。
- 目前只使用兩張圖片開發，不能代表一般準確度。
- 本次回歸檢查使用已儲存模型輸出，不代表新推論一定相同。
- 本模組不包含介面、資料庫、提醒或 Android 推理。
