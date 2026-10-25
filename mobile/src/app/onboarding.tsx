import { Ionicons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Eyebrow, PrimaryButton } from '@/components/ui';
import { useTheme } from '@/theme';

export default function OnboardingScreen() {
  const theme = useTheme();
  const router = useRouter();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: theme.bg }} edges={['top', 'bottom']}>
      <View style={styles.wrap}>
        <View style={styles.brand}>
          <Ionicons name="shield-checkmark" size={30} color={theme.accent} />
          <Text style={[styles.brandText, { color: theme.text }]}>PoolNet</Text>
          <Text style={[styles.brandTag, { color: theme.dim }]}>MOBILE</Text>
        </View>
        <View style={styles.body}>
          <Eyebrow>POOLNET MOBILE</Eyebrow>
          <Text style={[styles.title, { color: theme.text }]}>
            Интернет{'\n'}без лишних <Text style={{ color: theme.accent }}>глаз.</Text>
          </Text>
          <Text style={[styles.lead, { color: theme.muted }]}>
            Публичные VPN-узлы и прокси. PoolNet проверяет соединения, показывает факты и не обещает
            того, чего нет.
          </Text>
          {[
            ['shield-checkmark-outline', 'Проверено трафиком', 'TCP, TLS и сквозной HTTP-запрос — до публикации.'],
            ['key-outline', 'Без аккаунта', 'Бесплатный ключ на 7 дней за несколько секунд.'],
            ['lock-closed-outline', 'Прямое соединение', 'Трафик идёт клиент → узел. PoolNet не оператор.'],
          ].map(([icon, title, body]) => (
            <View key={title} style={[styles.feature, { borderColor: theme.line }]}>
              <Ionicons name={icon as keyof typeof Ionicons.glyphMap} size={18} color={theme.accent} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={[styles.featureTitle, { color: theme.text }]}>{title}</Text>
                <Text style={[styles.featureText, { color: theme.dim }]}>{body}</Text>
              </View>
            </View>
          ))}
        </View>
        <View style={styles.cta}>
          <PrimaryButton label="Начать" onPress={() => router.replace('/(tabs)')} />
          <PrimaryButton label="У меня уже есть ключ" tone="ghost" onPress={() => router.replace('/(tabs)/key')} />
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, paddingHorizontal: 22, paddingBottom: 18 },
  brand: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingTop: 6 },
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
