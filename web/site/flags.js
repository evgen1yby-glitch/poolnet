// Compact inline SVG flags, drawn at 20×14 and recognisable at that size:
// stripes where stripes do the work, dedicated marks for the rest.
// Anything missing falls back to the country code on a neutral plate.

const V = (d) => {
  const parts = d.split(':');
  return [parts[0], parts[1].split(',').map((c) => `#${c}`)];
};

// vertical / horizontal stripe flags
const STRIPES = {
  DE: V('v:000000,DD0000,FFCE00'),
  NL: V('h:AE1C28,FFFFFF,21468B'),
  RU: V('h:FFFFFF,0039A6,D52B1E'),
  FR: V('v:0055A4,FFFFFF,EF4135'),
  IT: V('v:009246,FFFFFF,CE2B37'),
  IE: V('v:169B62,FFFFFF,169B62'),
  BE: V('v:000000,FDDA24,EF3340'),
  RO: V('v:002B7F,FCD116,CE1126'),
  BG: V('h:FFFFFF,00966E,D62612'),
  HU: V('h:CE2939,FFFFFF,477050'),
  EE: V('h:0072CE,000000,FFFFFF'),
  LU: V('h:ED2939,FFFFFF,00A3E0'),
  AT: V('h:EF3340,FFFFFF,EF3340'),
  CO: V('h:FCD116,003893,CE1126'),
  EC: V('h:FFDD00,0047AB,ED1C24'),
  VE: V('h:FFCC00,00247D,CF142B,CC0000'),
  BO: V('h:D52B1E,F9E300,007A33,DD0000'),
  AR: V('v:74ACDF,FFFFFF,74ACDF'),
  BR: V('h:009B3A,FEDD00,002776'),
  CL: V('h:FFFFFF,0039A6,D52B1E'),
  PE: V('v:D91023,FFFFFF,D91023'),
  UY: V('h:FFFFFF,0038A8,FFFFFF,0038A8,FFFFFF'),
  PY: V('v:D52B1E,FFFFFF,0038A8,FFFFFF,D52B1E'),
  MX: V('v:006341,FFFFFF,CE1126'),
  NG: V('v:008751,FFFFFF,008751'),
  KE: V('h:000000,BB0000,006600,FFFFFF,BB0000,000000'),
  ZA: V('h:007A4D,FCDD09,FFFFFF,001489,DE3831,FFFFFF,000000,FFB612,007A4D'),
  EG: V('h:CE1126,FFFFFF,000000'),
  MA: V('h:C1272D,006233'),
  SA: V('h:006C35,FFFFFF,006C35'),
  AE: V('v:00732F,FFFFFF,000000'),
  IN: V('h:FF9933,FFFFFF,138808'),
  BD: V('h:006A4D,F42A41,006A4D,FFFFFF'),
  PK: V('h:FFFFFF,01411C,01411C,FFFFFF'),
  IR: V('h:239F40,FFFFFF,DA0000'),
  TR: V('h:E30A17,FFFFFF,E30A17'),
  AM: V('h:D90012,0033A0,F2A800'),
  GE: V('h:FFFFFF,FF0000,FF0000,000000,FF0000,FFFFFF'),
  TH: V('h:A51931,F4F5F8,2D2A4A,F4F5F8,A51931'),
  VN: V('h:DA251D,FFFF00'),
  ID: V('h:CE1126,FFFFFF,CE1126'),
  MY: V('v:CC0000,FFFFFF,CC0000,FFFFFF,010066,FFFFFF,010066'),
  SG: V('h:EF3340,FFFFFF,EF3340'),
  PH: V('v:0038A8,FFFFFF,CE1126,FFFFFF,0038A8'),
  KH: V('v:032EA1,FFFFFF,E00025,FFFFFF,032EA1'),
  LA: V('v:D52B1E,002D86,FFFFFF,002D86,D52B1E'),
  MM: V('h:FECB00,24B04B,EA2839,FFFFFF,EA2839,24B04B,FECB00'),
  NP: V('h:DC143C,003893,FFFFFF,003893,DC143C'),
  LK: V('v:FFB300,8D153A,FFB500,00534E,FFB500,8D153A,FFB300'),
  KZ: V('h:00AFCA,F1B400,00AFCA'),
  BY: V('h:FFFFFF,CE1720,FFFFFF,007C30,FFFFFF,CE1720,FFFFFF'),
  LT: V('h:FDB913,006A44,CE1126'),
  LV: V('h:9E3039,FFFFFF,9E3039'),
  MD: V('v:00319C,FCD116,CC092F'),
  RS: V('h:C6363C,0C4076,FFFFFF,0C4076,C6363C'),
  HR: V('h:FF0000,FFFFFF,171796,FFFFFF,FF0000'),
  SI: V('h:FFFFFF,005DA4,FFFFFF,ED1C24,FFFFFF,005DA4,FFFFFF'),
  SK: V('h:FFFFFF,0B4EA2,EE1C25,FFFFFF'),
  SE: V('v:006AA7,FFCD00,006AA7'),
  FI: V('v:FFFFFF,003580,FFFFFF'),
  NO: V('v:BA0C2F,FFFFFF,00205B,FFFFFF,BA0C2F'),
  DK: V('v:C60C30,FFFFFF,C60C30'),
  IS: V('v:02529C,FFFFFF,02529C,FFFFFF,DC1E35'),
  UA: V('h:0057B7,FFD700,0057B7'),
  PL: V('h:FFFFFF,DC143C,FFFFFF'),
  GR: V('v:0D5EAF,FFFFFF,0D5EAF,FFFFFF,0D5EAF,FFFFFF,0D5EAF'),
  ES: V('h:AA151B,F1BF00,AA151B'),
  JM: V('h:000000,009B3A,FEDD00'),
  CY: V('h:FFFFFF,FFFFFF,FFFFFF'),
  PT: V('v:006600,FF0000,006600'),
};

