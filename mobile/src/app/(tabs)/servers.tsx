import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { AppBar, Card, Chip, Empty, ErrorState, Eyebrow, Lead, Pill, ProfileButton, Screen, SearchField, Title } from '@/components/ui';
import { api } from '@/lib/api';
import { countryName } from '@/lib/format';
import { useAppStore } from '@/store/app';
import { radius, useTheme } from '@/theme';

export default function ServersScreen() {
  const theme = useTheme();
  const country = useAppStore((state) => state.country);
  const setCountry = useAppStore((state) => state.setCountry);
  const status = useQuery({ queryKey: ['status'], queryFn: api.status });
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<'all' | 'large' | 'favorites'>('all');
  const [favorites, setFavorites] = useState<Set<string>>(new Set());

  const countries = useMemo(() => {
    const rows = (status.data?.vpn.by_country ?? [])
      .filter((row) => row.name && row.name !== 'unknown')
      .map((row) => ({ cc: row.name.toUpperCase(), name: countryName(row.name), nodes: row.n }))
      .sort((a, b) => b.nodes - a.nodes);
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (needle && !`${row.cc} ${row.name}`.toLowerCase().includes(needle)) return false;
      if (filter === 'favorites') return favorites.has(row.cc);
      if (filter === 'large') return row.nodes >= 10;
      return true;
    });
  }, [favorites, filter, query, status.data?.vpn.by_country]);

  const select = (value: { cc: string; name: string; nodes: number }) => {
    void setCountry(value);
  };

  return (
    <>
      <AppBar right={<ProfileButton />} />
      <Screen>
        <View style={styles.topline}>
          <Eyebrow>ВЫБОР СТРАНЫ</Eyebrow>
          <Pill>{countries.length} доступно</Pill>
        </View>
        <Title>Серверы</Title>
        <Lead>Страны из текущей проверенной выдачи. Выбор сохраняется: ключ можно импортировать отдельным срезом страны.</Lead>

        <SearchField value={query} onChangeText={setQuery} placeholder="Страна или код" />
        <View style={styles.chips}>
          <Chip label="Все" active={filter === 'all'} onPress={() => setFilter('all')} />
          <Chip label="Крупные" active={filter === 'large'} onPress={() => setFilter('large')} />
          <Chip label="Избранное" active={filter === 'favorites'} onPress={() => setFilter('favorites')} />
        </View>

        {status.isError ? <ErrorState text="Не удалось получить список стран." onRetry={() => status.refetch()} /> : null}
        {!status.isLoading && !status.isError && countries.length === 0 ? (
          <Empty text="Нет стран по этому фильтру. Сбросьте поиск или избранное." />
        ) : null}

        <View style={styles.list}>
          {countries.map((row) => {
            const selected = country?.cc === row.cc;
            const favorite = favorites.has(row.cc);
            return (
              <Pressable
                key={row.cc}
                accessibilityRole="button"
                accessibilityLabel={`${row.name}, ${row.nodes} узлов`}
                accessibilityState={{ selected }}
                onPress={() => select(row)}
                style={({ pressed }) => [
                  styles.row,
                  {
                    backgroundColor: selected ? theme.accentSoft : theme.surface,
                    borderColor: selected ? 'rgba(139,92,255,.42)' : theme.line,
                    opacity: pressed ? 0.72 : 1,
                  },
                ]}>
                <View style={[styles.cc, { backgroundColor: theme.surface2, borderColor: theme.line }]}>
                  <Text style={[styles.ccText, { color: theme.text }]}>{row.cc}</Text>
                </View>
                <View style={styles.rowMain}>
                  <Text style={[styles.name, { color: theme.text }]}>{row.name}</Text>
                  <Text style={[styles.meta, { color: theme.dim }]}>{row.nodes} узлов в выдаче</Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel={favorite ? 'Убрать из избранного' : 'В избранное'}
                  hitSlop={10}
                  onPress={() => {
                    setFavorites((current) => {
                      const next = new Set(current);
                      if (next.has(row.cc)) next.delete(row.cc);
                      else next.add(row.cc);
                      return next;
                    });
                  }}>
                  <Ionicons name={favorite ? 'star' : 'star-outline'} size={17} color={favorite ? theme.warning : theme.dim} />
                </Pressable>
                {selected ? <Ionicons name="checkmark-circle" size={19} color={theme.accent} /> : null}
              </Pressable>
            );
          })}
        </View>

        <Card style={styles.note}>
          <Text style={[styles.noteTitle, { color: theme.text }]}>Почему без «пинга»?</Text>
          <Text style={[styles.noteText, { color: theme.dim }]}>
            Задержка зависит от вашей сети и меняется между проверками. Мы не показываем выдуманные
            миллисекунды: актуальные метрики доступны в каталоге прокси и на сайте.
          </Text>
        </Card>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  topline: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginTop: 4, marginBottom: 10 },
  chips: { flexDirection: 'row', gap: 7, marginTop: 12, marginBottom: 14 },
  list: { gap: 8 },
  row: {
    minHeight: 62,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    padding: 10,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 11,
  },
  cc: { width: 40, height: 40, borderRadius: 11, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center' },
  ccText: { fontFamily: 'monospace', fontSize: 10, fontWeight: '600' },
  rowMain: { flex: 1, gap: 2 },
  name: { fontSize: 13.5, fontWeight: '600', letterSpacing: -0.15 },
  meta: { fontSize: 10.5 },
  note: { marginTop: 16, gap: 5 },
  noteTitle: { fontSize: 12, fontWeight: '600' },
  noteText: { fontSize: 10.5, lineHeight: 16 },
});
