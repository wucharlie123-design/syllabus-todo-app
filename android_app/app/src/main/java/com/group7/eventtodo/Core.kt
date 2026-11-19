package com.group7.eventtodo

import android.content.Context
import com.chaquo.python.Python
import org.json.JSONArray
import org.json.JSONObject

object Core {
    private fun db(context: Context) = context.getDatabasePath("event_todo.db").also { it.parentFile?.mkdirs() }.absolutePath
    @Synchronized fun call(context: Context, method: String, vararg args: Any): String {
        val module = Python.getInstance().getModule("mobile_core")
        module.callAttr("initialize", db(context))
        return module.callAttr(method, db(context), *args).toString()
    }
    @Synchronized fun extract(text: String, reference: String): JSONObject =
        JSONObject(Python.getInstance().getModule("mobile_core").callAttr("extract_events", text, reference).toString())
    fun objectCall(context: Context, method: String, vararg args: Any) = JSONObject(call(context, method, *args))
    fun arrayCall(context: Context, method: String, vararg args: Any) = JSONArray(call(context, method, *args))
}
