import { Ionicons } from '@expo/vector-icons';
import { useInfiniteQuery } from '@tanstack/react-query';
import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppBar, Empty, ErrorState, Eyebrow, ProfileButton, SearchField, Title } from '@/components/ui';
import { api, type ProxyRow } from '@/lib/api';
import { radius, useTheme } from '@/theme';

export default function ProxyScreen() {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const [rawQuery, setRawQuery] = useState('');
  const [query, setQuery] = useState('');
  const [proto, setProto] = useState<'all' | 'http' | 'socks5'>('all');
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(rawQuery.trim()), 300);
    return () => clearTimeout(timer);
  }, [rawQuery]);

  const list = useInfiniteQuery({
    queryKey: ['proxies', query, proto],
    initialPageParam: 1,
    queryFn: ({ pageParam }) =>
      api.proxies({ page: pageParam, per: 50, q: query || undefined, proto: proto === 'all' ? undefined : proto }),
    getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
  });

  const rows = useMemo(() => list.data?.pages.flatMap((page) => page.rows) ?? [], [list.data?.pages]);
  const first = list.data?.pages[0];
  const total = first?.total ?? 0;

  const copy = async (row: ProxyRow) => {
    await Clipboard.setStringAsync(row.address);
    await Haptics.selectionAsync().catch(() => undefined);
    setCopied(row.address);
    setTimeout(() => setCopied((value) => (value === row.address ? null : value)), 1400);
  };

  return (
    <View style={{ flex: 1, backgroundColor: theme.bg }}>
      <AppBar right={<ProfileButton />} />
      <View style={{ paddingHorizontal: 18 }}>
        <View style={styles.topline}>
          <Eyebrow>ПРОКСИ-БАЗА</Eyebrow>
          <View style={styles.live}>
            <View style={[styles.dot, { backgroundColor: theme.success }]} />
            <Text style={[styles.liveText, { color: theme.muted }]}>LIVE</Text>
          </View>
        </View>
        <Title>Прокси</Title>
        <View style={styles.countLine}>
          <Text style={[styles.count, { color: theme.text }]}>{total ? total.toLocaleString('ru-RU') : '—'}</Text>
          <Text style={[styles.countMeta, { color: theme.dim }]}>живых адресов</Text>
        </View>
        <View style={[styles.segment, { backgroundColor: theme.surface, borderColor: theme.line }]}>
          {(['all', 'http', 'socks5'] as const).map((value) => (
            <Pressable
              key={value}
              accessibilityRole="button"
              accessibilityState={{ selected: proto === value }}
              onPress={() => setProto(value)}
              style={[styles.segmentItem, proto === value && { backgroundColor: theme.surface2 }]}>
              <Text style={{ color: proto === value ? theme.text : theme.dim, fontSize: 11.5, fontWeight: '600' }}>
                {value === 'all' ? 'Все' : value.toUpperCase()}
              </Text>
            </Pressable>
          ))}
        </View>
        <SearchField value={rawQuery} onChangeText={setRawQuery} placeholder="Адрес, страна или протокол" />
      </View>

      {list.isError ? (
        <View style={{ paddingHorizontal: 18 }}>
          <ErrorState text="Каталог прокси не загрузился. Проверьте соединение." onRetry={() => list.refetch()} />
        </View>
      ) : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.address}
          contentContainerStyle={{ paddingHorizontal: 18, paddingTop: 4, paddingBottom: 112 + insets.bottom, gap: 8 }}
          showsVerticalScrollIndicator={false}
          onEndReachedThreshold={0.4}
          onEndReached={() => list.hasNextPage && !list.isFetchingNextPage ? list.fetchNextPage() : undefined}
          refreshControl={<RefreshControl refreshing={list.isRefetching && !list.isFetchingNextPage} onRefresh={() => { void list.refetch(); }} tintColor={theme.accent} />}
          ListEmptyComponent={
            list.isLoading ? (
              <View style={styles.loading}><ActivityIndicator color={theme.accent} /></View>
            ) : (
              <Empty text="Нет прокси по этому фильтру. Сбросьте поиск или протокол." />
            )
          }
          ListFooterComponent={
            list.isFetchingNextPage ? <ActivityIndicator color={theme.accent} style={{ paddingVertical: 16 }} /> : undefined
          }
          renderItem={({ item }) => (
            <View style={[styles.row, { backgroundColor: theme.surface, borderColor: theme.line }]}>
              <View style={[styles.cc, { backgroundColor: theme.surface2, borderColor: theme.line }]}>
                <Text style={[styles.ccText, { color: theme.text }]}>{item.country || '—'}</Text>
              </View>
              <View style={styles.rowMain}>
                <Text style={[styles.address, { color: theme.text }]} numberOfLines={1}>{item.address}</Text>
                <Text style={[styles.meta, { color: theme.dim }]}>
                  {item.protocol.toUpperCase()} · {item.latency_ms == null ? '—' : `${item.latency_ms} ms`} · {item.grade}
                </Text>
              </View>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Скопировать ${item.address}`}
                onPress={() => void copy(item)}
                style={({ pressed }) => [styles.copy, { backgroundColor: theme.surface2, opacity: pressed ? 0.6 : 1 }]}>
                <Ionicons name={copied === item.address ? 'checkmark' : 'copy-outline'} size={15} color={copied === item.address ? theme.success : theme.muted} />
              </Pressable>
            </View>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  topline: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4, marginBottom: 10 },
  live: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  dot: { width: 5, height: 5, borderRadius: 3 },
  liveText: { fontFamily: 'monospace', fontSize: 9, letterSpacing: 1 },
  countLine: { flexDirection: 'row', alignItems: 'baseline', gap: 7, marginTop: 3, marginBottom: 12 },
  count: { fontSize: 34, fontWeight: '700', letterSpacing: -1.7 },
  countMeta: { fontSize: 10.5 },
  segment: { flexDirection: 'row', padding: 3, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, marginBottom: 10 },
  segmentItem: { flex: 1, height: 30, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 10,
  },
  cc: { width: 38, height: 38, borderRadius: 10, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center' },
  ccText: { fontFamily: 'monospace', fontSize: 9, fontWeight: '600' },
  rowMain: { flex: 1, gap: 3, minWidth: 0 },
  address: { fontFamily: 'monospace', fontSize: 11.5, letterSpacing: -0.3 },
  meta: { fontSize: 9.5 },
  copy: { width: 32, height: 32, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  loading: { padding: 40, alignItems: 'center' },
});
