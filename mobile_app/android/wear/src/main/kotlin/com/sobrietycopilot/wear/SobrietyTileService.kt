package com.sobrietycopilot.wear

import android.content.Context
import androidx.wear.protolayout.ActionBuilders
import androidx.wear.protolayout.ColorBuilders.argb
import androidx.wear.protolayout.DeviceParametersBuilders
import androidx.wear.protolayout.DimensionBuilders.dp
import androidx.wear.protolayout.DimensionBuilders.sp
import androidx.wear.protolayout.LayoutElementBuilders
import androidx.wear.protolayout.ModifiersBuilders
import androidx.wear.protolayout.ResourceBuilders
import androidx.wear.protolayout.TimelineBuilders
import androidx.wear.protolayout.material.Colors
import androidx.wear.protolayout.material.Text
import androidx.wear.protolayout.material.Typography
import androidx.wear.protolayout.material.layouts.PrimaryLayout
import androidx.wear.tiles.RequestBuilders
import androidx.wear.tiles.TileBuilders
import androidx.wear.tiles.TileService
import com.google.common.util.concurrent.Futures
import com.google.common.util.concurrent.ListenableFuture
import java.util.Calendar
import kotlin.math.roundToInt

/**
 * Wear OS Tile providing a glanceable card for sobriety days and daily reflection snippet.
 */
class SobrietyTileService : TileService() {

    override fun onTileRequest(requestParams: RequestBuilders.TileRequest): ListenableFuture<TileBuilders.Tile> {
        val prefs = applicationContext.getSharedPreferences("SobrietyWearPrefs", Context.MODE_PRIVATE)
        val dateIso = prefs.getString("sobriety_date", null)
        val discreet = prefs.getBoolean("sobriety_discreet", false)
        val dailyTitle = prefs.getString("daily_title", "Daily Reflection")
        val dailyBody = prefs.getString("daily_body", "One day at a time.")

        val days = if (!dateIso.isNullOrEmpty()) daysSince(dateIso) else 0
        val dayText = if (discreet) "Day $days" else "$days Days Sober"

        val rootLayout = PrimaryLayout.Builder(requestParams.deviceConfiguration)
            .setPrimaryLabelTextContent(
                Text.Builder(this, dayText)
                    .setTypography(Typography.TYPOGRAPHY_TITLE2)
                    .setColor(argb(0xFF38BDF8.toInt()))
                    .build()
            )
            .setContent(
                LayoutElementBuilders.Column.Builder()
                    .addContent(
                        Text.Builder(this, dailyTitle ?: "Daily Reflection")
                            .setTypography(Typography.TYPOGRAPHY_TITLE3)
                            .setColor(argb(0xFFFFFFFF.toInt()))
                            .setMaxLines(1)
                            .build()
                    )
                    .addContent(
                        LayoutElementBuilders.Spacer.Builder().setHeight(dp(4f)).build()
                    )
                    .addContent(
                        Text.Builder(this, dailyBody ?: "")
                            .setTypography(Typography.TYPOGRAPHY_BODY2)
                            .setColor(argb(0xFFCBD5E1.toInt()))
                            .setMaxLines(3)
                            .build()
                    )
                    .build()
            )
            .build()

        val timeline = TimelineBuilders.Timeline.Builder()
            .addTimelineEntry(
                TimelineBuilders.TimelineEntry.Builder()
                    .setLayout(LayoutElementBuilders.Layout.Builder().setRoot(rootLayout).build())
                    .build()
            )
            .build()

        val tile = TileBuilders.Tile.Builder()
            .setResourcesVersion("1")
            .setTimeline(timeline)
            .setFreshnessIntervalMillis(1800000)
            .build()

        return Futures.immediateFuture(tile)
    }

    override fun onTileResourcesRequest(requestParams: RequestBuilders.ResourcesRequest): ListenableFuture<ResourceBuilders.Resources> {
        return Futures.immediateFuture(ResourceBuilders.Resources.Builder().setVersion("1").build())
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
