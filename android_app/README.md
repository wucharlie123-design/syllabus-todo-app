# 活動待辦助理：Android 手機 MVP

此資料夾是可獨立開啟、編譯及安裝的 Android 專案；不是桌面程式的網頁或遠端控制畫面。

## 架構

- Kotlin：手機畫面、相簿與相機、內建 ML Kit OCR、Android 鬧鐘與通知。
- Python 3.12（Chaquopy）：OCR文字轉事件草稿、日期／民國換算／年份推定、欄位驗證、SQLite待辦及提醒資料。
- 中英文 OCR 模型與 Python 執行環境隨 APK 打包。執行時不需要 Mac、Ollama 或雲端 API。
- Manifest 移除網際網路權限；初次編譯需下載建置依賴，但手機辨識可離線執行。
- 事件理解目前採規則解析，並非將桌面的 Qwen VLM 移植到手機。複雜排版或多活動資訊需人工確認。

## 功能

1. 新增、編輯、完成、刪除與篩選任務。
2. 相簿選圖、呼叫手機相機拍照、貼上活動文字。
3. 圖片OCR後擷取事件、日期、時間與地點，確認後才儲存。
4. 缺少年份依日期與星期推定，明確提示人工確認。
5. 多日活動可限定每週規則，展開成最多366天內的單日任務。
6. 提醒寫入SQLite，再交由Android AlarmManager排程；通知不依賴畫面保持開啟。
7. 通知權限及精準鬧鐘權限設定入口；缺少精準權限時明確提示可能延遲。
8. 支援重開手機、更新App、重開App後恢復未觸發提醒。
9. 修改任務時間或完成／刪除任務會取消舊提醒。

## 裝置與安裝

Android 9（API28）以上，arm64-v8a 或 x86_64。已驗收裝置：vivo X300 Pro V2514、Android16。
以團隊提供的測試APK安裝即可；不必安裝Python或登入帳號。

提醒測試需允許通知，並建議允許「鬧鐘與提醒」的精準權限。系統強制停止App會暫停其鬧鐘，需重新開啟App；清除資料、解除安裝也會刪除任務。此測試版不依賴長駐前景服務。

## 從原始碼建置

使用 Android Studio 開啟本資料夾，不是上層的 Tkinter 桌面專案。

- Android Gradle Plugin 9.5.0，Gradle Wrapper 9.6.0。
- compile SDK37.0，Build Tools36，minSDK28，targetSDK35。
- Chaquopy17.2.0，手機Python3.12。建置電腦也需可用的Python3.12。
- Android Studio內建JDK可用於建置；Java與Kotlin程式碼目標為17。

Mac上可執行：

```bash
python3.12 build_apk.py
```

或在 Android Studio 選 Build APK。若命令列有多個Python版本，可用環境變數 EVENT_TODO_BUILD_PYTHON 指定Python3.12執行檔。

```bash
./gradlew assembleDebug lintDebug
```

輸出：`app/build/outputs/apk/debug/app-debug.apk`。`local.properties`、Gradle快取、APK和簽章檔不應加入Git。

## Python測試

從共用專案根目錄：

```bash
python3 -m unittest discover -s android_app/tests -v
```

這些測試驗證日期擷取、確認後儲存、資料持久化、任務編輯及提醒生命週期，不等於已完成所有手機硬體測試。實機驗收結果另見 MOBILE_ACCEPTANCE.md。

## 辨識品質評估

評估工具與資料收集方法見 [evaluation/README.md](evaluation/README.md)。目前一張既有海報的手機OCR紀錄加上三個人工文字案例，只供開發定位問題，不能作為一般準確率。
0.2.1加入手機辨識耗時紀錄，並修正多活動共用第一筆時間與地點的問題；這些改善不等於已換OCR模型或完成模型訓練。

## 限制

OCR與規則解析可能漏抓、讀錯或多抓活動；需要使用者確認。沒有明確日期時維持空白，不能直接儲存。重複活動編輯以單筆已展開任務為單位。跨日時間須拆成單日任務或手動調整。本版未加入社交共享、日曆同步與自動衝堂分析。
