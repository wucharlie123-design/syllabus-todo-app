package com.group7.eventtodo

import android.Manifest
import android.app.*
import android.content.*
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.util.concurrent.Executors

object ReminderScheduler {
    const val CHANNEL = "event_todo_reminders"
    fun channel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "活動提醒", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "你設定的活動與待辦提醒"
            enableVibration(true)
        })
    }
    fun allowed(context: Context): Boolean {
        val permission = Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        val manager = context.getSystemService(NotificationManager::class.java)
        val enabledChannel = manager.getNotificationChannel(CHANNEL)?.importance != NotificationManager.IMPORTANCE_NONE
        return permission && manager.areNotificationsEnabled() && enabledChannel
    }
    private fun pending(context: Context, id: Int): PendingIntent = PendingIntent.getBroadcast(
        context, id, Intent(context, ReminderReceiver::class.java).putExtra("reminder_id", id),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    fun schedule(context: Context, id: Int, fireAt: Long): Boolean {
        channel(context)
        val manager = context.getSystemService(AlarmManager::class.java)
        val time = maxOf(fireAt, System.currentTimeMillis() + 1500)
        val exact = Build.VERSION.SDK_INT < 31 || manager.canScheduleExactAlarms()
        try {
            if (exact) manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time, pending(context, id))
            else manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time, pending(context, id))
        } catch (_: SecurityException) {
            manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, time, pending(context, id))
            return false
        }
        return exact
    }
    fun cancel(context: Context, result: JSONObject) {
        val ids = result.optJSONArray("cancelled_reminders") ?: return
        val manager = context.getSystemService(AlarmManager::class.java)
        for (i in 0 until ids.length()) {
            val id = ids.getInt(i)
            val intent = pending(context, id)
            manager.cancel(intent)
            intent.cancel()
            context.getSystemService(NotificationManager::class.java).cancel(id)
        }
    }
    fun restore(context: Context) {
        if (!allowed(context)) return
        val rows = Core.arrayCall(context, "pending_reminders")
        for (i in 0 until rows.length()) {
            val row = rows.getJSONObject(i)
            schedule(context, row.getInt("id"), row.getLong("fire_at"))
        }
    }
}

class ReminderReceiver : BroadcastReceiver() {
    @android.annotation.SuppressLint("MissingPermission") // Checked by allowed() immediately before posting.
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getIntExtra("reminder_id", -1)
        if (id < 0) return
        val pending = goAsync()
        executor.execute {
            try {
                if (!ReminderScheduler.allowed(context)) return@execute
                val raw = Core.call(context, "reminder_for_delivery", id)
                if (raw == "null") return@execute
                val row = JSONObject(raw)
                if (row.getLong("fire_at") > System.currentTimeMillis() + 1000) {
                    ReminderScheduler.schedule(context, id, row.getLong("fire_at"))
                    return@execute
                }
                ReminderScheduler.channel(context)
                val open = PendingIntent.getActivity(context, id,
                    Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP),
                    PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                val prefix = if (row.optString("kind") == "test") "測試提醒：" else "活動提醒："
                val location = row.optString("location").takeIf { it != "null" } ?: ""
                val detail = row.optString("event_date") + " " + row.optString("start_time").replace("null", "") +
                    if (location.isNotEmpty()) "\n地點：$location" else ""
                val notification = NotificationCompat.Builder(context, ReminderScheduler.CHANNEL)
                    .setSmallIcon(android.R.drawable.ic_dialog_info)
                    .setContentTitle(prefix + row.getString("title"))
                    .setContentText(detail).setStyle(NotificationCompat.BigTextStyle().bigText(detail))
                    .setContentIntent(open).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH).build()
                context.getSystemService(NotificationManager::class.java).notify(id, notification)
                Core.call(context, "mark_delivered", id)
            } catch (error: Exception) {
                android.util.Log.e("EventTodo", "Reminder delivery failed", error)
            } finally { pending.finish() }
        }
    }
    companion object { private val executor = Executors.newSingleThreadExecutor() }
}

class RescheduleReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED,
                AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED)) return
        val pending = goAsync()
        executor.execute {
            try { ReminderScheduler.restore(context) }
            catch (error: Exception) { android.util.Log.e("EventTodo", "Reminder restore failed", error) }
            finally { pending.finish() }
        }
    }
    companion object { private val executor = Executors.newSingleThreadExecutor() }
}
