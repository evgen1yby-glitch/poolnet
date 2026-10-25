import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useT } from '@/lib/use-t';
import { useTheme } from '@/theme';

type TabBarProps = {
  state: { index: number; routes: { key: string; name: string }[] };
  emitter: {
    emit: (event: { type: 'tabPress'; target: string; canPreventDefault: true }) => { defaultPrevented: boolean };
  };
  navigateToTab: (routeKey: string) => void;
};

const ITEMS: { name: string; key: 'tabs.vpn' | 'tabs.proxy' | 'tabs.profile'; icon: keyof typeof Ionicons.glyphMap }[] = [
  { name: 'index', key: 'tabs.vpn', icon: 'power-outline' },
  { name: 'proxy', key: 'tabs.proxy', icon: 'git-network-outline' },
  { name: 'profile', key: 'tabs.profile', icon: 'person-outline' },
];

export function TabBar({ state, emitter, navigateToTab }: TabBarProps) {
  const theme = useTheme();
  const t = useT();
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[
        styles.wrap,
        {
          bottom: Math.max(insets.bottom, 10),
          backgroundColor: theme.dark ? 'rgba(8,8,8,.96)' : 'rgba(255,255,255,.96)',
          borderColor: theme.lineStrong,
        },
      ]}>
      {state.routes.map((route, index) => {
        const item = ITEMS.find((candidate) => candidate.name === route.name);
        if (!item) return null;
        const active = state.index === index;
        return (
          <Pressable
            key={route.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={t(item.key)}
            onPress={() => {
              const event = emitter.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
              if (!active && !event.defaultPrevented) navigateToTab(route.key);
            }}
            style={({ pressed }) => [
              styles.tab,
              active && { backgroundColor: theme.dark ? 'rgba(255,255,255,.055)' : theme.surface2 },
              pressed && { opacity: 0.65 },
            ]}>
            {active ? <View style={[styles.indicator, { backgroundColor: theme.accent }]} /> : null}
            <Ionicons name={item.icon} size={20} color={active ? theme.text : theme.dim} />
            <Text style={[styles.label, { color: active ? theme.text : theme.dim }]}>{t(item.key)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: 'absolute',
    left: 12,
    right: 12,
    height: 66,
    borderRadius: 22,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    padding: 6,
    shadowColor: '#000',
    shadowOpacity: 0.32,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 10 },
    elevation: 14,
  },
  tab: { flex: 1, borderRadius: 16, alignItems: 'center', justifyContent: 'center', gap: 3 },
  indicator: { position: 'absolute', top: 5, width: 22, height: 2, borderRadius: 2 },
  label: { fontSize: 9, fontWeight: '600' },
});
