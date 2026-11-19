import { Ionicons } from '@expo/vector-icons';
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Animated, {
  Easing,
  cancelAnimation,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { formatBytes, formatDuration } from '@/lib/format';
import { useT } from '@/lib/use-t';
import { useAppStore } from '@/store/app';
import { radius, space, useTheme } from '@/theme';

export function SessionStats() {
  const theme = useTheme();
  const t = useT();
  const connection = useAppStore((state) => state.connection);
  const language = useAppStore((state) => state.language);
  const startedAt = useAppStore((state) => state.sessionStartedAt);
  const rxBytes = useAppStore((state) => state.rxBytes);
  const txBytes = useAppStore((state) => state.txBytes);
  const exitIp = useAppStore((state) => state.exitIp);
  const syncTunnel = useAppStore((state) => state.syncTunnel);
  const refreshExitIp = useAppStore((state) => state.refreshExitIp);
  const reduceMotion = useReducedMotion();

  const connected = connection === 'connected';
  const connecting = connection === 'connecting' || connection === 'reconnecting';
  const [now, setNow] = useState(0);

  useEffect(() => {
    if (!connected) return;
    const tick = () => setNow(Date.now());
    const kickoff = setTimeout(tick, 0);
    const timer = setInterval(tick, 1000);
    return () => {
      clearTimeout(kickoff);
      clearInterval(timer);
    };
  }, [connected]);

  useEffect(() => {
    if (!connected) return;
    void syncTunnel();
    const timer = setInterval(() => void syncTunnel(), 2000);
    return () => clearInterval(timer);
  }, [connected, syncTunnel]);

  useEffect(() => {
    if (!connected) return;
    void refreshExitIp();
    const timer = setInterval(() => void refreshExitIp(), 60_000);
    return () => clearInterval(timer);
  }, [connected, refreshExitIp]);

  const pulse = useSharedValue(0);
  useEffect(() => {
    cancelAnimation(pulse);
    if (!connected || reduceMotion) {
      pulse.set(0);
      return;
    }
    pulse.set(0);
    pulse.set(
      withRepeat(
        withTiming(1, { duration: 1600, easing: Easing.out(Easing.quad) }),
        -1,
        false,
      ),
    );
    return () => cancelAnimation(pulse);
  }, [connected, pulse, reduceMotion]);

  const pulseStyle = useAnimatedStyle(() => ({
    opacity: (1 - pulse.value) * 0.35,
    transform: [{ scale: 1 + pulse.value * 2.2 }],
  }));

  const elapsed = connected && startedAt ? Math.max(0, (now - startedAt) / 1000) : 0;
  const timeText = connected
    ? formatDuration(elapsed)
    : connecting
      ? '--:--:--'
      : '00:00:00';
  const statusText = connected
    ? t('home.stats.live')
    : connecting
      ? t('home.stats.connecting')
      : t('home.stats.offline');
  const ipText = connected ? exitIp ?? '…' : '—';
  const totalBytes = rxBytes + txBytes;
  const downloadRatio = totalBytes > 0 ? rxBytes / totalBytes : 0;

  return (
    <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.line }]}>
      <View style={styles.header}>
        <Text style={[styles.eyebrow, { color: theme.dim }]}>{t('home.stats.title')}</Text>
        <View style={[styles.status, { borderColor: theme.line }]}>
          <View style={styles.dotWrap}>
            {connected ? (
              <Animated.View
                pointerEvents="none"
                style={[styles.pulse, { backgroundColor: theme.text }, pulseStyle]}
              />
            ) : null}
            <View
              style={[
                styles.dot,
                { backgroundColor: connected ? theme.text : theme.dim },
              ]}
            />
          </View>
          <Text style={[styles.statusText, { color: connected ? theme.text : theme.dim }]}>
            {statusText}
          </Text>
        </View>
      </View>

      <View style={styles.timeRow}>
        <Text
          numberOfLines={1}
          adjustsFontSizeToFit
          style={[styles.time, { color: connected ? theme.text : theme.dim }]}>
          {timeText}
        </Text>
        <Text style={[styles.timeLabel, { color: theme.dim }]}>{t('home.stats.time')}</Text>
      </View>

      <View style={[styles.divider, { backgroundColor: theme.line }]} />

      <View style={styles.ipRow}>
        <Text style={[styles.label, { color: theme.dim }]}>{t('home.stats.ip')}</Text>
        <Text
          selectable
          numberOfLines={1}
          style={[styles.ip, { color: connected ? theme.text : theme.muted }]}>
          {ipText}
        </Text>
      </View>

      <View style={styles.trafficHeader}>
        <Text style={[styles.label, { color: theme.dim }]}>{t('home.stats.traffic')}</Text>
        <Text style={[styles.total, { color: theme.muted }]}>
          {formatBytes(totalBytes, language)}
        </Text>
      </View>

      <View
        accessibilityLabel={`${t('home.stats.download')} ${formatBytes(rxBytes, language)}, ${t('home.stats.upload')} ${formatBytes(txBytes, language)}`}
        style={[styles.track, { backgroundColor: theme.line }]}>
        {totalBytes > 0 ? (
          <View style={styles.bar}>
            <View style={{ width: `${downloadRatio * 100}%`, backgroundColor: theme.text }} />
            <View style={{ flex: 1, backgroundColor: theme.dim }} />
          </View>
        ) : null}
      </View>

      <View style={styles.legend}>
        <View style={styles.legendItem}>
          <Ionicons name="arrow-down" size={10} color={theme.text} />
          <Text style={[styles.legendText, { color: theme.text }]}>
            {formatBytes(rxBytes, language)}
          </Text>
        </View>
        <View style={styles.legendItem}>
          <Ionicons name="arrow-up" size={10} color={theme.dim} />
          <Text style={[styles.legendText, { color: theme.dim }]}>
            {formatBytes(txBytes, language)}
          </Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: space.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: 14,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 22,
  },
  eyebrow: {
    fontFamily: 'monospace',
    fontSize: 9,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
  },
  status: {
    height: 22,
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: 8,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  dotWrap: { width: 6, height: 6, alignItems: 'center', justifyContent: 'center' },
  dot: { width: 4, height: 4, borderRadius: 2 },
  pulse: { position: 'absolute', width: 6, height: 6, borderRadius: 3 },
  statusText: {
    fontFamily: 'monospace',
    fontSize: 8,
    letterSpacing: 0.8,
  },
  timeRow: {
    flexDirection: 'row',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: 12,
    marginTop: 6,
  },
  time: {
    fontFamily: 'monospace',
    fontSize: 34,
    lineHeight: 40,
    fontWeight: '500',
    letterSpacing: -1.8,
    fontVariant: ['tabular-nums'],
  },
  timeLabel: {
    fontFamily: 'monospace',
    fontSize: 9,
    letterSpacing: 0.8,
    textTransform: 'uppercase',
  },
  divider: { height: StyleSheet.hairlineWidth, marginTop: 8, marginBottom: 10 },
  ipRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  label: {
    fontFamily: 'monospace',
    fontSize: 9,
    letterSpacing: 1.1,
    textTransform: 'uppercase',
  },
  ip: {
    fontFamily: 'monospace',
    fontSize: 13,
    letterSpacing: -0.2,
    fontVariant: ['tabular-nums'],
  },
  trafficHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 11,
  },
  total: {
    fontFamily: 'monospace',
    fontSize: 11,
    fontVariant: ['tabular-nums'],
  },
  track: {
    height: 4,
    borderRadius: 2,
    marginTop: 7,
    overflow: 'hidden',
  },
  bar: { flex: 1, flexDirection: 'row' },
  legend: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 7,
  },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  legendText: {
    fontFamily: 'monospace',
    fontSize: 10,
    fontVariant: ['tabular-nums'],
  },
});
