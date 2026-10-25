import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
  type ViewStyle,
  type StyleProp,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { radius, useTheme } from '@/theme';

export function Screen({
  children,
  scroll = true,
  padded = true,
  style,
}: {
  children: ReactNode;
  scroll?: boolean;
  padded?: boolean;
  style?: ViewStyle;
}) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  const content = (
    <View
      style={[
        padded && { paddingHorizontal: 18 },
        { paddingTop: 8, paddingBottom: 132 + insets.bottom, gap: 0 },
        style,
      ]}>
      {children}
    </View>
  );
  if (!scroll) return <View style={{ flex: 1, backgroundColor: theme.bg }}>{content}</View>;
  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: theme.bg }}
      contentContainerStyle={{ flexGrow: 1 }}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}>
      {content}
    </ScrollView>
  );
}

export function AppBar({ right }: { right?: ReactNode }) {
  const theme = useTheme();
  const insets = useSafeAreaInsets();
  return (
    <View style={[styles.appbar, { height: 58 + insets.top, paddingTop: insets.top }]}>
      <View style={styles.brand}>
        <Ionicons name="shield-checkmark" size={24} color={theme.accent} />
        <Text style={[styles.brandName, { color: theme.text }]}>PoolNet</Text>
        <Text style={[styles.brandTag, { color: theme.dim }]}>MOBILE</Text>
      </View>
      {right}
    </View>
  );
}

export function CloseButton() {
  const theme = useTheme();
  const router = useRouter();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Закрыть"
      onPress={() => router.back()}
      style={({ pressed }) => [
        styles.iconButton,
        { backgroundColor: theme.surface, borderColor: theme.line, opacity: pressed ? 0.65 : 1 },
      ]}>
      <Ionicons name="close" size={20} color={theme.muted} />
    </Pressable>
  );
}

export function ProfileButton() {
  const theme = useTheme();
  const router = useRouter();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Профиль"
      onPress={() => router.push('/(tabs)/profile')}
      style={({ pressed }) => [
        styles.iconButton,
        { backgroundColor: theme.surface, borderColor: theme.line, opacity: pressed ? 0.65 : 1 },
      ]}>
      <Ionicons name="person-outline" size={18} color={theme.muted} />
    </Pressable>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <Text style={[styles.eyebrow, { color: theme.dim }]}>{children}</Text>;
}

export function Title({ children, size = 30 }: { children: ReactNode; size?: number }) {
  const theme = useTheme();
  return (
    <Text style={{ color: theme.text, fontSize: size, lineHeight: size * 1.02, fontWeight: '700', letterSpacing: -1.1 }}>
      {children}
    </Text>
  );
}

export function Lead({ children }: { children: ReactNode }) {
  const theme = useTheme();
  return <Text style={[styles.lead, { color: theme.muted }]}>{children}</Text>;
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const theme = useTheme();
  return (
    <View style={[styles.card, { backgroundColor: theme.surface, borderColor: theme.line }, style]}>
      {children}
    </View>
  );
}

export function Pill({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'success' | 'warning' }) {
  const theme = useTheme();
  const colors =
    tone === 'success'
      ? { bg: theme.successSoft, fg: theme.success, border: 'rgba(74,222,128,.25)' }
      : tone === 'warning'
        ? { bg: 'rgba(251,191,36,.08)', fg: theme.warning, border: 'rgba(251,191,36,.25)' }
        : { bg: theme.accentSoft, fg: theme.accent, border: 'rgba(139,92,255,.25)' };
  return (
    <View style={[styles.pill, { backgroundColor: colors.bg, borderColor: colors.border }]}>
      <Text style={[styles.pillText, { color: colors.fg }]}>{children}</Text>
    </View>
  );
}

