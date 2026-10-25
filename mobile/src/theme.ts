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
  bg: '#07070A',
  bgAlt: '#0B0B10',
  surface: '#101015',
  surface2: '#181820',
  line: 'rgba(255,255,255,0.075)',
  lineStrong: 'rgba(255,255,255,0.14)',
  text: '#F6F4FF',
  muted: '#A09DAE',
  dim: '#716E80',
  accent: '#8B5CFF',
  accentSoft: 'rgba(139,92,255,0.14)',
  success: '#4ADE80',
  successSoft: 'rgba(74,222,128,0.10)',
  warning: '#FBBF24',
  danger: '#FB7185',
};

const light: Theme = {
  dark: false,
  bg: '#F7F5FC',
  bgAlt: '#EFECF8',
  surface: '#FFFFFF',
  surface2: '#F0EDF8',
  line: 'rgba(20,15,40,0.09)',
  lineStrong: 'rgba(20,15,40,0.16)',
  text: '#121018',
  muted: '#625D70',
  dim: '#8B8598',
  accent: '#6D46E8',
  accentSoft: 'rgba(109,70,232,0.10)',
  success: '#15803D',
  successSoft: 'rgba(21,128,61,0.09)',
  warning: '#A16207',
  danger: '#BE123C',
};

export function useTheme(): Theme {
  const scheme = useColorScheme();
  return scheme === 'light' ? light : dark;
}

export const radius = { sm: 10, md: 16, lg: 22, pill: 999 } as const;
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 22, xxl: 30 } as const;
