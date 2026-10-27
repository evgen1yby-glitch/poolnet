import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Flag } from '@/components/flag';

import { Eyebrow, PrimaryButton } from '@/components/ui';
import { languageOptions } from '@/i18n';
import { useLanguage, useT } from '@/lib/use-t';
import { useAppStore } from '@/store/app';
import { useTheme } from '@/theme';

export default function OnboardingScreen() {
  const theme = useTheme();
  const t = useT();
  const language = useLanguage();
  const setLanguage = useAppStore((state) => state.setLanguage);
  const router = useRouter();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }} edges={['top', 'bottom']}>
      <View style={styles.wrap}>
        <View style={styles.brand}>
          <View style={styles.brandLockup}>
            <Ionicons name="shield-checkmark" size={30} color={theme.text} />
            <Text style={[styles.brandText, { color: theme.text }]}>PoolNet</Text>
            <Text style={[styles.brandTag, { color: theme.dim }]}>MOBILE</Text>
          </View>
          <View style={[styles.lang, { borderColor: theme.line }]}>
            {languageOptions.map((option) => (
              <Pressable
                key={option.code}
                accessibilityRole="button"
                accessibilityState={{ selected: language === option.code }}
                accessibilityLabel={option.label}
                onPress={() => void setLanguage(option.code)}
                style={[styles.langItem, language === option.code && { backgroundColor: theme.accentSoft }]}>
                <Flag code={option.flag} size={12} />
                <Text style={[styles.langText, { color: language === option.code ? theme.text : theme.dim }]}>{option.code.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>
        </View>
        <View style={styles.body}>
          <Eyebrow>{t('onboarding.eyebrow')}</Eyebrow>
          <Text style={[styles.title, { color: theme.text }]}>
            {t('onboarding.title1')}{'\n'}{t('onboarding.title2')}
          </Text>
          <Text style={[styles.lead, { color: theme.muted }]}>{t('onboarding.lead')}</Text>
          {[
            ['globe-outline', t('onboarding.f1title'), t('onboarding.f1body')],
            ['swap-horizontal-outline', t('onboarding.f2title'), t('onboarding.f2body')],
            ['key-outline', t('onboarding.f3title'), t('onboarding.f3body')],
          ].map(([icon, title, body]) => (
            <View key={title} style={[styles.feature, { borderColor: theme.line }]}>
              <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={theme.text} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={[styles.featureTitle, { color: theme.text }]}>{title}</Text>
                <Text style={[styles.featureText, { color: theme.dim }]}>{body}</Text>
              </View>
            </View>
          ))}
        </View>
        <View style={styles.cta}>
          <PrimaryButton label={t('onboarding.start')} onPress={() => router.replace('/(tabs)')} />
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, paddingHorizontal: 22, paddingBottom: 18 },
  brand: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingTop: 6 },
  brandLockup: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  lang: { flexDirection: 'row', borderWidth: StyleSheet.hairlineWidth, borderRadius: 9, padding: 2 },
  langItem: { height: 28, minWidth: 46, borderRadius: 7, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 4 },
  langText: { fontFamily: 'monospace', fontSize: 8.5, fontWeight: '600' },
  brandText: { fontSize: 16, fontWeight: '700' },
  brandTag: { fontFamily: 'monospace', fontSize: 9, letterSpacing: 1.2 },
  body: { flex: 1, justifyContent: 'center', gap: 0 },
  title: { fontSize: 42, lineHeight: 43, fontWeight: '700', letterSpacing: -1.8, marginTop: 14, marginBottom: 16 },
  lead: { fontSize: 14, lineHeight: 21, marginBottom: 24 },
  feature: { borderTopWidth: StyleSheet.hairlineWidth, paddingVertical: 11, flexDirection: 'row', gap: 11 },
  featureTitle: { fontSize: 12.5, fontWeight: '600' },
  featureText: { fontSize: 11, lineHeight: 16 },
  cta: { gap: 9 },
});
