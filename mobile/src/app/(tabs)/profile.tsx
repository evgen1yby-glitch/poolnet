import { Ionicons } from '@expo/vector-icons';
import Constants from 'expo-constants';
import { useRouter } from 'expo-router';
import * as Linking from 'expo-linking';
import { Alert, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { Flag } from '@/components/flag';

import { AppBar, Eyebrow, Lead, Pill, ProfileButton, Screen, Title } from '@/components/ui';
import { languageOptions } from '@/i18n';
import { countryName } from '@/lib/format';
import { tunnelStatus } from '@/lib/tunnel';
import { useLanguage, useT } from '@/lib/use-t';
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
  const t = useT();
  const language = useLanguage();
  const router = useRouter();
  const subscription = useAppStore((state) => state.subscription);
  const setSubscription = useAppStore((state) => state.setSubscription);
  const setLanguage = useAppStore((state) => state.setLanguage);
  const version = Constants.expoConfig?.version ?? '0.1.0';

  const clear = () => {
    Alert.alert(
      t('profile.alertTitle'),
      t('profile.alertBody'),
      [
        { text: t('common.cancel'), style: 'cancel' },
        {
          text: t('common.delete'),
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
        <Eyebrow>{t('profile.eyebrow')}</Eyebrow>
        <Title>{t('profile.title')}</Title>
        <Lead>{t('profile.lead')}</Lead>

        <View style={[styles.profile, { backgroundColor: theme.surface, borderColor: theme.line }]}>
          <View style={[styles.avatar, { backgroundColor: theme.accentSoft, borderColor: theme.lineStrong }]}>
            <Text style={[styles.avatarText, { color: theme.accent }]}>P</Text>
          </View>
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={[styles.name, { color: theme.text }]}>{t('profile.guest')}</Text>
            <Text style={[styles.meta, { color: theme.dim }]}>{t('profile.noAccount')}</Text>
          </View>
          <Pill tone={subscription ? 'success' : 'neutral'}>{subscription ? t('profile.badgeKey') : 'FREE'}</Pill>
        </View>

        <Text style={[styles.section, { color: theme.text }]}>{t('common.language')}</Text>
        <View style={[styles.languageCard, { backgroundColor: theme.surface, borderColor: theme.line }]}>
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={[styles.languageTitle, { color: theme.text }]}>{t('profile.interface')}</Text>
            <Text style={[styles.languageSub, { color: theme.dim }]}>{t('profile.languageSub')}</Text>
          </View>
          <View style={[styles.languageRow, { backgroundColor: theme.bgAlt, borderColor: theme.line }]}>
            {languageOptions.map((option) => {
              const selected = language === option.code;
              return (
                <Pressable
                  key={option.code}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  accessibilityLabel={option.label}
                  onPress={() => void setLanguage(option.code)}
                  style={[styles.languageOption, selected && { backgroundColor: theme.surface2 }]}>
                  <Flag code={option.flag} size={14} />
                  <Text style={[styles.languageLabel, { color: selected ? theme.text : theme.dim }]}>{option.code.toUpperCase()}</Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <Text style={[styles.section, { color: theme.text }]}>{t('profile.sectionApp')}</Text>
        <View style={[styles.menu, { borderColor: theme.line }]}>
          <MenuRow icon="shield-checkmark-outline" title={t('profile.how')} onPress={() => router.push('/onboarding')} />
          <MenuRow icon="pulse-outline" title={t('profile.method')} onPress={() => void Linking.openURL(`${SITE}/verify`)} />
          <MenuRow icon="stats-chart-outline" title={t('profile.status')} onPress={() => void Linking.openURL(`${SITE}/status`)} />
          <MenuRow
            icon="build-outline"
            title={t('profile.diagnostics')}
            onPress={() => {
              const state = useAppStore.getState();
              void tunnelStatus().then((status) => {
                Alert.alert(
                  t('profile.diagTitle'),
                  [
                    t('profile.diagVersion', { value: version }),
                    t('profile.diagPlatform', { value: `${Platform.OS} ${Platform.Version}` }),
                    t('profile.diagTunnel', { value: status.running ? t('profile.diagOn') : t('profile.diagOff') }),
                    t('profile.diagCountry', { value: state.country ? countryName(state.country.cc, language) : t('profile.diagAuto') }),
                    state.connectionError ? t('profile.diagError', { value: state.connectionError }) : t('profile.diagNoError'),
                  ].join('\n'),
                );
              });
            }}
          />
          <MenuRow icon="logo-github" title={t('profile.github')} onPress={() => void Linking.openURL(GITHUB)} />
        </View>

        <Text style={[styles.section, { color: theme.text }]}>{t('profile.sectionData')}</Text>
        <View style={[styles.menu, { borderColor: theme.line }]}>
          <MenuRow icon="document-text-outline" title={t('profile.terms')} onPress={() => void Linking.openURL(`${SITE}/legal`)} />
          <MenuRow icon="lock-closed-outline" title={t('profile.privacy')} onPress={() => void Linking.openURL(`${SITE}/legal`)} />
          {subscription ? <MenuRow icon="trash-outline" title={t('profile.removeKey')} onPress={clear} destructive /> : null}
        </View>

        <Pressable
          onPress={() => void Linking.openURL(GITHUB)}
          style={[styles.star, { backgroundColor: theme.accentSoft, borderColor: theme.lineStrong }]}>
          <Ionicons name="star" size={21} color={theme.text} />
          <View style={{ flex: 1, gap: 2 }}>
            <Text style={[styles.starTitle, { color: theme.text }]}>{t('profile.starTitle')}</Text>
            <Text style={[styles.starText, { color: theme.dim }]}>{t('profile.starText')}</Text>
          </View>
          <Ionicons name="chevron-forward" size={16} color={theme.dim} />
        </Pressable>

        <Text style={[styles.version, { color: theme.dim }]}>{t('profile.version', { version })}</Text>
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
  languageCard: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.md, padding: 13, flexDirection: 'row', alignItems: 'center', gap: 12 },
  languageTitle: { fontSize: 12, fontWeight: '600' },
  languageSub: { fontSize: 10 },
  languageRow: { flexDirection: 'row', padding: 3, borderRadius: 10, borderWidth: StyleSheet.hairlineWidth },
  languageOption: { minWidth: 58, height: 30, borderRadius: 8, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5 },
  languageLabel: { fontSize: 9.5, fontWeight: '600' },
  menu: { borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.md, overflow: 'hidden' },
  menuRow: { flexDirection: 'row', alignItems: 'center', gap: 11, padding: 13, borderBottomWidth: StyleSheet.hairlineWidth },
  menuText: { flex: 1, fontSize: 12.5 },
  star: { marginTop: 16, borderWidth: StyleSheet.hairlineWidth, borderRadius: radius.md, padding: 14, flexDirection: 'row', alignItems: 'center', gap: 11 },
  starTitle: { fontSize: 12, fontWeight: '600' },
  starText: { fontSize: 10.5, lineHeight: 15 },
  version: { textAlign: 'center', fontFamily: 'monospace', fontSize: 9, marginTop: 22 },
});
