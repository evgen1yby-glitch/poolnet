import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { useMemo, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { Flag } from '@/components/flag';

import { AppBar, CloseButton, Empty, ErrorState, Eyebrow, Lead, Screen, SearchField } from '@/components/ui';
import { api } from '@/lib/api';
import { countryName } from '@/lib/format';
import { useT } from '@/lib/use-t';
import { useAppStore } from '@/store/app';
import { radius, useTheme } from '@/theme';

export default function ServersScreen() {
  const theme = useTheme();
  const t = useT();
  const router = useRouter();
  const language = useAppStore((state) => state.language);
  const country = useAppStore((state) => state.country);
  const setCountry = useAppStore((state) => state.setCountry);
  const status = useQuery({ queryKey: ['status'], queryFn: api.status });
  const [query, setQuery] = useState('');

  const countries = useMemo(() => {
    const rows = (status.data?.vpn.by_country ?? [])
      .filter((row) => row.name && row.name !== 'unknown')
      .map((row) => ({
        cc: row.name.toUpperCase(),
        name: countryName(row.name, 'ru'),
        label: countryName(row.name, language),
      }))
      .sort((a, b) => a.label.localeCompare(b.label, language));
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => !needle || `${row.cc} ${row.name} ${row.label}`.toLowerCase().includes(needle));
  }, [language, query, status.data?.vpn.by_country]);

  const select = (value: { cc: string; name: string; label: string } | null) => {
    void setCountry(value ? { cc: value.cc, name: value.name, nodes: 0 } : null).then(() => router.back());
  };

  return (
    <>
      <AppBar right={<CloseButton />} />
      <Screen>
        <Eyebrow>{t('servers.eyebrow')}</Eyebrow>
        <Text style={[styles.title, { color: theme.text }]}>{t('servers.title')}</Text>
        <Lead>{t('servers.lead')}</Lead>
        <SearchField value={query} onChangeText={setQuery} placeholder={t('servers.search')} />
        {status.isError ? <ErrorState text={t('servers.error')} onRetry={() => status.refetch()} /> : null}
        {status.isLoading ? <ActivityIndicator color={theme.text} style={{ marginTop: 24 }} /> : null}
        <View style={styles.list}>
          {!query ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={t('servers.auto')}
              onPress={() => select(null)}
              style={[styles.row, { borderColor: !country ? theme.lineStrong : theme.line, backgroundColor: !country ? theme.accentSoft : 'transparent' }]}>
              <View style={[styles.flagBox, { backgroundColor: theme.surface2, borderColor: theme.line }]}>
                <Ionicons name="globe-outline" size={21} color={theme.text} />
              </View>
              <View style={styles.main}>
                <Text style={[styles.name, { color: theme.text }]}>{t('servers.auto')}</Text>
                <Text style={[styles.sub, { color: theme.dim }]}>{t('servers.autoSub')}</Text>
              </View>
              {!country ? <Ionicons name="checkmark-circle" size={20} color={theme.text} /> : null}
            </Pressable>
          ) : null}
          {countries.map((row) => {
            const selected = country?.cc === row.cc;
            return (
              <Pressable
                key={row.cc}
                accessibilityRole="button"
                accessibilityLabel={row.label}
                accessibilityState={{ selected }}
                onPress={() => select(row)}
                style={({ pressed }) => [styles.row, { borderColor: selected ? theme.lineStrong : theme.line, backgroundColor: selected ? theme.accentSoft : 'transparent', opacity: pressed ? 0.65 : 1 }]}>
                <View style={[styles.flagBox, { backgroundColor: theme.surface2, borderColor: theme.line }]}>
                  <Flag code={row.cc} size={22} />
                </View>
                <View style={styles.main}>
                  <Text style={[styles.name, { color: theme.text }]}>{row.label}</Text>
                </View>
                {selected ? <Ionicons name="checkmark-circle" size={20} color={theme.text} /> : null}
              </Pressable>
            );
          })}
        </View>
        {!status.isLoading && !status.isError && countries.length === 0 ? <Empty text={t('servers.empty')} /> : null}
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 30, lineHeight: 32, letterSpacing: -1.2, fontWeight: '700', marginTop: 12 },
  list: { gap: 6, marginTop: 14 },
  row: { minHeight: 64, borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.md, padding: 10, flexDirection: 'row', alignItems: 'center', gap: 11 },
  flagBox: { width: 42, height: 42, borderRadius: 11, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' },
  main: { flex: 1, gap: 2 },
  name: { fontSize: 15, fontWeight: '600', letterSpacing: -0.2 },
  sub: { fontSize: 10.5 },
});
