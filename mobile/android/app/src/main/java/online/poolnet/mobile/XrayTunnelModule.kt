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
        if (XrayTunnelService.running || XrayTunnelService.starting || XrayTunnelService.stopping) {
            promise.reject("tunnel_busy", "VPN is already running")
            return
        }
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
        // A VpnService is bound by the system, so stopService() alone does not
        // tear it down. Do not start a service just to stop it: on Android 12+
        // that caused a foreground-service timeout when the tunnel was idle.
        if (!XrayTunnelService.running && !XrayTunnelService.starting && !XrayTunnelService.stopping) {
            promise.resolve(true)
            return
        }
        if (!XrayTunnelService.stopping) {
            val intent = Intent(context, XrayTunnelService::class.java).apply {
                action = XrayTunnelService.ACTION_STOP
            }
            context.startService(intent)
        }
        Thread {
            val deadline = System.currentTimeMillis() + 3_000
            while (System.currentTimeMillis() < deadline) {
                if (!XrayTunnelService.running && !XrayTunnelService.starting && !XrayTunnelService.stopping) {
                    promise.resolve(true)
                    return@Thread
                }
                try { Thread.sleep(50) } catch (_: InterruptedException) { break }
            }
            promise.reject("tunnel_stop_timeout", "VPN did not stop within 3 seconds")
        }.start()
    }

    @ReactMethod
    fun status(promise: Promise) {
        val out = Arguments.createMap()
        val stats = XrayTunnelService.statsSnapshot()
        out.putBoolean("running", XrayTunnelService.running)
        out.putString("error", XrayTunnelService.lastError)
        out.putDouble("startedAt", stats[0].toDouble())
        out.putDouble("rxBytes", stats[1].toDouble())
        out.putDouble("txBytes", stats[2].toDouble())
        promise.resolve(out)
    }

    companion object {
        private const val REQUEST_VPN = 0x504e
    }
}
