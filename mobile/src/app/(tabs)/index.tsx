import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { ConnectOrb, type ConnectOrbPhase } from '@/components/connect-orb';
import { Flag } from '@/components/flag';

import { AppBar, Eyebrow, Lead, Pill, ProfileButton, Screen, Title } from '@/components/ui';
import { countryName } from '@/lib/format';
import { useT } from '@/lib/use-t';
import { useAppStore } from '@/store/app';
import { radius, useTheme } from '@/theme';

export default function HomeScreen() {
  const theme = useTheme();
  const t = useT();
  const router = useRouter();
  const country = useAppStore((state) => state.country);
  const language = useAppStore((state) => state.language);
  const connection = useAppStore((state) => state.connection);
  const connectionError = useAppStore((state) => state.connectionError);
  const connect = useAppStore((state) => state.connect);
  const disconnect = useAppStore((state) => state.disconnect);

  const connected = connection === 'connected';
  const reconnecting = connection === 'reconnecting';
  const connecting = connection === 'connecting';
  const busy = connecting || reconnecting;
  const failed = connection === 'error';
  const orbPhase: ConnectOrbPhase = connected
    ? 'connected'
    : reconnecting
      ? 'reconnecting'
      : connecting
        ? 'connecting'
        : failed
          ? 'error'
          : 'idle';
  const selectedName = country ? countryName(country.cc, language) : t('home.country.auto');

  const title = connected
    ? t('home.title.protected')
    : reconnecting
      ? t('home.title.switching')
      : connecting
        ? t('home.title.connecting')
        : failed
          ? t('home.title.error')
          : t('home.title.ready');

  const subtitle = connected
    ? t('home.sub.protected', { country: selectedName })
    : reconnecting
      ? t('home.sub.switching')
      : connecting
        ? t('home.sub.connecting')
        : failed
          ? connectionError || t('home.sub.failed')
          : t('home.sub.ready');

  const orbLabel = connected
    ? t('home.orb.protected')
    : reconnecting
      ? t('home.orb.switching')
      : connecting
        ? t('home.orb.connecting')
        : failed
          ? t('home.orb.retry')
          : t('home.orb.connect');

  const orbHint = connected
    ? t('home.hint.disconnect')
    : busy
      ? t('home.hint.wait')
      : failed
        ? t('home.hint.retry')
        : t('home.hint.connect');

  const statusLabel = connected
    ? t('status.protected')
    : reconnecting
      ? t('status.switching')
      : connecting
        ? t('status.connecting')
        : failed
          ? t('status.error')
          : t('status.disconnected');

  const onOrb = () => {
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
    if (connected) {
      void disconnect();
      return;
    }
    if (!busy) void connect().catch(() => undefined);
  };

  return (
    <>
      <AppBar right={<ProfileButton />} />
      <Screen>
        <View style={styles.statusLine}>
          <Eyebrow>{t('home.kicker')}</Eyebrow>
          <Pill tone={connected ? 'success' : failed ? 'warning' : 'neutral'}>{statusLabel}</Pill>
        </View>

        <ConnectOrb
          phase={orbPhase}
          label={orbLabel}
          hint={orbHint}
          onPress={onOrb}
          disabled={busy}
        />

        <View style={styles.heading}>
          <Title>{title}</Title>
          <Lead>{subtitle}</Lead>
        </View>

        <Pressable
          onPress={() => router.push('/servers')}
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

      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  statusLine: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 },
  heading: { gap: 0, marginTop: 8, marginBottom: 16 },
  serverRow: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.lg, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 11 },
  cc: { width: 40, height: 40, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  serverMeta: { flex: 1, gap: 2 },
  serverName: { fontSize: 14, fontWeight: '600', letterSpacing: -0.2 },
  serverSub: { fontSize: 11 },
});
