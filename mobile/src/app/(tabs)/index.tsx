import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AppBar, Card, Eyebrow, Lead, Pill, PrimaryButton, ProfileButton, Screen, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { daysLeft, formatDate } from '@/lib/format';
import { tunnelSupported } from '@/lib/tunnel';
import { useAppStore } from '@/store/app';
import { radius, useTheme } from '@/theme';

export default function HomeScreen() {
  const theme = useTheme();
  const router = useRouter();
  const subscription = useAppStore((state) => state.subscription);
  const country = useAppStore((state) => state.country);
  const connection = useAppStore((state) => state.connection);
  const connectionError = useAppStore((state) => state.connectionError);
  const connect = useAppStore((state) => state.connect);
  const disconnect = useAppStore((state) => state.disconnect);
  const status = useQuery({ queryKey: ['status'], queryFn: api.status });

  const hasKey = Boolean(subscription);
  const connected = connection === 'connected';
  const connecting = connection === 'connecting';
  const failed = connection === 'error';
  const vpnCountries = status.data?.vpn.by_country.length ?? 0;
  const selectedName = country ? country.name : 'Авто';
  const selectedNodes = country?.nodes;
  const left = subscription ? daysLeft(subscription.expiresAt) : 0;

  const title = connected
    ? 'Соединение защищено'
    : connecting
      ? 'Подключаемся…'
      : failed
        ? 'Не удалось подключиться'
        : hasKey
          ? tunnelSupported
            ? 'Готово к подключению'
            : 'Ключ готов'
          : 'Начните с ключа';

  const subtitle = connected
    ? `Весь трафик идёт через узел ${selectedName}`
    : connecting
      ? 'Поднимаем защищённый туннель…'
      : failed
        ? connectionError || 'Проверьте соединение и попробуйте ещё раз.'
        : hasKey
          ? tunnelSupported
            ? 'Нажмите на круг, чтобы включить VPN. Узлы сторонние — не для чувствительных данных.'
            : 'Скопируйте ссылку и импортируйте её в Happ, Hiddify, v2rayNG или Clash.'
          : 'Получите бесплатный ключ на 7 дней и подключитесь в одно нажатие.';

  const orbLabel = connected
    ? 'ЗАЩИЩЕНО'
    : connecting
      ? 'ПОДКЛЮЧЕНИЕ'
      : failed
        ? 'ПОВТОРИТЬ'
        : hasKey
          ? tunnelSupported
            ? 'ПОДКЛЮЧИТЬ'
            : 'ОТКРЫТЬ КЛЮЧ'
          : 'НЕТ КЛЮЧА';
  const orbHint = connected
    ? 'нажмите, чтобы отключить'
    : connecting
      ? 'пожалуйста, подождите'
      : failed
        ? 'нажмите, чтобы попробовать снова'
        : hasKey
          ? tunnelSupported
            ? 'нажмите, чтобы включить'
            : 'ключ внутри приложения'
          : 'нажмите, чтобы получить';

  const onOrb = () => {
    if (!hasKey) {
      router.push('/key');
      return;
    }
    if (!tunnelSupported) {
      router.push('/key');
      return;
    }
    if (connected) {
      void disconnect();
      return;
    }
    if (!connecting) void connect().catch(() => undefined);
  };

  return (
    <>
      <AppBar right={<ProfileButton />} />
      <Screen>
        <View style={styles.statusLine}>
          <Eyebrow>СОСТОЯНИЕ</Eyebrow>
          <Pill tone={connected ? 'success' : failed ? 'warning' : 'neutral'}>
            {connected ? 'ЗАЩИЩЕНО' : connecting ? 'ПОДКЛЮЧЕНИЕ' : failed ? 'ОШИБКА' : hasKey ? 'КЛЮЧ АКТИВЕН' : 'КЛЮЧА НЕТ'}
          </Pill>
        </View>

        <View style={styles.orbStage}>
          {(connected || connecting) && <View style={[styles.halo, { borderColor: connected ? theme.success : theme.accent, opacity: 0.22 }]} />}
          <View style={[styles.ring, { borderColor: theme.line }]} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={connected ? 'Отключить VPN' : 'Подключить VPN'}
            accessibilityState={{ busy: connecting }}
            disabled={connecting}
            onPress={onOrb}
            style={({ pressed }) => [
              styles.orb,
              {
                backgroundColor: theme.dark ? '#111018' : theme.surface,
                borderColor: connected ? 'rgba(74,222,128,.4)' : hasKey ? 'rgba(139,92,255,.34)' : theme.lineStrong,
                transform: [{ scale: pressed ? 0.975 : 1 }],
              },
            ]}>
            <Ionicons
              name={connected ? 'shield-checkmark' : connecting ? 'sync' : failed ? 'alert-circle-outline' : hasKey ? 'power' : 'lock-closed-outline'}
              size={42}
              color={connected ? theme.success : failed ? theme.warning : hasKey ? theme.accent : theme.muted}
            />
            <Text style={[styles.orbLabel, { color: connected ? theme.success : failed ? theme.warning : hasKey ? theme.accent : theme.dim }]}>{orbLabel}</Text>
            <Text style={[styles.orbHint, { color: theme.dim }]}>{orbHint}</Text>
          </Pressable>
        </View>

        <View style={styles.heading}>
          <Title>{title}</Title>
          <Lead>{subtitle}</Lead>
        </View>

        <Pressable
          onPress={() => (hasKey ? router.push('/servers') : router.push('/key'))}
          style={[styles.serverRow, { backgroundColor: theme.surface, borderColor: theme.line }]}>
          <View style={[styles.cc, { backgroundColor: theme.surface2, borderColor: theme.line }]}>
            <Text style={[styles.ccText, { color: theme.text }]}>{country?.cc ?? 'AUTO'}</Text>
          </View>
          <View style={styles.serverMeta}>
            <Text style={[styles.serverName, { color: theme.text }]}>{selectedName}</Text>
            <Text style={[styles.serverSub, { color: theme.dim }]}>
              {selectedNodes ? `${selectedNodes} узлов · нажмите, чтобы сменить` : `${vpnCountries} стран · авто-выбор`}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.dim} />
        </Pressable>

        {hasKey && subscription ? (
          <Card style={styles.keyCard}>
            <View style={styles.rowBetween}>
              <Text style={[styles.keyTitle, { color: theme.text }]}>{connected ? 'VPN активно' : 'Бесплатный ключ'}</Text>
              <Pill tone="success">{left} дн.</Pill>
            </View>
            <Text style={[styles.keyMeta, { color: theme.dim }]}>
              до {formatDate(subscription.expiresAt)} · один ключ на IP в 24 часа
            </Text>
            <PrimaryButton
              label={connected ? 'Отключить VPN' : 'Открыть ключ и ссылку'}
              onPress={() => (connected ? void disconnect() : router.push('/key'))}
              tone={connected ? 'ghost' : 'accent'}
              icon={connected ? 'power-outline' : 'key-outline'}
            />
          </Card>
        ) : (
          <PrimaryButton label="Получить бесплатный ключ" onPress={() => router.push('/key')} />
        )}

        <View style={styles.statsRow}>
          <Card style={styles.stat}>
            <Text style={[styles.statLabel, { color: theme.dim }]}>ПРОКСИ</Text>
            <Text style={[styles.statValue, { color: theme.text }]}>{status.data?.pool.total ?? '—'}</Text>
            <Text style={[styles.statMeta, { color: theme.dim }]}>живых адресов</Text>
          </Card>
          <Card style={styles.stat}>
            <Text style={[styles.statLabel, { color: theme.dim }]}>VPN</Text>
            <Text style={[styles.statValue, { color: theme.text }]}>{status.data?.vpn.verified ?? '—'}</Text>
            <Text style={[styles.statMeta, { color: theme.dim }]}>узлов в выдаче</Text>
          </Card>
        </View>

        <Pressable onPress={() => router.push('/servers')} style={[styles.linkRow, { borderColor: theme.line }]}>
          <Ionicons name="globe-outline" size={17} color={theme.accent} />
          <Text style={[styles.linkText, { color: theme.muted }]}>Посмотреть серверы и страны</Text>
          <Ionicons name="chevron-forward" size={16} color={theme.dim} />
        </Pressable>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  statusLine: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 },
  orbStage: { height: 300, alignItems: 'center', justifyContent: 'center' },
  ring: { position: 'absolute', width: 280, height: 280, borderRadius: 140, borderWidth: StyleSheet.hairlineWidth },
  halo: { position: 'absolute', width: 252, height: 252, borderRadius: 126, borderWidth: 1 },
  orb: {
    width: 214,
    height: 214,
    borderRadius: 107,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 10,
    shadowColor: '#8B5CFF',
    shadowOpacity: 0.24,
    shadowRadius: 50,
    shadowOffset: { width: 0, height: 0 },
  },
  orbLabel: { fontFamily: 'monospace', fontSize: 10, letterSpacing: 1.2, fontWeight: '600' },
  orbHint: { fontFamily: 'monospace', fontSize: 8.5, letterSpacing: 0.2 },
  heading: { gap: 0, marginTop: -4, marginBottom: 16 },
  serverRow: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.lg, padding: 12, flexDirection: 'row', alignItems: 'center', gap: 11 },
  cc: { width: 40, height: 40, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center' },
  ccText: { fontFamily: 'monospace', fontSize: 10, fontWeight: '600', letterSpacing: 0.4 },
  serverMeta: { flex: 1, gap: 2 },
  serverName: { fontSize: 14, fontWeight: '600', letterSpacing: -0.2 },
  serverSub: { fontSize: 11 },
  keyCard: { marginTop: 10, gap: 10 },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  keyTitle: { fontSize: 13, fontWeight: '600' },
  keyMeta: { fontSize: 10.5, lineHeight: 15 },
  statsRow: { flexDirection: 'row', gap: 8, marginTop: 10 },
  stat: { flex: 1, padding: 13 },
  statLabel: { fontFamily: 'monospace', fontSize: 8.5, letterSpacing: 1 },
  statValue: { fontSize: 22, fontWeight: '700', letterSpacing: -0.9, marginTop: 4 },
  statMeta: { fontSize: 9.5, marginTop: 1 },
  linkRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, marginTop: 6 },
  linkText: { flex: 1, fontSize: 12 },
});