// flags whose identity is a mark, not stripes
const MARKS = {
  US: '<rect width="20" height="14" fill="#FFFFFF" rx="1.6"/><g fill="#B22234"><rect width="20" height="1.08"/><rect y="2.16" width="20" height="1.08"/><rect y="4.32" width="20" height="1.08"/><rect y="6.48" width="20" height="1.08"/><rect y="8.64" width="20" height="1.08"/><rect y="10.8" width="20" height="1.08"/><rect y="12.96" width="20" height="1.08"/></g><rect width="8.8" height="7.56" fill="#3C3B6E"/>',
  JP: '<rect width="20" height="14" fill="#FFFFFF" rx="1.6"/><circle cx="10" cy="7" r="4.3" fill="#BC002D"/>',
  KR: '<rect width="20" height="14" fill="#FFFFFF" rx="1.6"/><path d="M10 7a3.7 3.7 0 0 1 0-3.7 3.7 3.7 0 0 1 0 7.4z" fill="#CD2E3A"/><path d="M10 3.3a3.7 3.7 0 0 0 0 7.4 3.7 3.7 0 0 0 0-7.4z" fill="#0047A0" transform="rotate(180 10 7)"/>',
  TW: '<rect width="20" height="14" fill="#FE0000" rx="1.6"/><rect width="10" height="7" fill="#000095"/><circle cx="5" cy="3.5" r="1.9" fill="#FFFFFF"/><circle cx="6.6" cy="5.6" r="0.7" fill="#FFFFFF"/><circle cx="3.4" cy="5.6" r="0.7" fill="#FFFFFF"/><circle cx="6" cy="1.5" r="0.7" fill="#FFFFFF"/><circle cx="4" cy="1.5" r="0.7" fill="#FFFFFF"/>',
  CA: '<rect width="20" height="14" fill="#FFFFFF" rx="1.6"/><rect x="4.6" width="3" height="14" fill="#D80621"/><rect y="5.5" width="20" height="3" fill="#D80621"/><path d="M10 2.1l.62 1.9h2l-1.6 1.18.6 1.9-1.62-1.18-1.62 1.18.6-1.9L7.38 4h2z" fill="#D80621"/>',
  CH: '<rect width="20" height="14" fill="#D52B1E" rx="1.6"/><path d="M10 3.6v6.8M6.6 7h6.8" stroke="#FFFFFF" stroke-width="2.3" stroke-linecap="round"/>',
  GB: '<rect width="20" height="14" fill="#012169" rx="1.6"/><path d="M0 0l20 14M20 0L0 14" stroke="#FFFFFF" stroke-width="2.8"/><path d="M0 0l20 14M20 0L0 14" stroke="#C8102E" stroke-width="1.3"/><path d="M10 0v14M0 7h20" stroke="#FFFFFF" stroke-width="4.4"/><path d="M10 0v14M0 7h20" stroke="#C8102E" stroke-width="2.3"/>',
  DO: '<rect width="20" height="14" fill="#FFFFFF" rx="1.6"/><path d="M0 0l20 14M20 0L0 14" stroke="#CE1126" stroke-width="2.4"/><path d="M10 0v14M0 7h20" stroke="#002D62" stroke-width="3.2"/>',
  AU: '<rect width="20" height="14" fill="#00247D" rx="1.6"/><g fill="#FFFFFF"><rect width="8.6" height="1.1"/><rect y="2.2" width="8.6" height="1.1"/><rect y="4.4" width="8.6" height="1.1"/><rect y="6.6" width="8.6" height="1.1"/><rect y="8.8" width="8.6" height="1.1"/><rect y="11" width="8.6" height="1.1"/><rect width="1.1" height="6.5"/><rect x="2.2" width="1.1" height="6.5"/><rect x="4.4" width="1.1" height="6.5"/></g><rect width="8.6" height="6.5" fill="#00247D"/><path d="M0 0l8.6 6.5M8.6 0L0 6.5" stroke="#FFFFFF" stroke-width="1.1"/><path d="M4.3 0v6.5M0 3.25h8.6" stroke="#CF142B" stroke-width="0.7"/><g fill="#FFFFFF"><circle cx="15.2" cy="4.2" r="1.5"/><circle cx="16.6" cy="9.2" r="1.5"/><circle cx="12.2" cy="10.2" r="1.5"/><circle cx="13.2" cy="6.2" r="1.1"/></g>',
  NZ: '<rect width="20" height="14" fill="#00247D" rx="1.6"/><g fill="#FFFFFF"><rect width="8" height="1"/><rect y="2" width="8" height="1"/><rect y="4" width="8" height="1"/><rect y="6" width="8" height="1"/><rect y="8" width="8" height="1"/><rect y="10" width="8" height="1"/><rect y="12" width="8" height="1"/><rect width="1" height="6.5"/><rect x="2" width="1" height="6.5"/><rect x="4" width="1" height="6.5"/></g><rect width="8" height="6.5" fill="#00247D"/><path d="M0 0l8 6.5M8 0L0 6.5" stroke="#FFFFFF" stroke-width="1"/><path d="M4 0v6.5M0 3.25h8" stroke="#CF142B" stroke-width="0.6"/><g stroke="#CC142B" stroke-width="0.5" fill="none"><circle cx="15" cy="4" r="1.4"/><circle cx="16.8" cy="9" r="1.4"/><circle cx="12.6" cy="10" r="1.4"/></g>',
};

