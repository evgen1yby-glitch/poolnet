import { Ionicons } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';
import * as Linking from 'expo-linking';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { AppBar, Card, CloseButton, ErrorState, Eyebrow, Lead, Pill, PrimaryButton, Screen, Title } from '@/components/ui';
import { fetchSupportConfig, type SupportOffer } from '@/lib/support';
import { useT } from '@/lib/use-t';
import { useTheme } from '@/theme';

const PRIVACY = 'https://poolnet.online/legal';

export default function SupportScreen({ tab = false }: { tab?: boolean }) {
  const theme = useTheme();
  const t = useT();
  const support = useQuery({ queryKey: ['support'], queryFn: fetchSupportConfig, retry: 1 });
  const data = support.data;

  const open = (url: string) => {
    void Haptics.selectionAsync().catch(() => undefined);
    void Linking.openURL(url);
  };

  const label = (offer: SupportOffer) =>
    offer.badge || (offer.kind === 'ad' ? t('support.ad') : offer.kind === 'offerwall' ? t('support.offerwall') : t('support.partner'));

  return (
    <>
      <AppBar right={tab ? undefined : <CloseButton />} />
      <Screen>
        <Eyebrow>{t('support.eyebrow')}</Eyebrow>
        <Title>{t('support.title')}</Title>
        <Lead>{t('support.lead')}</Lead>

        <View style={[styles.note, { backgroundColor: theme.surface, borderColor: theme.line }]}>
          <Ionicons name="heart-outline" size={18} color={theme.text} />
          <Text style={[styles.noteText, { color: theme.muted }]}>{t('support.noAds')}</Text>
        </View>

        {support.isLoading ? <ActivityIndicator color={theme.text} style={{ marginTop: 24 }} /> : null}
        {support.isError ? <ErrorState text={t('support.loadError')} onRetry={() => support.refetch()} /> : null}

        {data && data.offers.length > 0 ? (
          <View style={styles.list}>
            {data.offers.map((offer) => (
              <Pressable
                key={offer.id}
                accessibilityRole="button"
                accessibilityLabel={`${label(offer)}: ${offer.title}`}
                onPress={() => open(offer.url)}
                style={({ pressed }) => [styles.offer, { backgroundColor: theme.surface, borderColor: theme.line, opacity: pressed ? 0.72 : 1 }]}>
                <View style={styles.offerTop}>
                  <Pill>{label(offer)}</Pill>
                  <Ionicons name="open-outline" size={16} color={theme.dim} />
                </View>
                <Text style={[styles.offerTitle, { color: theme.text }]}>{offer.title}</Text>
                {offer.body ? <Text style={[styles.offerBody, { color: theme.muted }]}>{offer.body}</Text> : null}
                <Text style={[styles.offerCta, { color: theme.text }]}>{offer.cta}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}

        {data && data.offers.length === 0 && !support.isLoading ? (
          <Card style={styles.empty}>
            <View style={[styles.emptyIcon, { backgroundColor: theme.accentSoft, borderColor: theme.line }]}>
              <Ionicons name="sparkles-outline" size={21} color={theme.text} />
            </View>
            <Text style={[styles.emptyTitle, { color: theme.text }]}>{t('support.empty')}</Text>
            <Text style={[styles.emptyBody, { color: theme.muted }]}>{t('support.emptyHint')}</Text>
            {data.contactUrl ? (
              <PrimaryButton label={t('support.partnerCta')} onPress={() => open(data.contactUrl!)} tone="ghost" icon="open-outline" />
            ) : null}
          </Card>
        ) : null}

        {data?.donateUrl ? (
          <Card style={styles.donate}>
            <Text style={[styles.donateTitle, { color: theme.text }]}>{t('support.donate')}</Text>
            <Text style={[styles.offerBody, { color: theme.muted }]}>{t('support.donateHint')}</Text>
            <PrimaryButton label={t('support.donateCta')} onPress={() => open(data.donateUrl!)} tone="ghost" icon="heart-outline" />
          </Card>
        ) : null}

        <Text style={[styles.disclosure, { color: theme.dim }]}>{t('support.disclosure')}</Text>
        <Pressable onPress={() => open(PRIVACY)} style={styles.privacy}>
          <Text style={[styles.privacyText, { color: theme.dim }]}>{t('support.privacy')}</Text>
        </Pressable>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  note: { marginTop: 16, padding: 12, borderWidth: StyleSheet.hairlineWidth, borderRadius: 14, flexDirection: 'row', alignItems: 'center', gap: 10 },
  noteText: { flex: 1, fontSize: 11, lineHeight: 16 },
  list: { gap: 10, marginTop: 14 },
  offer: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 16, padding: 14, gap: 8 },
  offerTop: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  offerTitle: { fontSize: 16, fontWeight: '600', letterSpacing: -0.3 },
  offerBody: { fontSize: 11.5, lineHeight: 17 },
  offerCta: { marginTop: 3, fontSize: 10, fontWeight: '600', letterSpacing: 0.1 },
  empty: { marginTop: 14, gap: 10, alignItems: 'flex-start' },
  emptyIcon: { width: 42, height: 42, borderRadius: 12, borderWidth: StyleSheet.hairlineWidth, alignItems: 'center', justifyContent: 'center' },
  emptyTitle: { fontSize: 16, fontWeight: '600' },
  emptyBody: { fontSize: 11.5, lineHeight: 17 },
  donate: { marginTop: 10, gap: 9 },
  donateTitle: { fontSize: 14, fontWeight: '600' },
  disclosure: { marginTop: 22, fontSize: 9.5, lineHeight: 15 },
  privacy: { marginTop: 10, paddingVertical: 4 },
  privacyText: { fontSize: 9.5, lineHeight: 15, textDecorationLine: 'underline' },
});
