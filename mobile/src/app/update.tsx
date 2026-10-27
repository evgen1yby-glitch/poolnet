import { Ionicons } from '@expo/vector-icons';
import * as Linking from 'expo-linking';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { AppBar, Card, CloseButton, ErrorState, Eyebrow, Lead, PrimaryButton, Screen, Title } from '@/components/ui';
import { currentVersion, checkForUpdates, downloadAndInstall, openInstallSettings, type UpdateCheck } from '@/lib/updates';
import { useT } from '@/lib/use-t';
import { useAppStore } from '@/store/app';
import { useTheme } from '@/theme';

type Stage = 'idle' | 'checking' | 'latest' | 'available' | 'downloading' | 'permission' | 'installer' | 'error';

export default function UpdateScreen() {
  const theme = useTheme();
  const t = useT();
  const language = useAppStore((state) => state.language);
  const [stage, setStage] = useState<Stage>('idle');
  const [info, setInfo] = useState<UpdateCheck | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const installed = currentVersion();

  const check = async () => {
    setStage('checking');
    setError(null);
    try {
      const result = await checkForUpdates();
      setInfo(result);
      setStage(result.available ? 'available' : 'latest');
    } catch (cause) {
      const raw = cause instanceof Error ? cause.message : String(cause);
      setError(raw.includes('manifest') ? t('update.invalidManifest') : t('update.networkError'));
      setStage('error');
    }
  };

  const download = async () => {
    if (!info) return;
    setStage('downloading');
    setProgress(0);
    setError(null);
    try {
      const result = await downloadAndInstall(info.manifest, setProgress);
      setStage(result.status === 'permission' ? 'permission' : 'installer');
    } catch (cause) {
      const raw = cause instanceof Error ? cause.message : String(cause);
      setError(raw.includes('checksum') || raw.includes('size') ? t('update.checksumError') : t('update.downloadError'));
      setStage('error');
    }
  };

  const notes = info ? info.manifest.releaseNotes[language] || info.manifest.releaseNotes.ru : '';

  return (
    <>
      <AppBar right={<CloseButton />} />
      <Screen>
        <Eyebrow>{t('update.eyebrow')}</Eyebrow>
        <Title>{t('update.title')}</Title>
        <Lead>{t('update.lead')}</Lead>

        <Card style={styles.versionCard}>
          <View style={styles.versionRow}>
            <View style={{ flex: 1 }}>
              <Text style={[styles.label, { color: theme.dim }]}>{t('update.current', { version: installed.name })}</Text>
              {info ? <Text style={[styles.latest, { color: theme.text }]}>{t('update.latest', { version: info.manifest.versionName })}</Text> : null}
            </View>
            <View style={[styles.icon, { backgroundColor: theme.accentSoft, borderColor: theme.line }]}>
              <Ionicons name={stage === 'latest' ? 'checkmark' : 'cloud-download-outline'} size={20} color={theme.text} />
            </View>
          </View>

          {stage === 'checking' ? <ActivityIndicator color={theme.text} style={{ marginTop: 18 }} /> : null}
          {stage === 'latest' ? (
            <View style={styles.result}>
              <Text style={[styles.resultTitle, { color: theme.text }]}>{t('update.upToDate')}</Text>
              <Text style={[styles.body, { color: theme.muted }]}>{t('update.upToDateBody')}</Text>
            </View>
          ) : null}
          {stage === 'permission' ? (
            <View style={styles.result}>
              <Text style={[styles.resultTitle, { color: theme.text }]}>{t('update.permissionTitle')}</Text>
              <Text style={[styles.body, { color: theme.muted }]}>{t('update.permissionBody')}</Text>
              <PrimaryButton label={t('update.download')} onPress={() => void download()} icon="download-outline" />
              <PrimaryButton label={t('update.openSettings')} onPress={() => void openInstallSettings()} tone="ghost" icon="settings-outline" />
            </View>
          ) : null}
          {stage === 'installer' ? (
            <View style={styles.result}>
              <Text style={[styles.resultTitle, { color: theme.text }]}>{t('update.ready')}</Text>
              <Text style={[styles.body, { color: theme.muted }]}>{t('update.installHint')}</Text>
            </View>
          ) : null}
        </Card>

        {stage === 'available' && info ? (
          <Card style={styles.releaseCard}>
            <View style={styles.releaseTop}>
              <View style={{ flex: 1 }}>
                <Text style={[styles.releaseTitle, { color: theme.text }]}>{t('update.available', { version: info.manifest.versionName })}</Text>
                <Text style={[styles.body, { color: theme.muted }]}>{t('update.availableBody')}</Text>
              </View>
              <Text style={[styles.size, { color: theme.dim }]}>{t('update.size', { size: Math.ceil(info.manifest.size / 1_048_576) })}</Text>
            </View>
            {notes ? (
              <View style={[styles.notes, { borderColor: theme.line }]}>
                <Text style={[styles.notesTitle, { color: theme.text }]}>{t('update.notes')}</Text>
                <Text style={[styles.body, { color: theme.muted }]}>{notes}</Text>
              </View>
            ) : null}
            <PrimaryButton label={t('update.download')} onPress={() => void download()} icon="download-outline" />
          </Card>
        ) : null}

        {stage === 'downloading' ? (
          <Card style={styles.releaseCard}>
            <Text style={[styles.resultTitle, { color: theme.text }]}>{t('update.downloading', { percent: progress })}</Text>
            <View style={[styles.progress, { backgroundColor: theme.line }]}>
              <View style={[styles.progressFill, { backgroundColor: theme.text, width: `${Math.max(2, progress)}%` }]} />
            </View>
            <Text style={[styles.body, { color: theme.dim }]}>{t('update.downloadingHint')}</Text>
          </Card>
        ) : null}

        {error ? (
          stage === 'error' ? <ErrorState text={error} onRetry={() => void check()} /> : <Text style={[styles.body, { color: theme.warning }]}>{error}</Text>
        ) : null}

        {stage !== 'downloading' ? (
          <PrimaryButton label={t('update.check')} onPress={() => void check()} tone="ghost" icon="refresh-outline" />
        ) : null}
        <Pressable
          onPress={() => void Linking.openURL('https://poolnet.online/app/')}
          style={({ pressed }) => [styles.browser, { borderColor: theme.line, opacity: pressed ? 0.6 : 1 }]}>
          <Text style={[styles.browserText, { color: theme.dim }]}>{t('update.browser')}</Text>
          <Ionicons name="open-outline" size={14} color={theme.dim} />
        </Pressable>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  versionCard: { marginTop: 16, gap: 10 },
  versionRow: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  label: { fontFamily: 'monospace', fontSize: 9, letterSpacing: 0.4 },
  latest: { marginTop: 4, fontSize: 16, fontWeight: '600', letterSpacing: -0.3 },
  icon: { width: 42, height: 42, borderWidth: StyleSheet.hairlineWidth, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  result: { gap: 8, marginTop: 4 },
  resultTitle: { fontSize: 15, fontWeight: '600', letterSpacing: -0.2 },
  body: { fontSize: 11.5, lineHeight: 17 },
  releaseCard: { marginTop: 10, gap: 12 },
  releaseTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 },
  releaseTitle: { fontSize: 15, fontWeight: '600', letterSpacing: -0.25 },
  size: { fontFamily: 'monospace', fontSize: 9, marginTop: 2 },
  notes: { borderTopWidth: StyleSheet.hairlineWidth, paddingTop: 10, gap: 5 },
  notesTitle: { fontSize: 11, fontWeight: '600' },
  progress: { height: 4, borderRadius: 4, overflow: 'hidden', marginTop: 3 },
  progressFill: { height: '100%', borderRadius: 4 },
  browser: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 5, marginTop: 16, paddingVertical: 8, borderTopWidth: StyleSheet.hairlineWidth },
  browserText: { fontSize: 10 },
});
