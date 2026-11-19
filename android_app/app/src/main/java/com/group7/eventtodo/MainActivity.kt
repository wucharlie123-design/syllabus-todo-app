package com.group7.eventtodo

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.*
import android.provider.MediaStore
import android.provider.Settings
import android.text.InputType
import android.view.*
import android.widget.*
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.widget.addTextChangedListener
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.*
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors
import kotlin.math.roundToInt

@Suppress("DEPRECATION")
class MainActivity : Activity() {
    private lateinit var container: LinearLayout
    private lateinit var tasksLayout: LinearLayout
    private lateinit var status: TextView
    private lateinit var permissions: TextView
    private val actionButtons = mutableListOf<Button>()
    private val executor = Executors.newSingleThreadExecutor()
    private var busy = false
    private var editorOpen = false
    private var filter = 0
    private var cameraUri: Uri? = null
    private var preview: Bitmap? = null
    private var drafts = listOf<JSONObject>()
    private var draftIndex = 0
    private val blue = Color.rgb(43, 61, 120)
    private val cream = Color.rgb(248, 245, 237)

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        cameraUri = state?.getString("camera_uri")?.let(Uri::parse)
        container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(cream)
            setPadding(dp(16), dp(16), dp(16), dp(12))
        }
        setContentView(container)
        ViewCompat.setOnApplyWindowInsetsListener(container) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(dp(16)+bars.left, dp(12)+bars.top, dp(16)+bars.right, dp(8)+bars.bottom)
            insets
        }
        container.addView(label("活動待辦助理", 26, true))
        container.addView(label("拍照或選圖，在手機離線整理活動", 14))
        val actions = row()
        listOf("新增任務" to { manualTask() }, "匯入圖片" to { pickImage() }, "拍照辨識" to { takePhoto() }).forEach { (title, action) ->
            val button = button(title, action)
            actions.addView(button, LinearLayout.LayoutParams(0, dp(52), 1f))
            actionButtons.add(button)
        }
        container.addView(actions)
        val secondary = row()
        secondary.addView(button("貼上活動文字") { pasteText() }, LinearLayout.LayoutParams(0, dp(48), 1f))
        secondary.addView(button("提醒權限") { permissionSettings() }, LinearLayout.LayoutParams(0, dp(48), 1f))
        container.addView(secondary)
        permissions = label("", 12)
        container.addView(permissions)
        status = label("先新增任務，或從活動海報擷取資料。", 14)
        status.setPadding(0, dp(8), 0, dp(8))
        container.addView(status)
        val selector = Spinner(this)
        selector.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, listOf("全部任務", "待辦", "已完成"))
        selector.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) {}
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) { filter = position; refreshTasks() }
        }
        container.addView(selector)
        tasksLayout = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val scroll = ScrollView(this).apply { addView(tasksLayout) }
        container.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        try { Core.call(this, "list_tasks"); refreshTasks() }
        catch (error: Exception) { error("初始化失敗", error) }
        ReminderScheduler.channel(this)
    }

    override fun onResume() {
        super.onResume()
        if (::permissions.isInitialized) {
            updatePermissions()
            refreshTasks()
            executor.execute {
                try { ReminderScheduler.restore(applicationContext) }
                catch (error: Exception) { android.util.Log.e("EventTodo", "restore", error) }
            }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("camera_uri", cameraUri?.toString())
        super.onSaveInstanceState(outState)
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).roundToInt()
    private fun row() = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
    private fun label(text: String, size: Int = 16, bold: Boolean = false) = TextView(this).apply {
        this.text = text; textSize = size.toFloat(); setTextColor(blue)
        if (bold) setTypeface(null, android.graphics.Typeface.BOLD)
    }
    private fun button(text: String, action: () -> Unit) = Button(this).apply {
        this.text = text; isAllCaps = false; setOnClickListener { action() }
    }
    private fun toast(text: String) { Toast.makeText(this, text, Toast.LENGTH_LONG).show() }
    private fun error(title: String, exception: Exception) {
        if (!isFinishing && !isDestroyed) AlertDialog.Builder(this).setTitle(title).setMessage(exception.message ?: "請稍後再試").setPositiveButton("確定", null).show()
    }
    private fun fieldValue(json: JSONObject, name: String) = if (json.isNull(name)) "" else json.optString(name, "")

    private fun refreshTasks() {
        if (!::tasksLayout.isInitialized) return
        try {
            val all = Core.arrayCall(this, "list_tasks")
            tasksLayout.removeAllViews()
            var shown = 0
            for (i in 0 until all.length()) {
                val task = all.getJSONObject(i)
                val completed = task.getInt("completed") == 1
                if ((filter == 1 && completed) || (filter == 2 && !completed)) continue
                shown++
                val card = LinearLayout(this).apply {
                    orientation = LinearLayout.HORIZONTAL; setPadding(dp(8), dp(12), dp(8), dp(12)); setBackgroundColor(Color.WHITE)
                }
                val checked = CheckBox(this).apply { isChecked = completed; contentDescription = "完成狀態" }
                checked.setOnCheckedChangeListener { _, value ->
                    try {
                        val result = Core.objectCall(this, "set_completed", task.getInt("id"), if (value) 1 else 0)
                        ReminderScheduler.cancel(this, result)
                        refreshTasks()
                    } catch (error: Exception) { error("更新失敗", error) }
                }
                card.addView(checked)
                val detail = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
                detail.addView(label(task.getString("title") + if (completed) "　✓" else "", 18, true))
                val date = task.getString("event_date")
                val weekday = try { "一二三四五六日"[LocalDate.parse(date).dayOfWeek.value-1] } catch (_: Exception) { '?' }
                val times = listOf(fieldValue(task,"start_time"),fieldValue(task,"end_time")).filter { it.isNotEmpty() }.joinToString("～")
                detail.addView(label("$date（$weekday） $times", 14))
                fieldValue(task,"location").takeIf { it.isNotEmpty() }?.let { detail.addView(label(it, 14)) }
                if (!task.isNull("next_reminder")) {
                    val at = Instant.ofEpochMilli(task.getLong("next_reminder")).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("MM-dd HH:mm"))
                    detail.addView(label("🔔 $at", 13))
                }
                detail.setOnClickListener { taskActions(task) }
                card.addView(detail, LinearLayout.LayoutParams(0, -2, 1f))
                card.setOnClickListener { taskActions(task) }
                val params = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(8) }
                tasksLayout.addView(card, params)
            }
            if (shown == 0) tasksLayout.addView(label("尚無任務。可新增任務或匯入活動圖片。", 16))
        } catch (error: Exception) { error("讀取失敗", error) }
    }

    private fun taskActions(task: JSONObject) {
        if (busy || editorOpen) { toast("請先完成目前的辨識或編輯。"); return }
        val actions = arrayOf("編輯任務", "設定提醒", "10秒後測試通知", "取消提醒", "刪除任務")
        AlertDialog.Builder(this).setTitle(task.getString("title")).setItems(actions) { _, which ->
            val id = task.getInt("id")
            when (which) {
                0 -> showEditor(task, id)
                1 -> setReminder(task)
                2 -> scheduleReminder(id, System.currentTimeMillis()+10000, "test")
                3 -> try {
                    ReminderScheduler.cancel(this, Core.objectCall(this,"cancel_reminders",id)); refreshTasks(); toast("已取消提醒")
                } catch (error: Exception) { error("取消失敗",error) }
                4 -> AlertDialog.Builder(this).setTitle("刪除任務？").setMessage("任務與提醒將一併刪除。")
                    .setNegativeButton("返回",null).setPositiveButton("刪除") { _, _ ->
                        try { ReminderScheduler.cancel(this,Core.objectCall(this,"delete_task",id)); refreshTasks() }
                        catch (error: Exception) { error("刪除失敗",error) }
                    }.show()
            }
        }.setNegativeButton("返回",null).show()
    }

    private fun manualTask() {
        if (busy || editorOpen) return
        preview = null
        showEditor(JSONObject().put("title","").put("date","").put("source_text",""))
    }

    private fun pickImage() {
        if (busy || editorOpen) return
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "image/*"; addCategory(Intent.CATEGORY_OPENABLE)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }
        startActivityForResult(intent, 101)
    }

    private fun takePhoto() {
        if (busy || editorOpen) return
        try {
            val folder = File(cacheDir,"captures").apply { mkdirs() }
            val file = File.createTempFile("event_", ".jpg",folder)
            cameraUri = FileProvider.getUriForFile(this, "$packageName.files", file)
            val intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE).apply {
                putExtra(MediaStore.EXTRA_OUTPUT,cameraUri)
                clipData = ClipData.newRawUri("event",cameraUri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
            }
            startActivityForResult(intent,102)
        } catch (error: Exception) { error("無法開啟相機",error) }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode,resultCode,data)
        if (resultCode != RESULT_OK) return
        val uri = if (requestCode == 102) cameraUri else if (requestCode == 101) data?.data else null
        if (uri != null) recognize(uri)
    }

    private fun setBusy(value: Boolean, text: String) {
        busy = value; status.text = text
        actionButtons.forEach { it.isEnabled = !value }
    }

    private fun recognize(uri: Uri) {
        setBusy(true,"正在手機上辨識文字，請稍候…")
        executor.execute {
            try {
                val source = ImageDecoder.createSource(contentResolver,uri)
                val bitmap = ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
                    decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                    val largest = maxOf(info.size.width,info.size.height)
                    if (largest > 2400) {
                        val ratio = 2400.0/largest
                        decoder.setTargetSize((info.size.width*ratio).toInt().coerceAtLeast(1),(info.size.height*ratio).toInt().coerceAtLeast(1))
                    }
                }
                preview = bitmap
                val image = InputImage.fromBitmap(bitmap,0)
                val chinese = TextRecognition.getClient(ChineseTextRecognizerOptions.Builder().build())
                chinese.process(image).addOnSuccessListener { result ->
                    chinese.close()
                    if (result.text.any { it in '\u3400'..'\u9fff' }) processText(result.text)
                    else {
                        val latin = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
                        latin.process(image).addOnSuccessListener { second ->
                            latin.close(); processText(if (second.text.length > result.text.length) second.text else result.text)
                        }.addOnFailureListener { failure -> latin.close(); processText(result.text) }
                    }
                }.addOnFailureListener { failure ->
                    chinese.close(); setBusy(false,"辨識失敗，可換圖或手動新增。"); error("辨識失敗",failure)
                }
            } catch (error: Exception) {
                runOnUiThread { setBusy(false,"無法讀取圖片。"); error("讀取圖片失敗",error) }
            }
        }
    }

    private fun processText(text: String) {
        if (text.isBlank()) {
            runOnUiThread { setBusy(false,"沒有辨識到文字，可換清楚的圖片或手動新增。"); toast("圖片沒有可辨識文字") }
            return
        }
        executor.execute {
            try {
                val parsed = Core.extract(text, LocalDate.now().toString())
                File(filesDir,"last_ocr.json").writeText(parsed.toString(2))
                val array = parsed.getJSONArray("events")
                drafts = (0 until array.length()).map { array.getJSONObject(it) }
                draftIndex = 0
                runOnUiThread {
                    if (!isDestroyed && !isFinishing) {
                        setBusy(false,"擷取 ${drafts.size} 筆草稿，請確認後儲存。")
                        if (drafts.isNotEmpty()) nextDraft()
                    }
                }
            } catch (error: Exception) { runOnUiThread { setBusy(false,"資料解析失敗，可手動新增。"); error("解析失敗",error) } }
        }
    }

    private fun pasteText() {
        if (busy || editorOpen) return
        val input = EditText(this).apply { hint="貼上活動名稱、日期、時間與地點"; minLines=5; gravity=Gravity.TOP }
        AlertDialog.Builder(this).setTitle("從文字建立活動").setView(input).setNegativeButton("取消",null)
            .setPositiveButton("擷取") { _, _ -> preview=null; setBusy(true,"正在擷取活動資訊…"); processText(input.text.toString()) }.show()
    }

    private fun nextDraft() {
        if (draftIndex >= drafts.size) { status.text="草稿確認結束，可在清單編輯任務與設定提醒。"; refreshTasks(); return }
        val draft = drafts[draftIndex++]
        showEditor(draft,null) { nextDraft() }
    }

    private fun showEditor(draft: JSONObject, taskId: Int? = null, onNext: (() -> Unit)? = null) {
        if (editorOpen) return
        editorOpen = true
        val form = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; setPadding(dp(18),dp(8),dp(18),dp(8)) }
        if (taskId == null && preview != null && fieldValue(draft,"source_text").isNotEmpty()) {
            form.addView(ImageView(this).apply { setImageBitmap(preview); adjustViewBounds=true; scaleType=ImageView.ScaleType.FIT_CENTER },LinearLayout.LayoutParams(-1,dp(160)))
        }
        val notes = draft.optJSONArray("notes")
        if (draft.optBoolean("year_inferred")) form.addView(label("年份為推定，請確認是否為這一年的活動。",14,true))
        if (notes != null) for (i in 0 until notes.length()) form.addView(label(notes.getString(i),13))
        val inputs = linkedMapOf<String,EditText>()
        fun input(key: String, caption: String, value: String = fieldValue(draft,key)): EditText {
            form.addView(label(caption,14,true))
            return EditText(this).apply {
                setText(value); textSize=16f; setSingleLine(true); inputType=InputType.TYPE_CLASS_TEXT
                form.addView(this,LinearLayout.LayoutParams(-1,-2)); inputs[key]=this
            }
        }
        input("title","事件名稱")
        val dateField = input("date","開始日期 YYYY-MM-DD", fieldValue(draft,"date").ifEmpty { fieldValue(draft,"event_date") })
        val hint = label("",13)
        form.addView(hint)
        dateField.addTextChangedListener {
            hint.text = try { "星期"+"一二三四五六日"[LocalDate.parse(it.toString()).dayOfWeek.value-1] } catch (_:Exception) { "請補完整日期，避免建立錯誤提醒。" }
        }
        dateField.setText(dateField.text.toString())
        if (taskId == null) {
            input("end_date","結束日期（單日留白）")
            input("weekdays","每週活動日 1至7，以逗號分隔；單次留白")
        }
        input("start_time","開始時間 HH:MM（未知留白）")
        input("end_time","結束時間 HH:MM（未知留白）")
        input("location","地點（未知留白）")
        val expand = CheckBox(this).apply { text="依日期範圍與每週規則展開任務" }
        if (taskId == null) form.addView(expand)
        form.addView(label("請確認上述內容，再按下方「確認儲存」。",13))
        if (taskId != null) form.addView(label("修改日期或時間會取消舊提醒，請重新設定。",13))
        if (onNext != null) form.addView(label("多抓的日期或活動可以略過，不會自動儲存。",13))
        val scroll = ScrollView(this).apply { addView(form) }
        val dialog = AlertDialog.Builder(this).setTitle(if(taskId != null)"編輯任務" else if(onNext != null)"確認草稿 $draftIndex / ${drafts.size}" else "新增任務")
            .setView(scroll).setPositiveButton("確認儲存",null)
            .setNegativeButton(if(onNext != null)"略過這筆" else "取消") { _, _ -> editorOpen=false; container.post { onNext?.invoke() } }.create()
        dialog.setOnDismissListener { editorOpen=false }
        dialog.setOnCancelListener { status.text="已結束草稿確認，已儲存的任務會保留。" }
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    val payload = JSONObject()
                    inputs.forEach { (key,value) -> payload.put(key,value.text.toString().trim()) }
                    payload.put("confirmed",true).put("expand_range",expand.isChecked)
                    payload.put("source_text",fieldValue(draft,"source_text"))
                    val result = if(taskId == null) Core.objectCall(this,"save_task",payload.toString()) else Core.objectCall(this,"update_task",taskId,payload.toString())
                    ReminderScheduler.cancel(this,result)
                    val cancelled = result.optJSONArray("cancelled_reminders")?.length() ?: 0
                    val count = result.optJSONArray("task_ids")?.length() ?: 1
                    dialog.dismiss(); editorOpen=false; refreshTasks()
                    toast(if(cancelled>0)"已儲存並取消舊提醒，請重新設定" else "已儲存 $count 筆任務")
                    onNext?.invoke()
                } catch(error:Exception) { error("無法儲存",error) }
            }
        }
        dialog.show()
        dialog.window?.setLayout(-1,(resources.displayMetrics.heightPixels*0.88).toInt())
    }

    private fun ensureNotifications(): Boolean {
        if (ReminderScheduler.allowed(this)) return true
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),201)
            toast("允許通知後，請再點一次設定或測試提醒。")
        } else {
            toast("請開啟此 App 的通知權限。")
            startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,packageName))
        }
        return false
    }

    private fun setReminder(task: JSONObject) {
        if (task.getInt("completed")==1) { toast("請先將任務切回待辦"); return }
        if (!ensureNotifications()) return
        var initial = LocalDateTime.now().plusMinutes(5)
        try {
            val time = fieldValue(task,"start_time")
            if(time.isNotEmpty()) {
                val proposed = LocalDateTime.of(LocalDate.parse(task.getString("event_date")),LocalTime.parse(time)).minusMinutes(15)
                if(proposed.isAfter(LocalDateTime.now())) initial=proposed
            }
        } catch (_:Exception) {}
        DatePickerDialog(this,{ _, year, month, day ->
            TimePickerDialog(this,{ _, hour, minute ->
                val selected = LocalDateTime.of(year,month+1,day,hour,minute).atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
                scheduleReminder(task.getInt("id"),selected,"normal")
            },initial.hour,initial.minute,true).show()
        },initial.year,initial.monthValue-1,initial.dayOfMonth).show()
    }

    private fun scheduleReminder(taskId:Int, fireAt:Long, kind:String) {
        if (!ensureNotifications()) return
        try {
            val result=Core.objectCall(this,"schedule_reminder",taskId,fireAt,kind)
            ReminderScheduler.cancel(this,result)
            val exact=ReminderScheduler.schedule(this,result.getInt("reminder_id"),result.getLong("fire_at"))
            refreshTasks()
            status.text=if(kind=="test")"測試通知已設定，請等待約10秒。" else "活動提醒已儲存，可離開 App 等待通知。"
            if(!exact) status.text="已設定一般提醒，系統可能延遲；可在「提醒權限」允許精準鬧鐘。"
        } catch(error:Exception) { error("無法設定提醒",error) }
    }

    private fun updatePermissions() {
        val exact=Build.VERSION.SDK_INT<31 || getSystemService(AlarmManager::class.java).canScheduleExactAlarms()
        permissions.text="通知：${if(ReminderScheduler.allowed(this))"已允許" else "未允許"}　精準提醒：${if(exact)"已允許" else "未允許（可能延遲）"}"
    }

    private fun permissionSettings() {
        val options=if(Build.VERSION.SDK_INT>=31)arrayOf("通知權限","精準提醒／鬧鐘權限") else arrayOf("通知權限")
        AlertDialog.Builder(this).setTitle("提醒設定").setMessage(null).setItems(options) { _, which ->
            if(which==0) {
                if(Build.VERSION.SDK_INT>=33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED)
                    requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS),201)
                else startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,packageName))
            } else if(Build.VERSION.SDK_INT>=31) {
                try { startActivity(Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM,Uri.parse("package:$packageName"))) }
                catch(error:Exception) { error("無法開啟設定",error) }
            }
        }.setNegativeButton("返回",null).show()
    }

    override fun onRequestPermissionsResult(requestCode:Int, permissions:Array<out String>, grantResults:IntArray) {
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        updatePermissions()
        if(requestCode==201 && grantResults.firstOrNull()==PackageManager.PERMISSION_GRANTED) {
            executor.execute { try { ReminderScheduler.restore(applicationContext) } catch (_:Exception) {} }
            toast("通知已允許，現在可以設定或測試提醒。")
        }
    }
}
