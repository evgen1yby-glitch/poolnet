import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import { useEffect, useState } from 'react';
import { Animated, Easing, Pressable, StyleSheet, Text, View } from 'react-native';
import { Flag } from '@/components/flag';

import { AppBar, Card, Eyebrow, Lead, Pill, PrimaryButton, ProfileButton, Screen, Title } from '@/components/ui';
import { countryName, daysLeft, formatDate } from '@/lib/format';
import { tunnelSupported } from '@/lib/tunnel';
import { useT } from '@/lib/use-t';
import { useAppStore } from '@/store/app';
import { radius, useTheme } from '@/theme';

export default function HomeScreen() {
  const theme = useTheme();
  const t = useT();
  const router = useRouter();
  const subscription = useAppStore((state) => state.subscription);
  const country = useAppStore((state) => state.country);
  const language = useAppStore((state) => state.language);
  const connection = useAppStore((state) => state.connection);
  const connectionError = useAppStore((state) => state.connectionError);
  const connect = useAppStore((state) => state.connect);
  const disconnect = useAppStore((state) => state.disconnect);
  const [pulse] = useState(() => new Animated.Value(0));
  const [spin] = useState(() => new Animated.Value(0));

  const hasKey = Boolean(subscription);
  const connected = connection === 'connected';
  const reconnecting = connection === 'reconnecting';
  const connecting = connection === 'connecting';
  const busy = connecting || reconnecting;
  const failed = connection === 'error';
  const active = connected || busy;
  const selectedName = country ? countryName(country.cc, language) : t('home.country.auto');
  const left = subscription ? daysLeft(subscription.expiresAt) : 0;

  useEffect(() => {
    if (!active) {
      pulse.setValue(0);
      spin.setValue(0);
      return;
    }
    const pulseLoop = Animated.loop(
      Animated.timing(pulse, {
        toValue: 1,
        duration: 2600,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }),
    );
    const spinLoop = Animated.loop(
      Animated.timing(spin, { toValue: 1, duration: 22000, easing: Easing.linear, useNativeDriver: true }),
    );
    pulseLoop.start();
    spinLoop.start();
    return () => {
      pulseLoop.stop();
      spinLoop.stop();
    };
  }, [active, pulse, spin]);

  const title = connected
    ? t('home.title.protected')
    : reconnecting
      ? t('home.title.switching')
      : connecting
        ? t('home.title.connecting')
        : failed
          ? t('home.title.error')
          : hasKey
            ? tunnelSupported
              ? t('home.title.ready')
              : t('home.title.keyReady')
            : t('home.title.start');

  const subtitle = connected
    ? t('home.sub.protected', { country: selectedName })
    : reconnecting
      ? t('home.sub.switching')
      : connecting
        ? t('home.sub.connecting')
        : failed
          ? connectionError || t('home.sub.failed')
          : hasKey
            ? tunnelSupported
              ? t('home.sub.ready')
              : t('home.sub.external')
            : t('home.sub.start');

  const orbLabel = connected
    ? t('home.orb.protected')
    : reconnecting
      ? t('home.orb.switching')
      : connecting
        ? t('home.orb.connecting')
        : failed
          ? t('home.orb.retry')
          : hasKey
            ? tunnelSupported
              ? t('home.orb.connect')
              : t('home.orb.open')
            : t('home.orb.none');

  const orbHint = connected
    ? t('home.hint.disconnect')
    : busy
      ? t('home.hint.wait')
      : failed
        ? t('home.hint.retry')
        : hasKey
          ? tunnelSupported
            ? t('home.hint.connect')
            : t('home.hint.key')
          : t('home.hint.get');

  const statusLabel = connected
    ? t('status.protected')
    : reconnecting
      ? t('status.switching')
      : connecting
        ? t('status.connecting')
        : failed
          ? t('status.error')
          : hasKey
            ? t('status.active')
            : t('status.none');

  const onOrb = () => {
    if (!hasKey || !tunnelSupported) {
      router.push('/key');
      return;
    }
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
    if (connected) {
      void disconnect();
      return;
    }
    if (!busy) void connect().catch(() => undefined);
  };

  const haloScale = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.9, 1.16] });
  const haloOpacity = pulse.interpolate({ inputRange: [0, 1], outputRange: [0.24, 0] });
  const orbitRotate = spin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });

  return (
    <>
      <AppBar right={<ProfileButton />} />
      <Screen>
        <View style={styles.statusLine}>
          <Eyebrow>{t('home.kicker')}</Eyebrow>
          <Pill tone={connected ? 'success' : failed ? 'warning' : 'neutral'}>{statusLabel}</Pill>
        </View>

        <View style={styles.orbStage}>
          <Animated.View
            style={[
              styles.orbit,
              { borderColor: theme.line, opacity: active ? 0.9 : 0.5, transform: [{ rotate: orbitRotate }] },
            ]}>
          </Animated.View>
          {active ? (
            <Animated.View
              style={[
                styles.halo,
                { borderColor: theme.text, opacity: haloOpacity, transform: [{ scale: haloScale }] },
              ]}
            />
          ) : null}
          <View style={[styles.ring, { borderColor: theme.line }]} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={connected ? t('home.key.disconnect') : t('home.orb.connect')}
            accessibilityState={{ busy, selected: connected }}
            disabled={busy}
            onPress={onOrb}
            style={({ pressed }) => [
              styles.orb,
              {
                backgroundColor: theme.dark ? '#0E0E0E' : theme.surface,
                borderColor: connected ? theme.lineStrong : hasKey ? theme.lineStrong : theme.line,
                transform: [{ scale: pressed ? 0.975 : 1 }],
              },
            ]}>
            <View style={[styles.orbCore, { borderColor: theme.line, backgroundColor: theme.dark ? '#070707' : theme.bgAlt }]}>
              <Ionicons
                name={connected ? 'shield-checkmark' : busy ? 'sync' : failed ? 'alert-circle-outline' : hasKey ? 'power' : 'lock-closed-outline'}
                size={38}
                color={connected ? theme.text : failed ? theme.warning : hasKey ? theme.text : theme.muted}
              />
            </View>
            <Text style={[styles.orbLabel, { color: connected ? theme.text : hasKey ? theme.text : theme.dim }]}>{orbLabel}</Text>
            <Text style={[styles.orbHint, { color: theme.dim }]}>{orbHint}</Text>
          </Pressable>
        </View>

        <View style={styles.heading}>
          <Title>{title}</Title>
          <Lead>{subtitle}</Lead>
        </View>

        <Pressable
          onPress={() => (hasKey ? router.push('/servers') : router.push('/key'))}
          style={({ pressed }) => [styles.serverRow, { backgroundColor: theme.surface, borderColor: theme.line, opacity: pressed ? 0.7 : 1 }]}>
          <View style={[styles.cc, { backgroundColor: theme.surface2, borderColor: theme.line }]}>
            {country ? (
              <Flag code={country.cc} size={22} />
            ) : (
              <Ionicons name="globe-outline" size={20} color={theme.muted} />
            )}
          </View>
          <View style={styles.serverMeta}>
            <Text style={[styles.serverName, { color: theme.text }]}>{selectedName}</Text>
            <Text style={[styles.serverSub, { color: theme.dim }]}>{t('home.country.change')}</Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.dim} />
        </Pressable>

        {hasKey && subscription ? (
          <Card style={styles.keyCard}>
            <View style={styles.rowBetween}>
              <Text style={[styles.keyTitle, { color: theme.text }]}>{connected ? t('home.key.active') : t('home.key.free')}</Text>
              <Pill tone="success">{t('home.key.days', { days: left })}</Pill>
            </View>
            <Text style={[styles.keyMeta, { color: theme.dim }]}>
              {t('home.key.until', { date: formatDate(subscription.expiresAt, language) })}
            </Text>
            <PrimaryButton
              label={connected ? t('home.key.disconnect') : t('home.key.open')}
              onPress={() => (connected ? void disconnect() : router.push('/key'))}
              tone={connected ? 'ghost' : 'accent'}
              icon={connected ? 'power-outline' : 'key-outline'}
            />
          </Card>
        ) : (
          <PrimaryButton label={t('home.key.get')} onPress={() => router.push('/key')} />
        )}
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  statusLine: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 },
  orbStage: { height: 310, alignItems: 'center', justifyContent: 'center' },
  orbit: { position: 'absolute', width: 292, height: 292, borderRadius: 146, borderWidth: StyleSheet.hairlineWidth, borderStyle: 'dashed' },
  halo: { position: 'absolute', width: 264, height: 264, borderRadius: 132, borderWidth: 1 },
  ring: { position: 'absolute', width: 248, height: 248, borderRadius: 124, borderWidth: StyleSheet.hairlineWidth },
  orb: {
    width: 214,
    height: 214,
    borderRadius: 107,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    shadowColor: '#FFFFFF',
    shadowOpacity: 0.16,
    shadowRadius: 44,
    shadowOffset: { width: 0, height: 0 },
  },
  orbCore: { width: 72, height: 72, borderRadius: 36, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center', marginBottom: 2 },
  orbLabel: { fontFamily: 'monospace', fontSize: 9.5, letterSpacing: 1.3, fontWeight: '600' },
  orbHint: { fontFamily: 'monospace', fontSize: 8, letterSpacing: 0.1 },
  heading: { gap: 0, marginTop: -6, marginBottom: 16 },
  serverRow: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.lg, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 11 },
  cc: { width: 40, height: 40, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  serverMeta: { flex: 1, gap: 2 },
  serverName: { fontSize: 14, fontWeight: '600', letterSpacing: -0.2 },
  serverSub: { fontSize: 11 },
  keyCard: { marginTop: 10, gap: 10 },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  keyTitle: { fontSize: 13, fontWeight: '600' },
  keyMeta: { fontSize: 10.5, lineHeight: 15 },
});
