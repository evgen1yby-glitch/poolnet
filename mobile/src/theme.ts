import { useColorScheme } from 'react-native';

export type Theme = {
  dark: boolean;
  bg: string;
  bgAlt: string;
  surface: string;
  surface2: string;
  line: string;
  lineStrong: string;
  text: string;
  muted: string;
  dim: string;
  accent: string;
  accentSoft: string;
  success: string;
  successSoft: string;
  warning: string;
  danger: string;
};

const dark: Theme = {
  dark: true,
  bg: '#050505',
  bgAlt: '#0A0A0A',
  surface: '#0C0C0C',
  surface2: '#151515',
  line: 'rgba(255,255,255,0.085)',
  lineStrong: 'rgba(255,255,255,0.18)',
  text: '#FAFAFA',
  muted: '#A3A3A3',
  dim: '#6B6B6B',
  accent: '#F5F5F5',
  accentSoft: 'rgba(255,255,255,0.09)',
  success: '#FAFAFA',
  successSoft: 'rgba(255,255,255,0.08)',
  warning: '#D4D4D4',
  danger: '#F5F5F5',
};

const light: Theme = {
  dark: false,
  bg: '#F3F3F1',
  bgAlt: '#EAEAE7',
  surface: '#FFFFFF',
  surface2: '#F0F0ED',
  line: 'rgba(0,0,0,0.10)',
  lineStrong: 'rgba(0,0,0,0.2)',
  text: '#0A0A0A',
  muted: '#5B5B5B',
  dim: '#858585',
  accent: '#0A0A0A',
  accentSoft: 'rgba(0,0,0,0.07)',
  success: '#0A0A0A',
  successSoft: 'rgba(0,0,0,0.06)',
  warning: '#4A4A4A',
  danger: '#111111',
};

export function useTheme(): Theme {
  const scheme = useColorScheme();
  return scheme === 'light' ? light : dark;
}

export const radius = { sm: 10, md: 16, lg: 22, pill: 999 } as const;
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 22, xxl: 30 } as const;
