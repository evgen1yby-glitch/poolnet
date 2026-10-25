package online.poolnet.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.system.OsConstants
import libXray.DialerController
import libXray.LibXray
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicBoolean

class XrayTunnelService : VpnService() {
    companion object {
        const val ACTION_START = "online.poolnet.mobile.START"
        const val ACTION_STOP = "online.poolnet.mobile.STOP"
        const val EXTRA_CONFIG = "config"
        private const val CHANNEL = "poolnet_vpn"
        private const val NOTIFICATION_ID = 4107

        @Volatile var running = false
        @Volatile var lastError: String? = null
    }

    private var tunFd: Int? = null
    private val started = AtomicBoolean(false)
    private var worker: Thread? = null

    private val protectController = object : DialerController {
        override fun protectFd(fd: Long): Boolean = protect(fd.toInt())
    }

    override fun onCreate() {
        super.onCreate()
        LibXray.registerDialerController(protectController)
        LibXray.registerListenerController(protectController)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopTunnel()
                return START_NOT_STICKY
            }
            ACTION_START -> {
                val config = intent.getStringExtra(EXTRA_CONFIG)
                if (config.isNullOrBlank()) {
                    lastError = "empty Xray config"
                    stopSelf()
                    return START_NOT_STICKY
                }
                startForegroundNotification("Подключение…")
                startTunnel(config)
                return START_NOT_STICKY
            }
        }
        return START_NOT_STICKY
    }

    private fun startTunnel(configJson: String) {
        if (!started.compareAndSet(false, true)) return
        lastError = null
        worker = Thread {
            try {
                val builder = Builder()
                    .setSession("PoolNet")
                    .setMtu(1500)
                    .addAddress("10.111.222.1", 30)
                    .addRoute("0.0.0.0", 0)
                    // IPv4-only by design: not routing IPv6 would leak it
                    // outside the tunnel, so the family is blocked instead.
                    .allowFamily(OsConstants.AF_INET)
                    .addDnsServer("1.1.1.1")
                    .setBlocking(true)
                // Xray's outbound sockets are protected by the controller below.
                // The app itself stays inside the tunnel so a post-start probe
                // measures the same path the user's browser will take.
                val pfd = builder.establish() ?: throw IllegalStateException("VPN interface was not established")
                val fd = pfd.detachFd()
                tunFd = fd

                val root = JSONObject(configJson)
                root.put(
                    "inbounds",
                    JSONArray().put(
                        JSONObject()
                            .put("tag", "tun-in")
                            .put("protocol", "tun")
                            .put("settings", JSONObject().put("name", "poolnet-tun").put("mtu", 1500))
                            .put(
                                "sniffing",
                                JSONObject()
                                    .put("enabled", true)
                                    .put("destOverride", JSONArray().put("http").put("tls").put("quic"))
                            )
                    )
                )
                val env = root.optJSONObject("env") ?: JSONObject()
                env.put("xray.tun.fd", fd.toString())
                root.put("env", env)

                try {
                    LibXray.setDNS(protectController, "1.1.1.1:53")
                } catch (_: Exception) {
                    // DNS protection is best-effort on older Android builds.
                }
                val request = JSONObject()
                    .put("apiVersion", 3)
                    .put("method", "runXray")
                    .put("payload", JSONObject().put("xrayJson", root.toString()))
                val response = JSONObject(LibXray.invoke(request.toString()))
                if (!response.optBoolean("success")) {
                    throw IllegalStateException(response.optString("error", "Xray failed to start"))
                }
                running = true
                updateNotification("Защищено")
            } catch (error: Throwable) {
                lastError = error.message ?: error.javaClass.simpleName
                running = false
                stopTunnel()
            }
        }.also { it.start() }
    }

    private fun stopTunnel() {
        running = false
        try {
            LibXray.invoke(
                JSONObject()
                    .put("apiVersion", 3)
                    .put("method", "stopXray")
                    .put("payload", JSONObject())
                    .toString()
            )
        } catch (_: Throwable) {
        }
        try { LibXray.resetDNS() } catch (_: Throwable) {}
        tunFd?.let { fd ->
            try { ParcelFileDescriptor.adoptFd(fd).close() } catch (_: Throwable) {}
        }
        tunFd = null
        started.set(false)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onRevoke() {
        stopTunnel()
        super.onRevoke()
    }

    override fun onDestroy() {
        if (running) stopTunnel()
        super.onDestroy()
    }

    private fun startForegroundNotification(text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(CHANNEL, "PoolNet VPN", NotificationManager.IMPORTANCE_LOW)
            channel.description = "Состояние VPN-туннеля PoolNet"
            manager.createNotificationChannel(channel)
        }
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL)
        } else {
            Notification.Builder(this)
        }
            .setContentTitle("PoolNet")
            .setContentText(text)
            .setSmallIcon(applicationInfo.icon)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun updateNotification(text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, CHANNEL)
        } else {
            Notification.Builder(this)
        }
            .setContentTitle("PoolNet")
            .setContentText(text)
            .setSmallIcon(applicationInfo.icon)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        manager.notify(NOTIFICATION_ID, notification)
    }
}
