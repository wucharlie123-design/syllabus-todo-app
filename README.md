# Campus AI Syllabus To-Do Assistant

已驗收的 **Mac 桌面 MVP**：圖片匯入 → 本地模型辨識 → 人工確認草稿 → SQLite 任務清單 → 編輯／完成／刪除 → App 內提醒。

目前版本不包含 Android App 或 App 關閉時的背景系統通知。

## 環境

已測環境：Apple Silicon Mac、8 GB RAM、Python 3.12、Ollama `qwen2.5vl:3b`。
Python 程式使用標準函式庫；Python 安裝需包含 Tkinter。

## 啟動

先安裝並開啟 [Ollama](https://ollama.com/download)，下載模型：

```bash
ollama pull qwen2.5vl:3b
```

第一次下載需要網路，模型下載完成後核心辨識可在本機執行。完整斷網情境仍需另行驗證，未列入本次人工驗收。

在專案根目錄執行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m tkinter
```

確認 Tkinter 測試視窗可開啟後關閉，再執行：

```bash
python main_ui.py
```

若 `python -m tkinter` 報缺少 `_tkinter`，請使用包含 Tkinter 的 Python 安裝；建立 venv 不會補裝缺少的標準函式庫元件。
亦可使用 `run_desktop.command`（會優先使用開發者原有 AI 專案環境，否則使用 `python3`）。

## 使用

1. 按「匯入圖片」，選擇 PNG／JPG／JPEG。辨識在背景執行。
2. 查看原圖，修正草稿，略過多餘活動。缺少年份的日期只是推定。
3. 勾選確認後儲存；日期不完整時不可存成今天。
4. 多日活動需填結束日期及重複規則，明確勾選展開為單日任務。
5. 選取任務後可編輯、切換完成狀態或刪除。修改時間會取消舊提醒，需重新設定。
6. 按「設定提醒」，或用「10秒後測試提醒」快速展示。
7. 提醒須保持 App 開啟；關閉或休眠期間不會跳出，重開或喚醒後補提醒。

## 驗證

```bash
python -m unittest test_desktop_flow test_desktop_reminders -v
```

25項無介面測試通過。涵蓋欄位驗證、資料持久化、多日任務、交易回復、任務編輯、提醒更新／取消／補顯示；模型回應使用模擬資料，不代表真實模型準確度測試。

使用者已在 Mac 完成人工驗收：圖片辨識、草稿確認儲存、略過多餘活動、重開資料保留、完成狀態切換、任務編輯及10秒提醒彈窗。

## 資料與限制

- 正式資料：專案根目錄 `offline_assistant.db`，含任務與提醒。
- 原始模型輸出：`integration_results/`；程式更新備份：`backups/`。
- 這些本機檔案與虛擬環境已設為 Git 忽略，請勿加入共用版本。
- 一次開啟一個 App，避免同一提醒被不同視窗重複顯示。
- 模型可能多抓活動、漏抓每週規則、讀錯文字；必須人工確認。
- 只有兩張開發圖片，尚無一般準確率、手機部署與效能保證。
- 衝堂偵測、外部日曆同步及手機通知不包含在這版。

詳細操作見 [DESKTOP_FLOW.md](DESKTOP_FLOW.md)，展示流程見 [MVP_DEMO.md](MVP_DEMO.md)。
