package com.sobrietycopilot.wear

import android.app.PendingIntent
import android.content.Intent
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.ShortTextComplicationData
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import androidx.wear.watchface.complications.datasource.SuspendingComplicationDataSourceService
import java.util.Calendar
import kotlin.math.roundToInt

/**
 * Wear OS Complication DataSource Service.
 * Provides glanceable sobriety day count on Wear OS watch faces.
 */
class SobrietyComplicationService : SuspendingComplicationDataSourceService() {

    override fun getPreviewData(type: ComplicationType): ComplicationData? {
        if (type != ComplicationType.SHORT_TEXT) return null
        return ShortTextComplicationData.Builder(
            text = PlainComplicationText.Builder("92d").build(),
            contentDescription = PlainComplicationText.Builder("Sobriety Day Counter").build()
        ).setTitle(PlainComplicationText.Builder("SOBER").build()).build()
    }

    override suspend fun onComplicationRequest(request: ComplicationRequest): ComplicationData? {
        if (request.complicationType != ComplicationType.SHORT_TEXT) return null

        val prefs = applicationContext.getSharedPreferences("SobrietyWearPrefs", MODE_PRIVATE)
        val dateIso = prefs.getString("sobriety_date", null)
        val discreet = prefs.getBoolean("sobriety_discreet", false)

        val text = if (dateIso.isNullOrEmpty()) {
            "—"
        } else {
            val days = daysSince(dateIso)
            if (discreet) "$days" else "${days}d"
        }

        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        val pendingIntent = if (launchIntent != null) {
            PendingIntent.getActivity(
                this,
                0,
                launchIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
        } else null

        return ShortTextComplicationData.Builder(
            text = PlainComplicationText.Builder(text).build(),
            contentDescription = PlainComplicationText.Builder("Sobriety Days: $text").build()
        )
            .setTitle(PlainComplicationText.Builder(if (discreet) "DAY" else "SOBER").build())
            .setTapAction(pendingIntent)
            .build()
    }

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
        return (diff / 86_400_000.0).roundToInt().coerceAtLeast(0)
    }
}
