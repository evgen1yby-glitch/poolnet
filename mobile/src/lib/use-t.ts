import { useCallback } from 'react';

import { translate, type Lang } from '@/i18n';
import { useAppStore } from '@/store/app';

export function useT() {
  const language = useAppStore((state) => state.language);
  return useCallback(
    (key: Parameters<typeof translate>[1], vars?: Record<string, string | number>) =>
      translate(language, key, vars),
    [language],
  );
}

export function useLanguage(): Lang {
  return useAppStore((state) => state.language);
}
