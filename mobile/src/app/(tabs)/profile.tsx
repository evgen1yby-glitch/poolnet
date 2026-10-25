import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import * as Linking from 'expo-linking';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { AppBar, Eyebrow, Lead, Pill, ProfileButton, Screen, Title } from '@/components/ui';
import { useAppStore } from '@/store/app';
import { radius, useTheme } from '@/theme';

const SITE = 'https://poolnet.online';
const GITHUB = 'https://github.com/evgen1yby-glitch/poolnet';

type RowProps = {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  onPress: () => void;
  destructive?: boolean;
};

function MenuRow({ icon, title, onPress, destructive }: RowProps) {
  const theme = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.menuRow, { borderColor: theme.line, opacity: pressed ? 0.6 : 1 }]}>
      <Ionicons name={icon} size={18} color={destructive ? theme.danger : theme.muted} />
      <Text style={[styles.menuText, { color: destructive ? theme.danger : theme.muted }]}>{title}</Text>
      <Ionicons name="chevron-forward" size={16} color={theme.dim} />
    </Pressable>
  );
}

export default function ProfileScreen() {
  const theme = useTheme();
  const router = useRouter();
  const subscription = useAppStore((state) => state.subscription);
  const setSubscription = useAppStore((state) => state.setSubscription);
  const version = Constants.expoConfig?.version ?? '0.1.0';

  const clear = () => {
    Alert.alert(
      'Удалить ключ?',
      'Ссылка будет удалена с этого устройства. Отменить это действие нельзя.',
      [
        { text: 'Отмена', style: 'cancel' },
        {
          text: 'Удалить',
          style: 'destructive',
          onPress: () => void setSubscription(null),
        },
      ],
    );
  };

  return (
    <>
      <AppBar right={<ProfileButton />} />
      <Screen>
        <Eyebrow>ПРИЛОЖЕНИЕ</Eyebrow>
        <Title>Профиль</Title>
        <Lead>Локальный профиль без аккаунта и без облачной синхронизации.</Lead>

        <View style={[styles.profile, { backgroundColor: theme.surface, borderColor: theme.line }]}>
          <View style={[styles.avatar, { backgroundColor: theme.accentSoft, borderColor: 'rgba(139,92,255,.3)' }]}>
            <Text style={[styles.avatarText, { color: theme.accent }]}>P</Text>
          </View>
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={[styles.name, { color: theme.text }]}>Гость</Text>
            <Text style={[styles.meta, { color: theme.dim }]}>без аккаунта · без истории</Text>
          </View>
          <Pill tone={subscription ? 'success' : 'neutral'}>{subscription ? 'КЛЮЧ' : 'FREE'}</Pill>
        </View>

        <Text style={[styles.section, { color: theme.text }]}>Приложение</Text>
        <View style={[styles.menu, { borderColor: theme.line }]}>
          <MenuRow icon="shield-checkmark-outline" title="Как это работает" onPress={() => router.push('/onboarding')} />
          <MenuRow icon="pulse-outline" title="Методика проверки" onPress={() => void Linking.openURL(`${SITE}/verify`)} />
          <MenuRow icon="stats-chart-outline" title="Статус сервиса" onPress={() => void Linking.openURL(`${SITE}/status`)} />
          <MenuRow icon="logo-github" title="GitHub проекта" onPress={() => void Linking.openURL(GITHUB)} />
        </View>

        <Text style={[styles.section, { color: theme.text }]}>Данные</Text>
        <View style={[styles.menu, { borderColor: theme.line }]}>
          <MenuRow icon="document-text-outline" title="Условия использования" onPress={() => void Linking.openURL(`${SITE}/legal`)} />
          <MenuRow icon="lock-closed-outline" title="Приватность" onPress={() => void Linking.openURL(`${SITE}/legal`)} />
          {subscription ? <MenuRow icon="trash-outline" title="Удалить ключ с устройства" onPress={clear} destructive /> : null}
        </View>

        <Pressable
          onPress={() => void Linking.openURL(GITHUB)}
          style={[styles.star, { backgroundColor: 'rgba(251,191,36,.045)', borderColor: 'rgba(251,191,36,.22)' }]}>
          <Ionicons name="star" size={21} color={theme.warning} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={[styles.starTitle, { color: theme.text }]}>Нравится PoolNet?</Text>
            <Text style={[styles.starText, { color: theme.dim }]}>Звезда на GitHub помогает другим найти проект.</Text>
          </View>
          <Ionicons name="chevron-forward" size={16} color={theme.dim} />
        </Pressable>

        <Text style={[styles.version, { color: theme.dim }]}>PoolNet Mobile · {version} · companion build</Text>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  profile: { marginTop: 16, borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.lg, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 12 },
  avatar: { width: 48, height: 48, borderRadius: 15, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontSize: 18, fontWeight: '700' },
  name: { fontSize: 14, fontWeight: '600' },
  meta: { fontSize: 10.5 },
  section: { fontSize: 14, fontWeight: '600', marginTop: 22, marginBottom: 8 },
  menu: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.md, overflow: 'hidden' },
  menuRow: { flexDirection: 'row', alignItems: 'center', gap: 11, padding: 13, borderBottomWidth: StyleSheet.hairlineWidth },
  menuText: { flex: 1, fontSize: 12.5 },
  star: { marginTop: 16, borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.md, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 11 },
  starTitle: { fontSize: 12, fontWeight: '600' },
  starText: { fontSize: 10.5, lineHeight: 15 },
  version: { textAlign: 'center', fontFamily: 'monospace', fontSize: 9, marginTop: 22 },
});
