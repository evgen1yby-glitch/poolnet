// i18n: two languages, no dependencies. data-i18n="key" sets text,
// data-i18n-attr="attr:key" sets attributes. Preferences persist and the
// html lang attribute follows the active language.
(() => {
  const DICT = {
    en: {
      'meta.title': 'Proxy Pool — verified public proxies, updated every 15 minutes',
      'meta.title.index': 'Proxy Pool — verified public proxies, updated every 15 minutes',
      'meta.title.bench': 'The benchmark — Proxy Pool',
      'meta.title.check': 'Check a proxy — Proxy Pool',
      'meta.title.files': 'Files & API — Proxy Pool',
      'meta.description.index': 'A continuously updated pool of public proxies.',
      'meta.description.bench': "Every public proxy list measured by this pipeline's own checks.",
      'meta.description.check': 'Check any public proxy right now: verdict, latency and exit IP.',
      'meta.description.files': 'Plain files over HTTP: protocol lists, metadata, statistics, country shards.',
      'meta.description':
        'A continuously updated pool of public proxies: collected from published lists, verified end to end, enriched with anonymity grade, latency and country, republished every fifteen minutes.',

      'nav.pool': 'The pool',
      'nav.files': 'Files & API',

      'hero.live': 'next refresh in {MM}:{SS} · measured {AGO}',
      'hero.liveDue': 'refresh due · measured {AGO}',
      'hero.liveImminent': 'refresh imminent · measured {AGO}',
      'hero.title': 'Public proxies,<br />verified and measured.',
      'hero.lead':
        'Every entry below answered a full request through a real connection — never a bare port scan, never a claim.',
      'hero.foot':
        'Collected from published lists, graded for anonymity, re-checked continuously from disposable runners.',
      'hero.stat.alive': 'alive right now',
      'pool.summaryTruncated':
        'Showing the newest {SHOWN} of {NUM} alive proxies — median {MED} ms, p95 {P95} ms; the full list is in the data files.',
      'hero.stat.sources': 'lists answering, this cycle',
      'hero.stat.countries': 'countries',
      'hero.stat.latency': 'median latency',

      'comp.latency': 'Latency spread',
      'comp.grade': 'Anonymity grade',
      'comp.history': 'Pool size over time',
      'nav.benchmark': 'Benchmark',
      'bench.title': 'The benchmark',
      'bench.sub':
        'Every public list is measured by this pipeline, never by its own claims. Ranked by the share of entries that answered a full request, not by how many it publishes.',
      'bench.export': 'Export CSV',
      'bench.search': 'Filter sources',
      'bench.orderLive': 'Live rate',
      'bench.order': 'Order',
      'bench.colSource': 'Source',
      'bench.colLive': 'Live rate',
      'bench.colAlive': 'Alive',
      'bench.colCands': 'Checked',
      'bench.colLatency': 'Median',
      'bench.colElite': 'Elite',
      'bench.colStale': 'Stale',
      'bench.colTrend': 'Trend',
      'bench.update':
        'Live rate = share of the source\u2019s own entries that answered a full request this cycle. Trend = change since the previous cycle.',
      'bench.measured': 'Measured {TIME}, from {ALIVE} alive proxies across {SOURCES} sources.',
      'bench.none': 'No source matches this filter.',
      'tm.title': 'Pool history',
      'tm.oldest': 'oldest cycle',
      'tm.now': 'now',
      'tm.play': 'Play history',
      'tm.pause': 'Pause',
      'tm.reset': 'Back to now',
      'tm.mode': 'Cycle from {TIME}',
      'tm.playing': 'Playing',
      'tm.points': '{N} cycles recorded',
      'nav.check': 'Check a proxy',
      'check.title': 'Check any proxy, right now',
      'check.sub':
        'Paste an address and see what a full request through it returns to you — verdict, latency and the exit IP it leaves from.',
      'check.placeholder': '1.2.3.4:8080 or socks5://1.2.3.4:1080',
      'check.run': 'Check',
      'check.examples': 'Examples',
      'check.idle': 'Enter an address — the check runs through this project\u2019s own API.',
      'check.checkedAt': 'Checked',
      'filter.protocol': 'Protocol',
      'check.checking': 'Checking {ADDRESS}…',
      'check.note':
        'The check runs through this project\u2019s own API (the Cloudflare Worker), so it stays free and is rate-limited to keep it sane. Use it to sanity-check an address, not to hunt the pool.',
      'check.alive': 'alive',
      'check.dead': 'dead',
      'check.verdict': 'Verdict',
      'check.error.title': 'Could not check this proxy',
      'check.error.net': 'The checker service did not respond. Try again in a moment.',
      'check.error.noapi':
        'This page has no checker API configured: set body[data-api] to your Worker URL to turn this on.',
      'drawer.protocol': 'Protocol',
      'check.error.input': 'That does not look like an address. Use ip:port.',
      'check.error.rate': 'The free checker is rate-limited right now. Try again in a minute.',
      'check.tryAgain': 'Try again',
      'check.example': 'Try an example',
      'spark.empty': 'collecting — {N} of 96 cycles',
      'spark.points': '{N} cycles',
      'spark.range': '{MIN}–{MAX} proxies',

      'pool.title': 'The pool',
      'pool.summary':
        '{NUM} proxies answered a full request through a real connection — median latency {MED} ms, p95 {P95} ms.',
      'action.copyView': 'Copy view',
      'action.copyViewTitle': 'Copy the first 10 of the current view',
      'action.export': 'Export .txt',
      'action.exportTitle': 'Download the current view as .txt',
      'action.compact': 'Compact',
      'action.compactTitle': 'Toggle row density',
      'action.reset': 'Reset filters',
      'action.github': 'GitHub',
      'action.source': 'Source',

      'search.placeholder': 'Search by address, country or network  (press /)',
      'filter.country': 'Country',
      'filter.all': 'All',
      'filter.show': 'Show',

      'th.proxy': 'Proxy',
      'th.protocol': 'Protocol',
      'th.grade': 'Grade',
      'th.latency': 'Latency',
      'th.uptime': 'Uptime 7d',
      'th.country': 'Country',

      'grade.elite': 'Elite',
      'grade.anonymous': 'Anonymous',
      'grade.transparent': 'Transparent',
      'grade.unknown': 'Ungraded',

      'empty.title': 'No proxies match these filters.',
      'pager.prev': 'Previous',
      'pager.next': 'Next',
      'pager.none': 'nothing matches',
      'pager.range': '{FROM}–{TO} of {TOTAL}',

      'files.title': 'Files & API',
      'files.sub': 'Plain files over HTTP. No keys, no rate limits worth worrying about.',
      'files.protos': 'Protocol lists',
      'files.protosText': 'Working proxies, one per line, with the scheme prefix.',
      'files.metadata': 'Full metadata',
      'files.metadataText': 'Every proxy with grade, latency, uptime windows, location and network.',
      'files.sources': 'Which sources deliver',
      'files.sourcesText': 'Working proxies per published list, last cycle.',
      'files.stats': 'Statistics',
      'files.statsText': 'Counts by protocol, grade and country, plus latency percentiles.',
      'files.countries': 'Country shards',
      'files.countriesText': 'Proxies by country, for geo-targeted work.',
      'files.copyPrefix': 'curl',
      'files.allCountries': 'all {COUNT} countries',

      'notice.title': 'Handle every entry as hostile',
      'notice.body':
        'These proxies are run by third parties — most of them services nobody meant to expose. Never send credentials, personal data or payments through a free proxy. Some entries terminate TLS themselves; those carry a “TLS” warning in the pool and tls_mitm: true in the JSON. Entries die without warning; check one immediately before you rely on it.',

      'drawer.label': 'Proxy details',
      'drawer.copyLine': 'Copy proxy line',
      'drawer.copyJson': 'Copy JSON record',
      'drawer.copyCurl': 'Copy curl test',
      'drawer.grade': 'Grade',
      'drawer.latency': 'Latency',
      'drawer.exit': 'Exit IP',
      'drawer.location': 'Location',
      'drawer.tls': 'TLS',
      'drawer.tlsBad': 'terminated by the proxy — treat as hostile',
      'drawer.tlsOk': 'clean handshake',
      'drawer.lastCheck': 'Last check',
      'drawer.sources': 'Sources seen',
      'drawer.uptime24': 'Uptime 24h',
      'drawer.curlscheme': 'curl -x {SCHEME}://{HOST}:{PORT} https://api.ipify.org',

      'hist.measured': '{N} measured',
      'hist.peak': 'peak {RANGE}',
      'comp.hint': '{MED} ms median · {P95} ms p95',

      'toast.copied': 'Copied {TEXT}',
      'row.exitShort': 'no exit check',
      'row.exitUnknown': 'answered, but never confirmed it reached the target - possible captive portal',
      'drawer.exitUnverified': 'unverified exit',
      'error.data': 'Could not load the pool data',
      'toast.copiedLine': 'Proxy line copied',
      'toast.copiedJson': 'JSON record copied',
      'toast.copiedCurl': 'curl test copied',
      'toast.copiedCommand': 'Command copied',
      'toast.copyFailed': 'Copy failed — select the text manually',
      'toast.exported': 'Exported {N} proxies',
      'toast.copyFailShort': 'Copy failed',

      'a11y.theme': 'Toggle dark mode',
      'a11y.search': 'Search proxies',
      'a11y.protocol': 'Protocol',
      'a11y.grade': 'Anonymity grade',
      'a11y.check': 'Proxy address to check',
      'a11y.keys': 'Keyboard shortcuts',
      'a11y.close': 'Close',
      'a11y.language': 'Language',

      'keys.search': 'search',
      'keys.close': 'close',
      'keys.pages': 'pages',

      'footer.generated': 'Generated {ISO} UTC · run {RUN}',

      'grade.short.elite': 'elite',
      'grade.short.anonymous': 'anonymous',
      'grade.short.transparent': 'transparent',
      'grade.short.unknown': 'ungraded',
    },

    ru: {
      'meta.title': 'Proxy Pool — проверенные публичные прокси, обновление каждые 15 минут',
      'meta.title.index': 'Proxy Pool — проверенные публичные прокси, обновление каждые 15 минут',
      'meta.title.bench': 'Бенчмарк — Proxy Pool',
      'meta.title.check': 'Проверка прокси — Proxy Pool',
      'meta.title.files': 'Файлы и API — Proxy Pool',
      'meta.description.index':
        'Постоянно обновляемый пул публичных прокси: собрано из опубликованных списков, проверено сквозными запросами, обогащено грейдом анонимности, задержкой и страной, переиздаётся каждые пятнадцать минут.',
      'meta.description.bench': 'Каждый список прокси измерен собственными проверками этого пайплайна.',
      'meta.description.check': 'Проверьте любой публичный прокси прямо сейчас: вердикт, задержка и IP выхода.',
      'meta.description.files': 'Обычные файлы по HTTP: списки протоколов, метаданные, статистика, шарды по странам.',
      'meta.description':
        'Постоянно обновляемый пул публичных прокси: собрано из опубликованных списков, проверено сквозными запросами, обогащено грейдом анонимности, задержкой и страной, переиздаётся каждые пятнадцать минут.',

      'nav.pool': 'Пул',
      'nav.files': 'Файлы и API',

      'hero.live': 'следующее обновление через {MM}:{SS} · измерено {AGO}',
      'hero.liveDue': 'обновление пора · измерено {AGO}',
      'hero.liveImminent': 'обновление вот-вот · измерено {AGO}',
      'hero.title': 'Публичные прокси,<br />проверенные и измеренные.',
      'hero.lead':
        'Каждая запись ниже ответила полным запросом через настоящее соединение — не «голым» сканом портов и не обещанием.',
      'hero.foot':
        'Собрано из опубликованных списков, оценено по анонимности, перепроверяется непрерывно с одноразовых раннеров.',
      'hero.stat.alive': 'живых прямо сейчас',
      'pool.summaryTruncated':
        'Показаны {SHOWN} новейших из {NUM} живых прокси — медиана {MED} мс, p95 {P95} мс; полный список — в файлах данных.',
      'hero.stat.sources': 'списков ответили за цикл',
      'hero.stat.countries': 'стран',
      'hero.stat.latency': 'медианная задержка',

      'comp.latency': 'Распределение задержки',
      'comp.grade': 'Грейд анонимности',
      'comp.history': 'Размер пула во времени',
      'nav.benchmark': 'Бенчмарк',
      'bench.title': 'Бенчмарк',
      'bench.sub':
        'Каждый публичный список измеряется этим пайплайном, а не его собственными заявлениями. Рейтинг по доле записей, ответивших полным запросом, а не по количеству публикуемых строк.',
      'bench.export': 'Экспорт CSV',
      'bench.search': 'Фильтр источников',
      'bench.orderLive': 'Доля живых',
      'bench.order': 'Порядок',
      'bench.colSource': 'Источник',
      'bench.colLive': 'Доля живых',
      'bench.colAlive': 'Живых',
      'bench.colCands': 'Проверено',
      'bench.colLatency': 'Медиана',
      'bench.colElite': 'Elite',
      'bench.colStale': 'Устарел',
      'bench.colTrend': 'Тренд',
      'bench.update':
        'Доля живых — какой процент собственных записей источника ответил полным запросом в этом цикле. Тренд — изменение с прошлого цикла.',
      'bench.measured': 'Измерено {TIME}: {ALIVE} живых прокси из {SOURCES} источников.',
      'bench.none': 'Ни один источник не подходит под фильтр.',
      'tm.title': 'История пула',
      'tm.oldest': 'самый старый цикл',
      'tm.now': 'сейчас',
      'tm.play': 'Проиграть историю',
      'tm.reset': 'Вернуться к текущему',
      'tm.pause': 'Пауза',
      'tm.mode': 'Цикл от {TIME}',
      'tm.playing': 'Воспроизведение',
      'tm.points': '{N} циклов в истории',
      'nav.check': 'Проверить прокси',
      'check.title': 'Проверьте любой прокси прямо сейчас',
      'check.sub': 'Вставьте адрес и посмотрите, что вернёт полный запрос через него — вердикт, задержку и IP выхода.',
      'check.placeholder': '1.2.3.4:8080 или socks5://1.2.3.4:1080',
      'check.run': 'Проверить',
      'check.examples': 'Примеры',
      'check.idle': 'Вставьте адрес — проверка идёт через API этого проекта.',
      'check.checkedAt': 'Проверено',
      'filter.protocol': 'Протокол',
      'check.checking': 'Проверяем {ADDRESS}…',
      'check.note':
        'Проверка идёт через API этого проекта, поэтому остаётся бесплатной и ограничена по частоте. Это быстрая sanity-проверка адреса, а не охота по пулу.',
      'check.alive': 'жив',
      'check.dead': 'мёртв',
      'check.verdict': 'Вердикт',
      'check.error.title': 'Не удалось проверить прокси',
      'check.error.net': 'Сервис проверки не ответил. Попробуйте через минуту.',
      'check.error.noapi': 'На странице не настроен API проверки: укажите URL вашего Worker в body[data-api].',
      'drawer.protocol': 'Протокол',
      'check.error.input': 'Это не похоже на адрес. Используйте ip:port.',
      'check.error.rate': 'Бесплатный сервис проверки ограничил частоту. Попробуйте через минуту.',
      'check.tryAgain': 'Повторить',
      'check.example': 'Попробовать пример',
      'spark.empty': 'собираем данные — {N} из 96 циклов',
      'spark.points': '{N} циклов',
      'spark.range': '{MIN}–{MAX} прокси',

      'pool.title': 'Пул',
      'pool.summary':
        '{NUM} прокси ответили полным запросом через настоящее соединение — медиана {MED} мс, p95 {P95} мс.',
      'action.copyView': 'Копировать вид',
      'action.copyViewTitle': 'Скопировать первые 10 из текущей выборки',
      'action.export': 'Экспорт .txt',
      'action.exportTitle': 'Скачать текущую выборку в .txt',
      'action.compact': 'Компактно',
      'action.compactTitle': 'Плотность строк',
      'action.reset': 'Сбросить фильтры',
      'action.github': 'GitHub',
      'action.source': 'Исходники',

      'search.placeholder': 'Поиск по адресу, стране или сети  (нажмите /)',
      'filter.country': 'Страна',
      'filter.all': 'Все',
      'filter.show': 'Показывать',

      'th.proxy': 'Прокси',
      'th.protocol': 'Протокол',
      'th.grade': 'Грейд',
      'th.latency': 'Задержка',
      'th.uptime': 'Uptime 7д',
      'th.country': 'Страна',

      'grade.elite': 'Elite',
      'grade.anonymous': 'Anonymous',
      'grade.transparent': 'Transparent',
      'grade.unknown': 'Без грейда',

      'empty.title': 'Под фильтры ничего не подходит.',
      'pager.prev': 'Назад',
      'pager.next': 'Вперёд',
      'pager.none': 'нет совпадений',
      'pager.range': '{FROM}–{TO} из {TOTAL}',

      'files.title': 'Файлы и API',
      'files.sub': 'Обычные файлы по HTTP. Без ключей и без rate limit, о которых стоит думать.',
      'files.protos': 'Списки протоколов',
      'files.protosText': 'Рабочие прокси, по одному в строке, с префиксом схемы.',
      'files.metadata': 'Полные метаданные',
      'files.metadataText': 'Каждый прокси с грейдом, задержкой, окнами uptime, гео и сетью.',
      'files.sources': 'Какие источники дают',
      'files.sourcesText': 'Рабочих прокси на каждый опубликованный список, последний цикл.',
      'files.stats': 'Статистика',
      'files.statsText': 'Счётчики по протоколам, грейдам и странам плюс процентили задержки.',
      'files.countries': 'Шарды по странам',
      'files.countriesText': 'Прокси по странам для гео-направленной работы.',
      'files.copyPrefix': 'curl',
      'files.allCountries': 'все {COUNT} стран',

      'notice.title': 'Относитесь к каждой записи как к враждебной',
      'notice.body':
        'Эти прокси управляются третьими сторонами — большинство из них сервисы, которые никто не собирался открывать. Не передавайте через бесплатный прокси учётные данные, персональные данные и платежи. Некоторые прокси сами терминируют TLS — они помечены предупреждением «TLS» в пуле и tls_mitm: true в JSON. Записи умирают без предупреждения: проверяйте прокси непосредственно перед тем, как положиться на него.',

      'drawer.label': 'Детали прокси',
      'drawer.copyLine': 'Копировать строку прокси',
      'drawer.copyJson': 'Копировать JSON-запись',
      'drawer.copyCurl': 'Копировать curl-тест',
      'drawer.grade': 'Грейд',
      'drawer.latency': 'Задержка',
      'drawer.exit': 'Exit IP',
      'drawer.location': 'Локация',
      'drawer.tls': 'TLS',
      'drawer.tlsBad': 'терминируется прокси — считайте враждебным',
      'drawer.tlsOk': 'чистое рукопожатие',
      'drawer.lastCheck': 'Последняя проверка',
      'drawer.sources': 'Виден в источниках',
      'drawer.uptime24': 'Аптайм 24ч',
      'drawer.curlscheme': 'curl -x {SCHEME}://{HOST}:{PORT} https://api.ipify.org',

      'hist.measured': '{N} измерено',
      'hist.peak': 'пик {RANGE}',
      'comp.hint': 'медиана {MED} мс · p95 {P95} мс',

      'toast.copied': 'Скопировано {TEXT}',
      'row.exitShort': 'выход не проверен',
      'row.exitUnknown': 'ответил, но не подтвердил связь с целью - возможен captive portal',
      'drawer.exitUnverified': 'выход не подтверждён',
      'error.data': 'Не удалось загрузить данные пула',
      'toast.copiedLine': 'Строка прокси скопирована',
      'toast.copiedJson': 'JSON-запись скопирована',
      'toast.copiedCurl': 'curl-тест скопирован',
      'toast.copiedCommand': 'Команда скопирована',
      'toast.copyFailed': 'Не удалось скопировать — выделите текст вручную',
      'toast.exported': 'Экспортировано {N} прокси',
      'toast.copyFailShort': 'Не удалось скопировать',

      'a11y.theme': 'Переключить тёмную тему',
      'a11y.search': 'Поиск прокси',
      'a11y.protocol': 'Протокол',
      'a11y.grade': 'Грейд анонимности',
      'a11y.check': 'Адрес прокси для проверки',
      'a11y.keys': 'Горячие клавиши',
      'a11y.close': 'Закрыть',
      'a11y.language': 'Язык',

      'keys.search': 'поиск',
      'keys.close': 'закрыть',
      'keys.pages': 'страницы',

      'footer.generated': 'Сгенерировано {ISO} UTC · прогон {RUN}',

      'grade.short.elite': 'elite',
      'grade.short.anonymous': 'anonymous',
      'grade.short.transparent': 'transparent',
      'grade.short.unknown': 'без грейда',
    },
  };

  const STORE_KEY = 'lang';
  let current = 'en';

  const t = (key, vars) => {
    const dict = DICT[current] || DICT.en;
    const str = dict[key] ?? DICT.en[key] ?? key;
    if (!vars) return str;
    // single pass with delimited names: sequential replaceAll would let
    // short names like TO corrupt longer ones like TOTAL
    return str.replace(/\{(\w+)\}/g, (m, name) => (vars[name] === undefined ? m : String(vars[name])));
  };

  function apply(root = document) {
    for (const el of root.querySelectorAll('[data-i18n]')) {
      el.innerHTML = t(el.dataset.i18n);
    }
    for (const el of root.querySelectorAll('[data-i18n-attr]')) {
      for (const pair of el.dataset.i18nAttr.split(',')) {
        const [attr, key] = pair.split(':').map((s) => s.trim());
        if (attr) el.setAttribute(attr, t(key));
      }
    }
    document.documentElement.lang = current;
  }

  function set(lang) {
    if (!DICT[lang]) return;
    current = lang;
    try {
      window.localStorage.setItem(STORE_KEY, lang);
    } catch {
      /* private mode */
    }
    for (const b of document.querySelectorAll('.lang__btn')) {
      const on = b.dataset.lang === lang;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-pressed', String(on));
    }
    apply();
    document.dispatchEvent(new CustomEvent('languagechange', { detail: { lang } }));
  }

  // initial language: stored choice, else the browser's preference
  let initial = 'en';
  try {
    initial = window.localStorage.getItem(STORE_KEY) || (navigator.language || 'en').slice(0, 2);
  } catch {
    initial = (navigator.language || 'en').slice(0, 2);
  }
  if (!DICT[initial]) initial = 'en';

  document.addEventListener('DOMContentLoaded', () => {
    for (const b of document.querySelectorAll('.lang__btn')) {
      b.addEventListener('click', () => set(b.dataset.lang));
    }
    set(initial);
  });

  // country names in Russian for the top markets; English otherwise
  const COUNTRY_RU = {
    RU: 'Россия',
    US: 'США',
    DE: 'Германия',
    NL: 'Нидерланды',
    FR: 'Франция',
    GB: 'Великобритания',
    VN: 'Вьетнам',
    BR: 'Бразилия',
    ID: 'Индонезия',
    IN: 'Индия',
    UA: 'Украина',
    CN: 'Китай',
    TR: 'Турция',
    IR: 'Иран',
    PL: 'Польша',
    TH: 'Таиланд',
    BD: 'Бангладеш',
    PK: 'Пакистан',
    HK: 'Гонконг',
    SG: 'Сингапур',
    JP: 'Япония',
    KR: 'Южная Корея',
    MY: 'Малайзия',
    PH: 'Филиппины',
    MX: 'Мексика',
    AR: 'Аргентина',
    CO: 'Колумбия',
    CL: 'Чили',
    CA: 'Канада',
    KZ: 'Казахстан',
    GE: 'Грузия',
    AM: 'Армения',
    AZ: 'Азербайджан',
    BY: 'Беларусь',
    LT: 'Литва',
    LV: 'Латвия',
    EE: 'Эстония',
    MD: 'Молдова',
    RS: 'Сербия',
    BG: 'Болгария',
    GR: 'Греция',
    CZ: 'Чехия',
    RO: 'Румыния',
    IT: 'Италия',
    ES: 'Испания',
    AT: 'Австрия',
    CH: 'Швейцария',
    BE: 'Бельгия',
    PT: 'Португалия',
    SE: 'Швеция',
    FI: 'Финляндия',
    NO: 'Норвегия',
    DK: 'Дания',
    IE: 'Ирландия',
    HU: 'Венгрия',
    SK: 'Словакия',
    SI: 'Словения',
    HR: 'Хорватия',
    LU: 'Люксембург',
    AU: 'Австралия',
    NZ: 'Новая Зеландия',
    TW: 'Тайвань',
    EG: 'Египет',
    ZA: 'ЮАР',
    NG: 'Нигерия',
    KE: 'Кения',
    MA: 'Марокко',
    SA: 'Саудовская Аравия',
    AE: 'ОАЭ',
    IL: 'Израиль',
    IQ: 'Ирак',
    UZ: 'Узбекистан',
    KH: 'Камбоджа',
    LA: 'Лаос',
    MM: 'Мьянма',
    NP: 'Непал',
    LK: 'Шри-Ланка',
    EC: 'Эквадор',
    VE: 'Венесуэла',
    PE: 'Перу',
    UY: 'Уругвай',
    BO: 'Боливия',
    PY: 'Парагвай',
    JM: 'Ямайка',
    DO: 'Доминикана',
    IS: 'Исландия',
    PR: 'Пуэрто-Рико',
    ZW: 'Зимбабве',
    TZ: 'Танзания',
    GH: 'Гана',
    UG: 'Уганда',
    SY: 'Сирия',
    GT: 'Гватемала',
    HN: 'Гондурас',
    CY: 'Кипр',
    BW: 'Ботсвана',
    OM: 'Оман',
    QA: 'Катар',
    MN: 'Монголия',
    SN: 'Сенегал',
    AL: 'Албания',
    MT: 'Мальта',
    BY2: 'Беларусь',
  };

  const countryName = (cc) => {
    if (!cc) return '';
    const en = (window.Flags && window.Flags.countryName(cc)) || cc;
    if (current === 'ru' && COUNTRY_RU[cc]) return COUNTRY_RU[cc];
    return en;
  };

  window.I18N = {
    t,
    set,
    get lang() {
      return current;
    },
    apply,
    countryName,
  };
})();