export function PrimaryButton({
  label,
  onPress,
  disabled,
  loading,
  tone = 'accent',
  icon,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  loading?: boolean;
  tone?: 'accent' | 'ghost';
  icon?: keyof typeof Ionicons.glyphMap;
}) {
  const theme = useTheme();
  const bg = tone === 'accent' ? theme.accent : theme.surface;
  const fg = tone === 'accent' ? '#FFFFFF' : theme.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      disabled={disabled || loading}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        {
          backgroundColor: bg,
          borderColor: tone === 'accent' ? 'transparent' : theme.lineStrong,
          opacity: disabled ? 0.45 : pressed ? 0.78 : 1,
        },
      ]}>
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <>
          {icon ? <Ionicons name={icon} size={17} color={fg} /> : null}
          <Text style={[styles.buttonText, { color: fg }]}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

export function SearchField({
  value,
  onChangeText,
  placeholder,
  ...props
}: TextInputProps & { value: string; onChangeText: (value: string) => void }) {
  const theme = useTheme();
  return (
    <View style={[styles.search, { backgroundColor: theme.surface, borderColor: theme.line }]}>
      <Ionicons name="search" size={16} color={theme.dim} />
      <TextInput
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.dim}
        style={[styles.searchInput, { color: theme.text }]}
        autoCorrect={false}
        autoCapitalize="none"
        {...props}
      />
    </View>
  );
}

export function Chip({
  label,
  active,
  onPress,
}: {
  label: string;
  active: boolean;
  onPress: () => void;
}) {
  const theme = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: active }}
      onPress={onPress}
      style={[
        styles.chip,
        {
          borderColor: active ? 'rgba(139,92,255,.45)' : theme.line,
          backgroundColor: active ? theme.accentSoft : 'transparent',
        },
      ]}>
      <Text style={[styles.chipText, { color: active ? theme.text : theme.muted }]}>{label}</Text>
    </Pressable>
  );
}

export function Empty({ text }: { text: string }) {
  const theme = useTheme();
  return (
    <View style={[styles.empty, { borderColor: theme.lineStrong }]}>
      <Text style={{ color: theme.dim, textAlign: 'center', fontSize: 12 }}>{text}</Text>
    </View>
  );
}

export function ErrorState({ text, onRetry }: { text: string; onRetry?: () => void }) {
  const theme = useTheme();
  return (
    <Card style={{ gap: 10 }}>
      <Text style={{ color: theme.text, fontSize: 14, fontWeight: '600' }}>Не удалось загрузить</Text>
      <Text style={{ color: theme.muted, fontSize: 12, lineHeight: 18 }}>{text}</Text>
      {onRetry ? <PrimaryButton label="Повторить" onPress={onRetry} tone="ghost" /> : null}
    </Card>
  );
}

export function Divider() {
  const theme = useTheme();
  return <View style={{ height: StyleSheet.hairlineWidth, backgroundColor: theme.line }} />;
}

const styles = StyleSheet.create({
  appbar: {
    height: 58,
    backgroundColor: 'transparent',
    paddingHorizontal: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  brandName: { fontSize: 15, fontWeight: '700', letterSpacing: -0.2 },
  brandTag: { fontFamily: 'monospace', fontSize: 9, letterSpacing: 1.2, marginTop: 1 },
  iconButton: {
    width: 38,
    height: 38,
    borderRadius: 19,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  eyebrow: {
    fontFamily: 'monospace',
    fontSize: 9,
    letterSpacing: 1.4,
    textTransform: 'uppercase',
  },
  lead: { fontSize: 14, lineHeight: 21, marginTop: 8 },
  card: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.lg,
    padding: 15,
  },
  pill: {
    alignSelf: 'flex-start',
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: 9,
    paddingVertical: 4,
  },
  pillText: { fontFamily: 'monospace', fontSize: 9, letterSpacing: 0.7, textTransform: 'uppercase' },
  button: {
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 16,
  },
  buttonText: { fontSize: 13, fontWeight: '600' },
  search: {
    height: 44,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingHorizontal: 12,
  },
  searchInput: { flex: 1, fontSize: 13, paddingVertical: 0 },
  chip: {
    borderWidth: StyleSheet.hairlineWidth,
    borderRadius: radius.pill,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  chipText: { fontSize: 11, fontWeight: '500' },
  empty: {
    padding: 28,
    borderWidth: 1,
    borderStyle: 'dashed',
    borderRadius: radius.md,
    alignItems: 'center',
  },
});
