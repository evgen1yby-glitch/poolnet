package online.poolnet.mobile

import android.app.Activity
import android.content.Intent
import android.os.Build
import android.net.VpnService
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.modules.core.DeviceEventManagerModule
import android.app.Activity.RESULT_OK

class XrayTunnelModule(private val context: ReactApplicationContext) :
    ReactContextBaseJavaModule(context) {

    private var pending: Promise? = null

    init {
        context.addActivityEventListener(object : com.facebook.react.bridge.ActivityEventListener {
            override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
                if (requestCode == REQUEST_VPN) {
                    pending?.resolve(resultCode == RESULT_OK)
                    pending = null
                }
            }

            override fun onNewIntent(intent: Intent) {}
        })
    }

    override fun getName(): String = "XrayTunnel"

    @ReactMethod
    fun prepare(promise: Promise) {
        val intent = VpnService.prepare(context)
        if (intent == null) {
            promise.resolve(true)
            return
        }
        val activity = context.currentActivity
        if (activity == null) {
            promise.reject("no_activity", "Open the app before enabling VPN")
            return
        }
        pending = promise
        activity.startActivityForResult(intent, REQUEST_VPN)
    }

    @ReactMethod
    fun start(config: String, promise: Promise) {
        XrayTunnelService.lastError = null
        if (VpnService.prepare(context) != null) {
            promise.reject("permission_required", "VPN permission was not granted")
            return
        }
        val intent = Intent(context, XrayTunnelService::class.java).apply {
            action = XrayTunnelService.ACTION_START
            putExtra(XrayTunnelService.EXTRA_CONFIG, config)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(intent)
        } else {
            context.startService(intent)
        }
        Thread {
            val deadline = System.currentTimeMillis() + 12_000
            while (System.currentTimeMillis() < deadline) {
                if (XrayTunnelService.running) {
                    promise.resolve(true)
                    return@Thread
                }
                val error = XrayTunnelService.lastError
                if (!error.isNullOrBlank()) {
                    promise.reject("tunnel_failed", error)
                    return@Thread
                }
                try { Thread.sleep(200) } catch (_: InterruptedException) { break }
            }
            promise.reject("tunnel_timeout", "VPN did not start within 12 seconds")
        }.start()
    }

    @ReactMethod
    fun stop(promise: Promise) {
        val intent = Intent(context, XrayTunnelService::class.java).apply {
            action = XrayTunnelService.ACTION_STOP
        }
        context.startService(intent)
        promise.resolve(true)
    }

    @ReactMethod
    fun status(promise: Promise) {
        val out = Arguments.createMap()
        out.putBoolean("running", XrayTunnelService.running)
        out.putString("error", XrayTunnelService.lastError)
        promise.resolve(out)
    }

    companion object {
        private const val REQUEST_VPN = 0x504e
    }
}
