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

export function countryName(cc: string): string {
  const code = String(cc || '').toUpperCase();
  if (COUNTRY_NAMES_RU[code]) return COUNTRY_NAMES_RU[code];
  try {
    const display = new Intl.DisplayNames(['ru'], { type: 'region' });
    const name = display.of(code);
    // Hermes on some devices lacks DisplayNames locale data and returns the code.
    return name && name !== code ? name : code;
  } catch {
    return code;
  }
}

export function daysLeft(iso: string): number {
  const end = new Date(iso).getTime();
  if (!Number.isFinite(end)) return 0;
  return Math.max(0, Math.ceil((end - Date.now()) / 86_400_000));
}

export function formatRetry(seconds: number): string {
  const safe = Math.max(0, Math.ceil(seconds));
  const totalMinutes = Math.ceil(safe / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `${hours} ч ${minutes} мин`;
  return `${minutes} мин`;
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long' });
}
