import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/theme';

type TabBarProps = {
  state: { index: number; routes: { key: string; name: string }[] };
  emitter: {
    emit: (event: { type: 'tabPress'; target: string; canPreventDefault: true }) => { defaultPrevented: boolean };
  };
  navigateToTab: (routeKey: string) => void;
};

const ITEMS: { name: string; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { name: 'index', label: 'Главная', icon: 'power-outline' },
  { name: 'servers', label: 'Серверы', icon: 'globe-outline' },
  { name: 'proxy', label: 'Прокси', icon: 'git-network-outline' },
  { name: 'key', label: 'Ключ', icon: 'key-outline' },
  { name: 'profile', label: 'Профиль', icon: 'person-outline' },
];

export function TabBar({ state, emitter, navigateToTab }: TabBarProps) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[
        styles.wrap,
        {
          bottom: Math.max(insets.bottom, 10),
          backgroundColor: theme.dark ? 'rgba(14,14,20,.94)' : 'rgba(255,255,255,.94)',
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
            accessibilityLabel={item.label}
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
            <Text style={[styles.label, { color: active ? theme.text : theme.dim }]}>{item.label}</Text>
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
