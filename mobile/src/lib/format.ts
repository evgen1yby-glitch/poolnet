export function countryName(cc: string): string {
  try {
    const display = new Intl.DisplayNames(['ru'], { type: 'region' });
    return display.of(cc.toUpperCase()) || cc;
  } catch {
    return cc;
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