const GLOBE =
  '<rect width="20" height="14" fill="#E2E8F0" rx="1.6"/><circle cx="10" cy="7" r="4.4" fill="none" stroke="#64748B" stroke-width="1"/><path d="M5.8 7h8.4M10 2.6c2.2 2 2.2 6.8 0 8.8M10 2.6c-2.2 2-2.2 6.8 0 8.8" stroke="#64748B" stroke-width="0.7" fill="none"/>';

const svg = (body, cls) =>
  `<svg viewBox="0 0 20 14" width="20" height="14" class="flag${cls ? ` ${cls}` : ''}" aria-hidden="true">${body}</svg>`;

function flagSvg(cc, cls) {
  if (!cc) return svg(GLOBE, cls);
  const mark = MARKS[cc];
  if (mark) return svg(mark, cls);
  const stripes = STRIPES[cc];
  if (stripes) {
    const [dir, colors] = stripes;
    const n = colors.length;
    const rects =
      dir === 'h'
        ? colors
            .map(
              (c, i) =>
                `<rect x="0" y="${((i * 14) / n).toFixed(2)}" width="20" height="${(14 / n).toFixed(2)}" fill="${c}"/>`,
            )
            .join('')
        : colors
            .map(
              (c, i) =>
                `<rect x="${((i * 20) / n).toFixed(2)}" y="0" width="${(20 / n).toFixed(2)}" height="14" fill="${c}"/>`,
            )
            .join('');
    return svg(`<rect width="20" height="14" fill="#CBD5E1" rx="1.6"/>${rects}`, cls);
  }
  return svg(
    `<rect width="20" height="14" fill="#E2E8F0" rx="1.6"/><text x="10" y="9.8" text-anchor="middle" font-size="7" font-family="ui-monospace,monospace" fill="#64748B">${cc.slice(0, 2)}</text>`,
    cls,
  );
}

