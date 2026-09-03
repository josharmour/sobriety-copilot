package com.sobrietycopilot.wear

import android.content.Context
import com.google.android.gms.wearable.DataEvent
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService

/**
 * Listens for Data Layer sync events from the phone app
 * and updates local Wear SharedPreferences.
 */
class DataLayerListenerService : WearableListenerService() {

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        val prefs = applicationContext.getSharedPreferences("SobrietyWearPrefs", Context.MODE_PRIVATE)

        for (event in dataEvents) {
            if (event.type == DataEvent.TYPE_CHANGED) {
                val uri = event.dataItem.uri
                if (uri.path == "/sobriety_data") {
                    val dataMap = DataMapItem.fromDataItem(event.dataItem).dataMap
                    val dateIso = dataMap.getString("sobriety_date")
                    val discreet = dataMap.getBoolean("sobriety_discreet", false)
                    val streak = dataMap.getInt("sobriety_streak", 0)
                    val dailyTitle = dataMap.getString("daily_title")
                    val dailyBody = dataMap.getString("daily_body")
                    val dailySource = dataMap.getString("daily_source")

                    prefs.edit()
                        .putString("sobriety_date", dateIso)
                        .putBoolean("sobriety_discreet", discreet)
                        .putInt("sobriety_streak", streak)
                        .putString("daily_title", dailyTitle)
                        .putString("daily_body", dailyBody)
                        .putString("daily_source", dailySource)
                        .apply()
                }
            }
        }
    }
}
