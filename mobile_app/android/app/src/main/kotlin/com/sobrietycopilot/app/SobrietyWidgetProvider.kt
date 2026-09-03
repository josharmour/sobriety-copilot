package com.sobrietycopilot.app

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.view.View
import android.widget.RemoteViews
import es.antonborri.home_widget.HomeWidgetProvider
import java.util.Calendar
import kotlin.math.roundToInt

/**
 * Home-screen sobriety counter. The Flutter side stores the sobriety date
 * (`sobriety_date`, yyyy-MM-dd, local calendar) and the discreet flag via
 * home_widget; the day count is recomputed here at render time so periodic
 * updates (updatePeriodMillis) keep it correct across midnight with no
 * background work in Dart.
 */
class SobrietyWidgetProvider : HomeWidgetProvider() {

    override fun onUpdate(
        context: Context,
        appWidgetManager: AppWidgetManager,
        appWidgetIds: IntArray,
        widgetData: SharedPreferences
    ) {
        val dateIso = widgetData.getString("sobriety_date", null)
        val discreet = widgetData.getBoolean("sobriety_discreet", false)

        for (widgetId in appWidgetIds) {
            val views = RemoteViews(context.packageName, R.layout.sobriety_widget)

            if (dateIso.isNullOrEmpty()) {
                views.setTextViewText(R.id.widget_days, "—")
                views.setTextViewText(R.id.widget_subtitle, "Tap to set your date")
                views.setViewVisibility(R.id.widget_subtitle, View.VISIBLE)
            } else {
                val days = daysSince(dateIso)
                when {
                    discreet -> {
                        views.setTextViewText(R.id.widget_days, "Day $days")
                        views.setViewVisibility(R.id.widget_subtitle, View.GONE)
                    }
                    days <= 0 -> {
                        views.setTextViewText(R.id.widget_days, "Day one")
                        views.setTextViewText(R.id.widget_subtitle, "One day at a time")
                        views.setViewVisibility(R.id.widget_subtitle, View.VISIBLE)
                    }
                    else -> {
                        val (target, label) = nextMilestone(days)
                        views.setTextViewText(R.id.widget_days, "$days")
                        views.setTextViewText(
                            R.id.widget_subtitle,
                            "days sober · ${target - days} to $label"
                        )
                        views.setViewVisibility(R.id.widget_subtitle, View.VISIBLE)
                    }
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
            views.setOnClickPendingIntent(R.id.widget_root, pending)

            appWidgetManager.updateAppWidget(widgetId, views)
        }
    }

    /** Completed local calendar days since [dateIso] (yyyy-MM-dd); 0 on that day. */
    private fun daysSince(dateIso: String): Int {
        val parts = dateIso.split("-")
        if (parts.size != 3) return 0
        val start = Calendar.getInstance().apply {
            clear()
            set(parts[0].toInt(), parts[1].toInt() - 1, parts[2].toInt())
        }
        val today = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        val diff = today.timeInMillis - start.timeInMillis
        // Rounding absorbs DST offsets (+/- 1h) in the millisecond diff.
        return (diff / 86_400_000.0).roundToInt().coerceAtLeast(0)
    }

    /** Mirrors kMilestones in lib/features/milestones/sobriety_tracker.dart. */
    private fun nextMilestone(days: Int): Pair<Int, String> {
        val targets = intArrayOf(1, 7, 14, 30, 60, 90, 180, 270, 365, 545, 730)
        val labels = arrayOf(
            "24 hours", "1 week", "2 weeks", "30 days", "60 days", "90 days",
            "6 months", "9 months", "1 year", "18 months", "2 years"
        )
        for (i in targets.indices) {
            if (days < targets[i]) return targets[i] to labels[i]
        }
        val years = days / 365 + 1
        return years * 365 to "$years years"
    }
}