const COUNTRY_NAMES_RU = {
  NL: "Нидерланды",   DE: "Германия",   FI: "Финляндия",   GB: "Великобритания",   FR: "Франция",
  SE: "Швеция",   PL: "Польша",   CZ: "Чехия",   AT: "Австрия",   CH: "Швейцария",
  LT: "Литва",   LV: "Латвия",   EE: "Эстония",   MD: "Молдова",   RO: "Румыния",
  BG: "Болгария",   IT: "Италия",   ES: "Испания",   PT: "Португалия",   IE: "Ирландия",
  DK: "Дания",   NO: "Норвегия",   BE: "Бельгия",   CA: "Канада",   TR: "Турция",
  KZ: "Казахстан",   GE: "Грузия",   AM: "Армения",   RS: "Сербия",   SK: "Словакия",
  SI: "Словения",   HR: "Хорватия",   HU: "Венгрия",   GR: "Греция",   UA: "Украина",
  JP: "Япония",   SG: "Сингапур",   HK: "Гонконг",   KR: "Корея",   AU: "Австралия",
  IN: "Индия",   BR: "Бразилия",   AR: "Аргентина",   MX: "Мексика",   ZA: "ЮАР",
  AE: "ОАЭ",   IL: "Израиль",   IS: "Исландия",   LU: "Люксембург",   MT: "Мальта",
  CY: "Кипр",   AL: "Албания",   TH: "Таиланд",   TW: "Тайвань",   VN: "Вьетнам",
  MY: "Малайзия",   CR: "Коста-Рика",   RU: "Россия",   CL: "Чили",   BY: "Беларусь",
  BA: "Босния",   MK: "Македония",   ME: "Черногория",   AZ: "Азербайджан",   UZ: "Узбекистан",
  PH: "Филиппины",   NZ: "Новая Зеландия",   ID: "Индонезия",   US: "США",
};

