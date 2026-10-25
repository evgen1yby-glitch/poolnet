import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useMemo } from 'react';

import { AppBar, Card, Eyebrow, Lead, Pill, PrimaryButton, ProfileButton, Screen, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { daysLeft, formatDate } from '@/lib/format';
import { useAppStore } from '@/store/app';
import { radius, useTheme } from '@/theme';

export default function HomeScreen() {
  const theme = useTheme();
  const router = useRouter();
  const subscription = useAppStore((state) => state.subscription);
  const country = useAppStore((state) => state.country);
  const status = useQuery({ queryKey: ['status'], queryFn: api.status });

  const vpnCountries = status.data?.vpn.by_country.length ?? 0;
  const selectedName = country ? country.name : 'Авто';
  const selectedNodes = country?.nodes;
  const left = subscription ? daysLeft(subscription.expiresAt) : 0;
  const hasKey = Boolean(subscription);
  const subtitle = useMemo(() => {
    if (status.isLoading) return 'Обновляем данные пула…';
    if (!hasKey) return 'Получите бесплатный ключ и добавьте его в VPN-клиент.';
    return 'Ключ готов. Импортируйте ссылку в Happ, Hiddify, v2rayNG или Clash.';
  }, [hasKey, status.isLoading]);

  return (
    <>
      <AppBar right={<ProfileButton />} />
      <Screen>
        <View style={styles.statusLine}>
          <Eyebrow>СОСТОЯНИЕ</Eyebrow>
          <Pill tone={hasKey ? 'success' : 'neutral'}>{hasKey ? 'КЛЮЧ АКТИВЕН' : 'КЛЮЧА НЕТ'}</Pill>
        </View>

        <View style={styles.orbStage}>
          {hasKey ? <View style={[styles.halo, { borderColor: theme.accent, opacity: 0.22 }]} /> : null}
          <View style={[styles.ring, { borderColor: theme.line }]} />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={hasKey ? 'Открыть ключ' : 'Получить ключ'}
            onPress={() => router.push('/(tabs)/key')}
            style={({ pressed }) => [
              styles.orb,
              {
                backgroundColor: theme.dark ? '#111018' : theme.surface,
                borderColor: hasKey ? 'rgba(139,92,255,.34)' : theme.lineStrong,
                transform: [{ scale: pressed ? 0.975 : 1 }],
              },
            ]}>
            <Ionicons name={hasKey ? 'shield-checkmark-outline' : 'lock-closed-outline'} size={42} color={hasKey ? theme.success : theme.muted} />
            <Text style={[styles.orbLabel, { color: hasKey ? theme.success : theme.dim }]}>{hasKey ? 'КЛЮЧ ГОТОВ' : 'НЕТ КЛЮЧА'}</Text>
            <Text style={[styles.orbHint, { color: theme.dim }]}>{hasKey ? 'нажмите, чтобы открыть' : 'нажмите, чтобы получить'}</Text>
          </Pressable>
        </View>

        <View style={styles.heading}>
          <Title>{hasKey ? 'Ключ готов' : 'Начните с ключа'}</Title>
          <Lead>{subtitle}</Lead>
        </View>

        <Pressable
          onPress={() => router.push('/(tabs)/key')}
          style={[styles.serverRow, { backgroundColor: theme.surface, borderColor: theme.line }]}>
          <View style={[styles.cc, { backgroundColor: theme.surface2, borderColor: theme.line }]}>
            <Text style={[styles.ccText, { color: theme.text }]}>{country?.cc ?? 'AUTO'}</Text>
          </View>
          <View style={styles.serverMeta}>
            <Text style={[styles.serverName, { color: theme.text }]}>{selectedName}</Text>
            <Text style={[styles.serverSub, { color: theme.dim }]}>
              {selectedNodes ? `${selectedNodes} узлов · выбор страны` : `${vpnCountries} стран · авто-выбор`}
            </Text>
          </View>
          <Ionicons name="chevron-forward" size={18} color={theme.dim} />
        </Pressable>

        {hasKey && subscription ? (
          <Card style={styles.keyCard}>
            <View style={styles.rowBetween}>
              <Text style={[styles.keyTitle, { color: theme.text }]}>Бесплатный ключ</Text>
              <Pill tone="success">{left} дн.</Pill>
            </View>
            <Text style={[styles.keyMeta, { color: theme.dim }]}>до {formatDate(subscription.expiresAt)} · один ключ на IP в 24 часа</Text>
            <PrimaryButton label="Открыть ключ и ссылку" onPress={() => router.push('/(tabs)/key')} icon="key-outline" />
          </Card>
        ) : (
          <PrimaryButton label="Получить бесплатный ключ" onPress={() => router.push('/(tabs)/key')} />
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

        <Pressable
          onPress={() => router.push('/(tabs)/servers')}
          style={[styles.linkRow, { borderColor: theme.line }]}>
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
  serverRow: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
  },
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
