package com.sobrietycopilot.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.view.View
import android.widget.RemoteViews
import com.sobrietycopilot.app.R
import es.antonborri.home_widget.HomeWidgetProvider
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Home-screen daily reflection widget.
 * Displays the current day's reading title, snippet, and citation.
 */
class DailyReflectionWidgetProvider : HomeWidgetProvider() {

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
        widgetData: SharedPreferences
    ) {
        val title = widgetData.getString("daily_title", null)
        val body = widgetData.getString("daily_body", null)
        val source = widgetData.getString("daily_source", null)
        val dateIso = widgetData.getString("daily_date", null)

        val displayDate = if (!dateIso.isNullOrEmpty()) {
            try {
                val parsed = SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(dateIso)
                SimpleDateFormat("MMM d", Locale.US).format(parsed ?: Date())
            } catch (_: Exception) {
                SimpleDateFormat("MMM d", Locale.US).format(Date())
            }
        } else {
            SimpleDateFormat("MMM d", Locale.US).format(Date())
        }

        for (widgetId in appWidgetIds) {
            val views = RemoteViews(context.packageName, R.layout.daily_reflection_widget)

            views.setTextViewText(R.id.daily_widget_date, displayDate)

            if (title.isNullOrEmpty() && body.isNullOrEmpty()) {
                views.setTextViewText(R.id.daily_widget_title, "Daily Reflection")
                views.setTextViewText(R.id.daily_widget_body, "Open Sobriety Copilot to view today's reading and reflection.")
                views.setTextViewText(R.id.daily_widget_source, "Recovery Literature")
            } else {
                views.setTextViewText(R.id.daily_widget_title, title ?: "Daily Reflection")
                views.setTextViewText(R.id.daily_widget_body, body ?: "")
                if (!source.isNullOrEmpty()) {
                    views.setTextViewText(R.id.daily_widget_source, source)
                    views.setViewVisibility(R.id.daily_widget_source, View.VISIBLE)
                } else {
                    views.setViewVisibility(R.id.daily_widget_source, View.GONE)
                }
            }

            val launch = Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
            val pending = PendingIntent.getActivity(
                context,
                0,
                launch,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            views.setOnClickPendingIntent(R.id.daily_widget_root, pending)

            appWidgetManager.updateAppWidget(widgetId, views)
        }
    }
}