const COUNTRY_NAMES = {
  DE: 'Germany',
  NL: 'Netherlands',
  US: 'United States',
  RU: 'Russia',
  GB: 'United Kingdom',
  FR: 'France',
  VN: 'Vietnam',
  BR: 'Brazil',
  ID: 'Indonesia',
  IN: 'India',
  UA: 'Ukraine',
  CN: 'China',
  TR: 'Turkey',
  IR: 'Iran',
  PL: 'Poland',
  TH: 'Thailand',
  BD: 'Bangladesh',
  PK: 'Pakistan',
  HK: 'Hong Kong',
  SG: 'Singapore',
  JP: 'Japan',
  KR: 'South Korea',
  MY: 'Malaysia',
  PH: 'Philippines',
  MX: 'Mexico',
  AR: 'Argentina',
  CO: 'Colombia',
  CL: 'Chile',
  CA: 'Canada',
  KZ: 'Kazakhstan',
  GE: 'Georgia',
  AM: 'Armenia',
  AZ: 'Azerbaijan',
  BY: 'Belarus',
  LT: 'Lithuania',
  LV: 'Latvia',
  EE: 'Estonia',
  MD: 'Moldova',
  RS: 'Serbia',
  BG: 'Bulgaria',
  GR: 'Greece',
  CZ: 'Czechia',
  RO: 'Romania',
  IT: 'Italy',
  ES: 'Spain',
  AT: 'Austria',
  CH: 'Switzerland',
  BE: 'Belgium',
  PT: 'Portugal',
  SE: 'Sweden',
  FI: 'Finland',
  NO: 'Norway',
  DK: 'Denmark',
  IE: 'Ireland',
  HU: 'Hungary',
  SK: 'Slovakia',
  SI: 'Slovenia',
  HR: 'Croatia',
  LU: 'Luxembourg',
  AU: 'Australia',
  NZ: 'New Zealand',
  TW: 'Taiwan',
  EG: 'Egypt',
  ZA: 'South Africa',
  NG: 'Nigeria',
  KE: 'Kenya',
  MA: 'Morocco',
  SA: 'Saudi Arabia',
  AE: 'United Arab Emirates',
  IL: 'Israel',
  IQ: 'Iraq',
  UZ: 'Uzbekistan',
  KH: 'Cambodia',
  LA: 'Laos',
  MM: 'Myanmar',
  NP: 'Nepal',
  LK: 'Sri Lanka',
  EC: 'Ecuador',
  VE: 'Venezuela',
  PE: 'Peru',
  UY: 'Uruguay',
  BO: 'Bolivia',
  PY: 'Paraguay',
  JM: 'Jamaica',
  DO: 'Dominican Republic',
  IS: 'Iceland',
  PR: 'Puerto Rico',
  ZW: 'Zimbabwe',
  TZ: 'Tanzania',
  GH: 'Ghana',
  UG: 'Uganda',
  SY: 'Syria',
  GT: 'Guatemala',
  HN: 'Honduras',
  CY: 'Cyprus',
  BW: 'Botswana',
  OM: 'Oman',
  QA: 'Qatar',
  MN: 'Mongolia',
  SN: 'Senegal',
  ET: 'Ethiopia',
  AO: 'Angola',
  MU: 'Mauritius',
  BB: 'Barbados',
  BS: 'Bahamas',
  CR: 'Costa Rica',
  NI: 'Nicaragua',
  PA: 'Panama',
  SV: 'El Salvador',
  KG: 'Kyrgyzstan',
  TJ: 'Tajikistan',
  TM: 'Turkmenistan',
  AL: 'Albania',
  MK: 'North Macedonia',
  ME: 'Montenegro',
  BA: 'Bosnia and Herzegovina',
  MT: 'Malta',
};

const countryName = (cc) => {
  const table = (document.documentElement.lang || "ru").startsWith("en")
    ? COUNTRY_NAMES
    : COUNTRY_NAMES_RU;
  return table[cc] || COUNTRY_NAMES[cc] || cc;
};

const codeForName = (value) => {
  const needle = String(value || "").trim().toLowerCase();
  if (!needle) return null;
  for (const table of [COUNTRY_NAMES, COUNTRY_NAMES_RU]) {
    for (const [cc, name] of Object.entries(table)) {
      if (String(name).toLowerCase() === needle) return cc;
    }
  }
  return null;
};

// The merged site marks every country element with `data-cc`; mounting once
// after parse puts the flag in front of the label. Idempotent so a page can
// re-run it after injecting rows.
function mount(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-cc]').forEach((node) => {
    if (node.dataset.flagMounted === '1') return;
    const cc = (node.dataset.cc || '').toUpperCase();
    if (!/^[A-Z]{2}$/.test(cc)) return;
    node.dataset.flagMounted = '1';
    node.classList.add('with-flag');
    node.insertAdjacentHTML('afterbegin', flagSvg(cc));
    if (!node.getAttribute('title')) node.setAttribute('title', countryName(cc));
    if (!node.getAttribute('aria-label')) node.setAttribute('aria-label', countryName(cc));
  });
}

function start() {
  mount(document);
  const lang = document.documentElement.lang || 'ru';
  document.documentElement.dataset.lang = lang;
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start);
} else {
  start();
}

window.Flags = { flagSvg, countryName, codeForName, mount };

