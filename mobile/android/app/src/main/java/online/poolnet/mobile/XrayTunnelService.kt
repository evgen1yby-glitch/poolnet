package online.poolnet.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.TrafficStats
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.system.OsConstants
import libXray.DialerController
import libXray.LibXray
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.NetworkInterface
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean

class XrayTunnelService : VpnService() {
    companion object {
        const val ACTION_START = "online.poolnet.mobile.START"
        const val ACTION_STOP = "online.poolnet.mobile.STOP"
        const val EXTRA_CONFIG = "config"
        private const val CHANNEL = "poolnet_vpn"
        private const val NOTIFICATION_ID = 4107

        @Volatile var running = false
        @Volatile var starting = false
        @Volatile var stopping = false
        @Volatile var lastError: String? = null
        @Volatile private var currentInstance: XrayTunnelService? = null
        @Volatile private var startedAt = 0L
        @Volatile private var interfaceName: String? = null
        @Volatile private var rxBase = 0L
        @Volatile private var txBase = 0L

        fun statsSnapshot(): LongArray {
            if (!running) return longArrayOf(0L, 0L, 0L)
            val name = interfaceName ?: findInterfaceName("10.111.222.1")?.also {
                interfaceName = it
                rxBase = 0L
                txBase = 0L
            } ?: return longArrayOf(startedAt, 0L, 0L)
            val rx = readCounter(name, true)
            val tx = readCounter(name, false)
            return longArrayOf(
                startedAt,
                (rx - rxBase).coerceAtLeast(0L),
                (tx - txBase).coerceAtLeast(0L),
            )
        }

        private fun markStarted(address: String) {
            val name = findInterfaceName(address)
            interfaceName = name
            rxBase = if (name != null) readCounter(name, true) else 0L
            txBase = if (name != null) readCounter(name, false) else 0L
            startedAt = System.currentTimeMillis()
        }

        private fun resetStats() {
            startedAt = 0L
            interfaceName = null
            rxBase = 0L
            txBase = 0L
        }

        private fun findInterfaceName(address: String): String? {
            return try {
                val interfaces = NetworkInterface.getNetworkInterfaces() ?: return null
                for (iface in Collections.list(interfaces)) {
                    for (inet in Collections.list(iface.inetAddresses)) {
                        if (inet.hostAddress == address) return iface.name
                    }
                }
                null
            } catch (_: Throwable) {
                null
            }
        }

        private fun readCounter(name: String, rx: Boolean): Long {
            return try {
                val traffic = if (rx) TrafficStats.getRxBytes(name) else TrafficStats.getTxBytes(name)
                if (traffic != TrafficStats.UNSUPPORTED.toLong()) {
                    traffic
                } else {
                    val file = if (rx) "rx_bytes" else "tx_bytes"
                    File("/sys/class/net/$name/statistics/$file").readText().trim().toLong()
                }
            } catch (_: Throwable) {
                0L
            }
        }
    }

    private var tunFd: Int? = null
    private val started = AtomicBoolean(false)
    private var worker: Thread? = null
    @Volatile private var runToken = 0

    private val protectController = object : DialerController {
        override fun protectFd(fd: Long): Boolean = protect(fd.toInt())
    }

    override fun onCreate() {
        super.onCreate()
        currentInstance = this
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
        if (!started.compareAndSet(false, true)) {
            lastError = "tunnel already active"
            return
        }
        val token = ++runToken
        lastError = null
        starting = true
        worker = Thread {
            var pendingFd: ParcelFileDescriptor? = null
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
                pendingFd = builder.establish() ?: throw IllegalStateException("VPN interface was not established")
                if (token != runToken) return@Thread
                val fd = pendingFd.detachFd()
                pendingFd = null
                if (token != runToken) {
                    closeFd(fd)
                    return@Thread
                }
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
                    LibXray.setDNS(protectController, "77.88.8.8:53")
                } catch (_: Exception) {
                    // DNS protection is best-effort on older Android builds.
                }
                val request = JSONObject()
                    .put("apiVersion", 3)
                    .put("method", "runXray")
                    .put("payload", JSONObject().put("xrayJson", root.toString()))
                val response = JSONObject(LibXray.invoke(request.toString()))
                if (token != runToken) {
                    stopXray()
                    if (tunFd == fd) tunFd = null
                    closeFd(fd)
                    return@Thread
                }
                if (!response.optBoolean("success")) {
                    throw IllegalStateException(response.optString("error", "Xray failed to start"))
                }
                running = true
                markStarted("10.111.222.1")
                updateNotification("Подключено")
            } catch (error: Throwable) {
                if (token == runToken) {
                    lastError = error.message ?: error.javaClass.simpleName
                    running = false
                    stopTunnel()
                }
            } finally {
                try { pendingFd?.close() } catch (_: Throwable) {}
                if (token == runToken) starting = false
            }
        }.also { it.start() }
    }

    private fun stopTunnel() {
        runToken += 1
        stopping = true
        starting = false
        running = false
        resetStats()
        stopXray()
        try { LibXray.resetDNS() } catch (_: Throwable) {}
        tunFd?.let { closeFd(it) }
        tunFd = null
        started.set(false)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
        stopping = false
    }

    private fun stopXray() {
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
    }

    private fun closeFd(fd: Int) {
        try { ParcelFileDescriptor.adoptFd(fd).close() } catch (_: Throwable) {}
    }

    override fun onRevoke() {
        stopTunnel()
        super.onRevoke()
    }

    override fun onDestroy() {
        // If a new service instance already owns the tunnel, an old instance
        // must not tear it down during the replacement race.
        if (currentInstance === this) {
            if (running || starting || stopping) stopTunnel()
            currentInstance = null
        }
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
