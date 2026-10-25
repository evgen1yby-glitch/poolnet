import { Ionicons } from '@expo/vector-icons';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useRouter } from 'expo-router';
import { AppBar, Card, CloseButton, ErrorState, Eyebrow, Lead, Pill, PrimaryButton, Screen, Title } from '@/components/ui';
import { api, ApiError } from '@/lib/api';
import { daysLeft, formatDate, formatRetry } from '@/lib/format';
import { useT } from '@/lib/use-t';
import { useAppStore } from '@/store/app';
import { useTheme } from '@/theme';

export default function KeyScreen() {
  const theme = useTheme();
  const t = useT();
  const language = useAppStore((state) => state.language);
  const router = useRouter();
  const queryClient = useQueryClient();
  const subscription = useAppStore((state) => state.subscription);
  const country = useAppStore((state) => state.country);
  const setSubscription = useAppStore((state) => state.setSubscription);
  const [claiming, setClaiming] = useState(false);
  const [waitLeft, setWaitLeft] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const status = useQuery({ queryKey: ['free-status'], queryFn: api.freeStatus, retry: 1 });

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  const left = subscription ? daysLeft(subscription.expiresAt) : 0;
  const active = Boolean(subscription && left > 0);
  const subscriptionUrl = subscription
    ? country
      ? `${subscription.url}/country/${country.cc.toLowerCase()}`
      : subscription.url
    : null;
  const remaining = status.data?.retry_after ?? 0;

  const copy = async () => {
    if (!subscriptionUrl) return;
    await Clipboard.setStringAsync(subscriptionUrl);
    await Haptics.selectionAsync().catch(() => undefined);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };

  const claim = async () => {
    if (!status.data?.available || claiming) return;
    setClaiming(true);
    setError(null);
    try {
      const challenge = await api.freeChallenge();
      const wait = Math.max(0, challenge.wait_seconds || 0);
      if (wait > 0) {
        setWaitLeft(wait);
        await new Promise<void>((resolve) => {
          let left = wait;
          timer.current = setInterval(() => {
            left -= 1;
            setWaitLeft(Math.max(0, left));
            if (left <= 0) {
              if (timer.current) clearInterval(timer.current);
              timer.current = null;
              resolve();
            }
          }, 1000);
        });
      }
      const key = await api.freeClaim(challenge.challenge);
      await setSubscription({ token: key.token, url: key.subscription, expiresAt: key.expires_at });
      await queryClient.invalidateQueries({ queryKey: ['free-status'] });
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
    } catch (cause) {
      if (cause instanceof ApiError) {
        const message = cause.retryAfter
          ? t('key.retry', { time: formatRetry(cause.retryAfter, language) })
          : cause.code === 'timeout'
            ? t('error.timeout')
            : cause.code === 'network'
              ? t('error.network')
              : cause.status >= 500
                ? t('error.service')
                : cause.message;
        setError(message);
      } else {
        setError(t('key.errorGeneric'));
      }
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error).catch(() => undefined);
    } finally {
      setClaiming(false);
      setWaitLeft(0);
    }
  };

  return (
    <>
      <AppBar right={<CloseButton />} />
      <Screen>
        <Eyebrow>{t('key.eyebrow')}</Eyebrow>
        <Title>{t('key.title')}</Title>
        <Lead>{t('key.lead')}</Lead>

        {active && subscription ? (
          <>
            <Card style={[styles.keyCard, { borderColor: theme.lineStrong }]}>
              <View style={styles.rowBetween}>
                <Text style={[styles.keyLabel, { color: theme.accent }]}>PERSONAL KEY</Text>
                <Pill tone="success">{t('key.active')}</Pill>
              </View>
              <View style={styles.daysRow}>
                <Text style={[styles.days, { color: theme.text }]}>{left}</Text>
                <Text style={[styles.daysMeta, { color: theme.muted }]}>{t('key.daysLeft')}</Text>
              </View>
              <View style={[styles.progress, { backgroundColor: theme.line }]}>
                <View style={[styles.progressFill, { backgroundColor: theme.accent, width: `${Math.max(4, Math.min(100, (left / 7) * 100))}%` }]} />
              </View>
              <View style={styles.rowBetween}>
                <Text style={[styles.small, { color: theme.dim }]}>{t('key.until', { date: formatDate(subscription.expiresAt, language) })}</Text>
                <Text style={[styles.small, { color: theme.dim }]}>{t('key.week')}</Text>
              </View>
              <View style={[styles.subBox, { borderColor: theme.line, backgroundColor: theme.bgAlt }]}>
                <Text style={[styles.subText, { color: theme.muted }]} numberOfLines={1}>{subscriptionUrl}</Text>
                <Pressable onPress={() => void copy()} accessibilityRole="button" accessibilityLabel={t('key.copy')} style={[styles.copy, { backgroundColor: theme.surface2 }]}>
                  <Ionicons name={copied ? 'checkmark' : 'copy-outline'} size={16} color={copied ? theme.success : theme.muted} />
                </Pressable>
              </View>
              <PrimaryButton label={copied ? t('key.copied') : t('key.copy')} onPress={() => void copy()} icon="copy-outline" />
            </Card>

            <PrimaryButton label={t('key.done')} onPress={() => router.back()} tone="ghost" />
            <Text style={[styles.section, { color: theme.text }]}>{t('key.how')}</Text>
            <View style={styles.steps}>
              {[
                ['01', t('key.step1title'), t('key.step1body')],
                ['02', t('key.step2title'), t('key.step2body')],
                ['03', t('key.step3title'), t('key.step3body')],
              ].map(([n, title, body]) => (
                <View key={n} style={styles.step}>
                  <View style={[styles.stepNo, { backgroundColor: theme.accentSoft }]}>
                    <Text style={[styles.stepNoText, { color: theme.accent }]}>{n}</Text>
                  </View>
                  <View style={styles.stepMain}>
                    <Text style={[styles.stepTitle, { color: theme.text }]}>{title}</Text>
                    <Text style={[styles.stepBody, { color: theme.dim }]}>{body}</Text>
                  </View>
                </View>
              ))}
            </View>
          </>
        ) : (
          <Card style={styles.emptyCard}>
            <View style={[styles.emptyIcon, { backgroundColor: theme.accentSoft }]}>
              <Ionicons name="key-outline" size={25} color={theme.accent} />
            </View>
            <Text style={[styles.emptyTitle, { color: theme.text }]}>
              {subscription ? t('key.expired') : t('key.none')}
            </Text>
            <Text style={[styles.emptyText, { color: theme.muted }]}>
              {t('key.empty')}
            </Text>

            {status.isError ? <ErrorState text={t('key.checkError')} onRetry={() => status.refetch()} /> : null}
            {!status.data?.available && remaining > 0 ? (
              <Text style={[styles.retry, { color: theme.warning }]}>
                {t('key.retry', { time: formatRetry(remaining, language) })}
              </Text>
            ) : null}
            {error ? <Text style={[styles.retry, { color: theme.danger }]}>{error}</Text> : null}

            <PrimaryButton
              label={claiming ? (waitLeft > 0 ? t('key.wait', { seconds: waitLeft }) : t('key.checking')) : t('key.get')}
              onPress={() => void claim()}
              loading={claiming && waitLeft === 0}
              disabled={claiming || !status.data?.available || remaining > 0}
              icon="download-outline"
            />
            <Text style={[styles.fine, { color: theme.dim }]}>
              {t('key.fine')}
            </Text>
          </Card>
        )}

        {status.data?.available && active ? (
          <View style={[styles.claim, { borderColor: theme.line }]}>
            <View>
              <Text style={[styles.claimTitle, { color: theme.text }]}>{t('key.next')}</Text>
              <Text style={[styles.claimMeta, { color: theme.dim }]}>{t('key.nextMeta')}</Text>
            </View>
            <Text style={[styles.claimState, { color: theme.dim }]}>{t('key.first')}</Text>
          </View>
        ) : null}
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  keyCard: { marginTop: 16, gap: 13, overflow: 'hidden' },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  keyLabel: { fontFamily: 'monospace', fontSize: 9, letterSpacing: 1.4 },
  daysRow: { flexDirection: 'row', alignItems: 'baseline', gap: 6, marginTop: 2 },
  days: { fontSize: 46, fontWeight: '700', letterSpacing: -2.2 },
  daysMeta: { fontSize: 13 },
  progress: { height: 5, borderRadius: 4, overflow: 'hidden' },
  progressFill: { height: '100%', borderRadius: 4 },
  small: { fontSize: 9.5 },
  subBox: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: StyleSheet.hairlineWidth, borderRadius: 13, padding: 10 },
  subText: { flex: 1, fontFamily: 'monospace', fontSize: 10 },
  copy: { width: 32, height: 32, borderRadius: 9, alignItems: 'center', justifyContent: 'center' },
  section: { fontSize: 15, fontWeight: '600', marginTop: 24, marginBottom: 8 },
  steps: { gap: 12 },
  step: { flexDirection: 'row', gap: 11, alignItems: 'flex-start' },
  stepNo: { width: 22, height: 22, borderRadius: 7, alignItems: 'center', justifyContent: 'center' },
  stepNoText: { fontFamily: 'monospace', fontSize: 9 },
  stepMain: { flex: 1, gap: 1 },
  stepTitle: { fontSize: 12, fontWeight: '600' },
  stepBody: { fontSize: 10.5, lineHeight: 16 },
  emptyCard: { marginTop: 16, gap: 12, alignItems: 'stretch' },
  emptyIcon: { width: 46, height: 46, borderRadius: 15, alignItems: 'center', justifyContent: 'center' },
  emptyTitle: { fontSize: 17, fontWeight: '700', letterSpacing: -0.4 },
  emptyText: { fontSize: 12, lineHeight: 18 },
  retry: { fontSize: 11, lineHeight: 17 },
  fine: { fontSize: 9.5, lineHeight: 15 },
  claim: { marginTop: 18, borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 14, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  claimTitle: { fontSize: 12, fontWeight: '600' },
  claimMeta: { fontSize: 10, marginTop: 2 },
  claimState: { fontSize: 10 },
});
