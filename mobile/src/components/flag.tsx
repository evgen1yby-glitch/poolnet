import { Image, StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme';

const flags: Record<string, number> = {
  'ae': require('../../assets/flags/ae.png'),
  'al': require('../../assets/flags/al.png'),
  'am': require('../../assets/flags/am.png'),
  'ar': require('../../assets/flags/ar.png'),
  'at': require('../../assets/flags/at.png'),
  'au': require('../../assets/flags/au.png'),
  'az': require('../../assets/flags/az.png'),
  'ba': require('../../assets/flags/ba.png'),
  'be': require('../../assets/flags/be.png'),
  'bg': require('../../assets/flags/bg.png'),
  'br': require('../../assets/flags/br.png'),
  'by': require('../../assets/flags/by.png'),
  'ca': require('../../assets/flags/ca.png'),
  'ch': require('../../assets/flags/ch.png'),
  'cl': require('../../assets/flags/cl.png'),
  'cr': require('../../assets/flags/cr.png'),
  'cy': require('../../assets/flags/cy.png'),
  'cz': require('../../assets/flags/cz.png'),
  'de': require('../../assets/flags/de.png'),
  'dk': require('../../assets/flags/dk.png'),
  'ee': require('../../assets/flags/ee.png'),
  'es': require('../../assets/flags/es.png'),
  'fi': require('../../assets/flags/fi.png'),
  'fr': require('../../assets/flags/fr.png'),
  'gb': require('../../assets/flags/gb.png'),
  'ge': require('../../assets/flags/ge.png'),
  'gr': require('../../assets/flags/gr.png'),
  'hk': require('../../assets/flags/hk.png'),
  'hr': require('../../assets/flags/hr.png'),
  'hu': require('../../assets/flags/hu.png'),
  'id': require('../../assets/flags/id.png'),
  'ie': require('../../assets/flags/ie.png'),
  'il': require('../../assets/flags/il.png'),
  'in': require('../../assets/flags/in.png'),
  'is': require('../../assets/flags/is.png'),
  'it': require('../../assets/flags/it.png'),
  'jp': require('../../assets/flags/jp.png'),
  'kr': require('../../assets/flags/kr.png'),
  'kz': require('../../assets/flags/kz.png'),
  'lt': require('../../assets/flags/lt.png'),
  'lu': require('../../assets/flags/lu.png'),
  'lv': require('../../assets/flags/lv.png'),
  'md': require('../../assets/flags/md.png'),
  'me': require('../../assets/flags/me.png'),
  'mk': require('../../assets/flags/mk.png'),
  'mt': require('../../assets/flags/mt.png'),
  'mx': require('../../assets/flags/mx.png'),
  'my': require('../../assets/flags/my.png'),
  'nl': require('../../assets/flags/nl.png'),
  'no': require('../../assets/flags/no.png'),
  'nz': require('../../assets/flags/nz.png'),
  'ph': require('../../assets/flags/ph.png'),
  'pl': require('../../assets/flags/pl.png'),
  'pt': require('../../assets/flags/pt.png'),
  'ro': require('../../assets/flags/ro.png'),
  'rs': require('../../assets/flags/rs.png'),
  'ru': require('../../assets/flags/ru.png'),
  'se': require('../../assets/flags/se.png'),
  'sg': require('../../assets/flags/sg.png'),
  'si': require('../../assets/flags/si.png'),
  'sk': require('../../assets/flags/sk.png'),
  'th': require('../../assets/flags/th.png'),
  'tr': require('../../assets/flags/tr.png'),
  'tw': require('../../assets/flags/tw.png'),
  'ua': require('../../assets/flags/ua.png'),
  'uz': require('../../assets/flags/uz.png'),
  'vn': require('../../assets/flags/vn.png'),
  'za': require('../../assets/flags/za.png'),
};

export function Flag({ code, size = 22, rounded = true }: { code?: string | null; size?: number; rounded?: boolean }) {
  const theme = useTheme();
  const cc = String(code || '').toLowerCase();
  const source = flags[cc];
  if (!source) {
    return (
      <View style={[styles.fallback, { width: size * 1.5, height: size, borderColor: theme.line }]}>
        <Text style={{ color: theme.muted, fontSize: size * 0.42, fontWeight: '700' }}>{cc ? cc.toUpperCase() : '—'}</Text>
      </View>
    );
  }
  return (
    <Image
      source={source}
      style={{ width: size * 1.5, height: size, borderRadius: rounded ? Math.max(2, size * 0.1) : 0 }}
      resizeMode="cover"
    />
  );
}

const styles = StyleSheet.create({
  fallback: { borderWidth: StyleSheet.hairlineWidth, borderRadius: 3, alignItems: 'center', justifyContent: 'center' },
});
