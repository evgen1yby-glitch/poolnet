const COUNTRY_NAMES_RU: Record<string, string> = {
  NL: 'Нидерланды', DE: 'Германия', FI: 'Финляндия', GB: 'Великобритания', FR: 'Франция',
  SE: 'Швеция', PL: 'Польша', CZ: 'Чехия', AT: 'Австрия', CH: 'Швейцария',
  LT: 'Литва', LV: 'Латвия', EE: 'Эстония', MD: 'Молдова', RO: 'Румыния',
  BG: 'Болгария', IT: 'Италия', ES: 'Испания', PT: 'Португалия', IE: 'Ирландия',
  DK: 'Дания', NO: 'Норвегия', BE: 'Бельгия', CA: 'Канада', TR: 'Турция',
  KZ: 'Казахстан', GE: 'Грузия', AM: 'Армения', RS: 'Сербия', SK: 'Словакия',
  SI: 'Словения', HR: 'Хорватия', HU: 'Венгрия', GR: 'Греция', UA: 'Украина',
  JP: 'Япония', SG: 'Сингапур', HK: 'Гонконг', KR: 'Корея', AU: 'Австралия',
  IN: 'Индия', BR: 'Бразилия', AR: 'Аргентина', MX: 'Мексика', ZA: 'ЮАР',
  AE: 'ОАЭ', IL: 'Израиль', IS: 'Исландия', LU: 'Люксембург', MT: 'Мальта',
  CY: 'Кипр', AL: 'Албания', TH: 'Таиланд', TW: 'Тайвань', VN: 'Вьетнам',
  MY: 'Малайзия', CR: 'Коста-Рика', RU: 'Россия', CL: 'Чили', BY: 'Беларусь',
  BA: 'Босния', MK: 'Македония', ME: 'Черногория', AZ: 'Азербайджан', UZ: 'Узбекистан',
  PH: 'Филиппины', NZ: 'Новая Зеландия', ID: 'Индонезия', US: 'США',
};


const COUNTRY_NAMES_EN: Record<string, string> = {
  NL: 'Netherlands', DE: 'Germany', FI: 'Finland', GB: 'United Kingdom', FR: 'France',
  SE: 'Sweden', PL: 'Poland', CZ: 'Czechia', AT: 'Austria', CH: 'Switzerland',
  LT: 'Lithuania', LV: 'Latvia', EE: 'Estonia', MD: 'Moldova', RO: 'Romania',
  BG: 'Bulgaria', IT: 'Italy', ES: 'Spain', PT: 'Portugal', IE: 'Ireland',
  DK: 'Denmark', NO: 'Norway', BE: 'Belgium', CA: 'Canada', TR: 'Türkiye',
  KZ: 'Kazakhstan', GE: 'Georgia', AM: 'Armenia', RS: 'Serbia', SK: 'Slovakia',
  SI: 'Slovenia', HR: 'Croatia', HU: 'Hungary', GR: 'Greece', UA: 'Ukraine',
  JP: 'Japan', SG: 'Singapore', HK: 'Hong Kong', KR: 'South Korea', AU: 'Australia',
  IN: 'India', BR: 'Brazil', AR: 'Argentina', MX: 'Mexico', ZA: 'South Africa',
  AE: 'UAE', IL: 'Israel', IS: 'Iceland', LU: 'Luxembourg', MT: 'Malta',
  CY: 'Cyprus', AL: 'Albania', TH: 'Thailand', TW: 'Taiwan', VN: 'Vietnam',
  MY: 'Malaysia', CR: 'Costa Rica', RU: 'Russia', CL: 'Chile', BY: 'Belarus',
  BA: 'Bosnia and Herzegovina', MK: 'North Macedonia', ME: 'Montenegro', AZ: 'Azerbaijan',
  UZ: 'Uzbekistan', PH: 'Philippines', NZ: 'New Zealand', ID: 'Indonesia', US: 'United States',
};

export function countryName(cc: string, lang: 'ru' | 'en' = 'ru'): string {
  const code = String(cc || '').toUpperCase();
  if (lang === 'ru' && COUNTRY_NAMES_RU[code]) return COUNTRY_NAMES_RU[code];
  if (lang === 'en' && COUNTRY_NAMES_EN[code]) return COUNTRY_NAMES_EN[code];
  try {
    const display = new Intl.DisplayNames([lang], { type: 'region' });
    const name = display.of(code);
    // Hermes on some devices lacks DisplayNames locale data and returns the code.
    return name && name !== code ? name : (lang === 'en' ? COUNTRY_NAMES_EN[code] : COUNTRY_NAMES_RU[code]) ?? code;
  } catch {
    return (lang === 'en' ? COUNTRY_NAMES_EN[code] : COUNTRY_NAMES_RU[code]) ?? code;
  }
}

export function daysLeft(iso: string): number {
  const end = new Date(iso).getTime();
  if (!Number.isFinite(end)) return 0;
  return Math.max(0, Math.min(7, Math.ceil((end - Date.now()) / 86_400_000)));
}

export function formatRetry(seconds: number, lang: 'ru' | 'en' = 'ru'): string {
  const safe = Math.max(0, Math.ceil(seconds));
  const totalMinutes = Math.ceil(safe / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (lang === 'en') return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
  if (hours > 0) return `${hours} ч ${minutes} мин`;
  return `${minutes} мин`;
}

export function formatDate(iso: string, lang: 'ru' | 'en' = 'ru'): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString(lang === 'en' ? 'en-US' : 'ru-RU', { day: 'numeric', month: 'long' });
}
