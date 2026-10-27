(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const COUNTRIES = [
    { code: 'auto', ru: 'Авто', en: 'Auto', auto: true },
    { code: 'nl', ru: 'Нидерланды', en: 'Netherlands', flag: 'nl' },
    { code: 'us', ru: 'США', en: 'United States', flag: 'us' },
    { code: 'de', ru: 'Германия', en: 'Germany', flag: 'de' },
    { code: 'fi', ru: 'Финляндия', en: 'Finland', flag: 'fi' },
    { code: 'gb', ru: 'Великобритания', en: 'United Kingdom', flag: 'gb' },
    { code: 'fr', ru: 'Франция', en: 'France', flag: 'fr' },
    { code: 'se', ru: 'Швеция', en: 'Sweden', flag: 'se' },
    { code: 'pl', ru: 'Польша', en: 'Poland', flag: 'pl' },
    { code: 'jp', ru: 'Япония', en: 'Japan', flag: 'jp' },
    { code: 'ca', ru: 'Канада', en: 'Canada', flag: 'ca' },
  ];

  const PROXIES = [
    { flag: 'fi', address: '56.228.13.15:18146', proto: 'HTTP', ms: 90 },
    { flag: 'de', address: '18.157.159.247:9595', proto: 'HTTP', ms: 94 },
    { flag: 'se', address: '56.228.13.15:5584', proto: 'SOCKS5', ms: 102 },
    { flag: 'nl', address: '193.29.139.168:8080', proto: 'HTTP', ms: 78 },
    { flag: 'gb', address: '51.68.207.44:3128', proto: 'HTTP', ms: 111 },
    { flag: 'pl', address: '185.125.230.11:1080', proto: 'SOCKS5', ms: 126 },
  ];

  const I18N = {
    ru: {
      'chrome.proto': 'Интерактивный макет',
      'chrome.noteAK': 'Соединение',
      'chrome.noteA': 'Один жест. Поле реагирует.',
      'chrome.noteBK': 'Маршрут',
      'chrome.noteB': 'Без счётчиков. Только страны.',
      'chrome.demo': 'Смоделировать обрыв шлюза',
      'chrome.foot': 'Интерактивный макет · 390 × 844 · RU / EN',
      'chrome.hint': 'Нажмите на круг, откройте страны, смените язык в профиле.',
      'aria.profile': 'Профиль',
      'aria.close': 'Закрыть',
      'aria.connect': 'Подключить VPN',
      'aria.disconnect': 'Отключить VPN',
      'aria.copy': 'Скопировать ссылку',
      'vpn.kicker': 'Децентрализованный VPN',
      'vpn.change': 'Сменить страну',
      'vpn.key': 'Ключ',
      'vpn.open': 'Открыть',
      'tabs.vpn': 'VPN',
      'tabs.proxy': 'Прокси',
      'tabs.profile': 'Профиль',
      'proxy.kicker': 'Прокси-база',
      'proxy.title': 'Прокси',
      'proxy.lead': 'Живые адреса из открытого каталога.',
      'proxy.all': 'Все',
      'countries.kicker': 'Страны',
      'countries.title': 'Куда подключиться',
      'countries.search': 'Поиск страны',
      'countries.auto': 'Авто',
      'countries.autoSub': 'Лучший доступный узел',
      'key.kicker': 'Доступ',
      'key.title': 'Ключ',
      'key.days': 'Бессрочно',
      'key.until': 'Без срока действия',
      'key.week': 'Бесплатно',
      'key.done': 'Готово — к подключению',
      'key.fine': 'Ключ не истекает. Узлы сторонние — не используйте для чувствительных данных.',
      'profile.kicker': 'Приложение',
      'profile.title': 'Профиль',
      'profile.lead': 'Локальный профиль. Без аккаунта и облака.',
      'profile.guest': 'Гость',
      'profile.meta': 'без аккаунта · без истории',
      'profile.key': 'КЛЮЧ',
      'profile.language': 'Язык',
      'profile.languageHint': 'интерфейс и страны',
      'profile.app': 'Приложение',
      'profile.how': 'Как это работает',
      'profile.method': 'Методика проверки',
      'profile.status': 'Статус сервиса',
      'profile.diag': 'Диагностика',
      'profile.fine': 'Публичные сторонние узлы. PoolNet не оператор и не даёт гарантий.',
      'state.idle.status': 'Ключ активен',
      'state.idle.title': 'Свобода без границ.',
      'state.idle.sub': 'Один жест — и интернет снова без границ.',
      'state.idle.label': 'Подключить',
      'state.idle.hint': 'нажмите, чтобы включить',
      'state.connecting.status': 'Подключение',
      'state.connecting.title': 'Подключаемся…',
      'state.connecting.sub': 'Устанавливаем соединение…',
      'state.connecting.label': 'Подключение',
      'state.connecting.hint': 'пожалуйста, подождите',
      'state.connected.status': 'Подключено',
      'state.connected.title': 'Вы подключены',
      'state.connected.sub': 'Трафик идёт через {country}. Если узел упадёт, переключимся сами.',
      'state.connected.autoSub': 'Трафик идёт через лучший доступный узел. Если он упадёт, переключимся сами.',
      'state.connected.label': 'Подключено',
      'state.connected.hint': 'нажмите, чтобы отключить',
      'state.switching.status': 'Переключение',
      'state.switching.title': 'Меняем шлюз…',
      'state.switching.sub': 'Текущий шлюз не отвечает. Ищем следующий.',
      'state.switching.label': 'Переключение',
      'state.switching.hint': 'без вашего участия',
      'toast.connecting': 'Поднимаем туннель…',
      'toast.connected': 'Подключение установлено',
      'toast.disconnected': 'VPN отключён',
      'toast.switched': 'Шлюз переключён: {country}',
      'toast.copy': 'Ссылка скопирована',
      'toast.notConnected': 'Сначала подключитесь',
      'toast.demo': 'Имитируем обрыв шлюза',
      'toast.mock': 'Это интерактивный макет — раздел не подключён.',
      'empty.countries': 'Ничего не найдено.',
      'demo.disabled': 'Сначала подключитесь',
    },
    en: {
      'chrome.proto': 'Interactive prototype',
      'chrome.noteAK': 'Connection',
      'chrome.noteA': 'One gesture. The field responds.',
      'chrome.noteBK': 'Routing',
      'chrome.noteB': 'No counters. Just countries.',
      'chrome.demo': 'Simulate a gateway drop',
      'chrome.foot': 'Interactive prototype · 390 × 844 · RU / EN',
      'chrome.hint': 'Tap the orb, open countries, switch language in Profile.',
      'aria.profile': 'Profile',
      'aria.close': 'Close',
      'aria.connect': 'Connect VPN',
      'aria.disconnect': 'Disconnect VPN',
      'aria.copy': 'Copy link',
      'vpn.kicker': 'Decentralized VPN',
      'vpn.change': 'Change country',
      'vpn.key': 'Key',
      'vpn.open': 'Open',
      'tabs.vpn': 'VPN',
      'tabs.proxy': 'Proxy',
      'tabs.profile': 'Profile',
      'proxy.kicker': 'Proxy directory',
      'proxy.title': 'Proxy',
      'proxy.lead': 'Live addresses from the public directory.',
      'proxy.all': 'All',
      'countries.kicker': 'Countries',
      'countries.title': 'Where to connect',
      'countries.search': 'Search countries',
      'countries.auto': 'Auto',
      'countries.autoSub': 'Best available node',
      'key.kicker': 'Access',
      'key.title': 'Key',
      'key.days': 'Unlimited',
      'key.until': 'No expiry',
      'key.week': 'Free',
      'key.done': 'Done — back to connecting',
      'key.fine': 'This key does not expire. Nodes are third-party — do not use them for sensitive data.',
      'profile.kicker': 'App',
      'profile.title': 'Profile',
      'profile.lead': 'A local profile. No account, no cloud.',
      'profile.guest': 'Guest',
      'profile.meta': 'no account · no history',
      'profile.key': 'KEY',
      'profile.language': 'Language',
      'profile.languageHint': 'interface and countries',
      'profile.app': 'App',
      'profile.how': 'How it works',
      'profile.method': 'Verification method',
      'profile.status': 'Service status',
      'profile.diag': 'Diagnostics',
      'profile.fine': 'Public third-party nodes. PoolNet is not the operator and makes no guarantees.',
      'state.idle.status': 'Key active',
      'state.idle.title': 'Freedom without borders.',
      'state.idle.sub': 'One tap — and the internet is open again.',
      'state.idle.label': 'Connect',
      'state.idle.hint': 'tap to turn on',
      'state.connecting.status': 'Connecting',
      'state.connecting.title': 'Connecting…',
      'state.connecting.sub': 'Establishing connection…',
      'state.connecting.label': 'Connecting',
      'state.connecting.hint': 'please wait',
      'state.connected.status': 'Connected',
      'state.connected.title': 'You are connected',
      'state.connected.sub': 'Traffic goes through {country}. If the node drops, we switch automatically.',
      'state.connected.autoSub': 'Traffic goes through the best available node. If it drops, we switch automatically.',
      'state.connected.label': 'Connected',
      'state.connected.hint': 'tap to disconnect',
      'state.switching.status': 'Switching',
      'state.switching.title': 'Switching gateway…',
      'state.switching.sub': 'The current gateway is not responding. Finding the next one.',
      'state.switching.label': 'Switching',
      'state.switching.hint': 'without your input',
      'toast.connecting': 'Bringing up the tunnel…',
      'toast.connected': 'Connection established',
      'toast.disconnected': 'VPN disconnected',
      'toast.switched': 'Gateway switched: {country}',
      'toast.copy': 'Link copied',
      'toast.notConnected': 'Connect first',
      'toast.demo': 'Simulating a gateway drop',
      'toast.mock': 'This is an interactive prototype — the section is not wired.',
      'empty.countries': 'Nothing found.',
      'demo.disabled': 'Connect first',
    },
  };

  const state = {
    lang: 'ru',
    screen: 'vpn',
    phase: 'idle',
    country: 'nl',
    lastFocus: null,
    connectTimer: 0,
    switchTimer: 0,
    toastTimer: 0,
  };

  const root = document.documentElement;
  const app = $('#app');
  const sheetLayer = $('#sheetLayer');
  const countriesSheet = $('#countriesSheet');
  const keySheet = $('#keySheet');
  const countryList = $('#countryList');
  const search = $('#countrySearch');
  const toast = $('#toast');

  function t(key, vars) {
    let text = (I18N[state.lang] && I18N[state.lang][key]) || (I18N.ru[key] || key);
    if (vars) {
      Object.entries(vars).forEach(([name, value]) => {
        text = text.replaceAll(`{${name}}`, String(value));
      });
    }
    return text;
  }

  function country(code) {
    return COUNTRIES.find((item) => item.code === code) || COUNTRIES[1];
  }

  function countryName(code = state.country) {
    const item = country(code);
    return item[state.lang] || item.ru;
  }

  function flag(code) {
    return `<img src="./assets/flags/${code}.png" alt="" loading="lazy">`;
  }

  function applyStatic() {
    root.lang = state.lang;
    $$('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $$('[data-i18n-aria]').forEach((el) => { el.setAttribute('aria-label', t(el.dataset.i18nAria)); });
    $$('[data-i18n-placeholder]').forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    $$('.lang-option').forEach((el) => {
      const active = el.dataset.lang === state.lang;
      el.classList.toggle('is-active', active);
      el.setAttribute('aria-pressed', String(active));
    });
    document.title = state.lang === 'ru'
      ? 'PoolNet Mobile — интерактивный макет'
      : 'PoolNet Mobile — interactive prototype';
  }

  function renderCountryList() {
    const query = search.value.trim().toLowerCase();
    const auto = COUNTRIES.filter((item) => item.auto);
    const countries = COUNTRIES
      .filter((item) => !item.auto)
      .sort((a, b) => a[state.lang].localeCompare(b[state.lang], state.lang === 'ru' ? 'ru' : 'en'));
    const rows = [...auto, ...countries].filter((item) => {
      if (!query) return true;
      return `${item[state.lang]} ${item.ru} ${item.code}`.toLowerCase().includes(query);
    });
    if (!rows.length) {
      countryList.innerHTML = `<div class="empty">${t('empty.countries')}</div>`;
      return;
    }
    countryList.innerHTML = rows.map((item) => {
      const selected = state.country === item.code;
      const sub = item.auto ? `<small>${t('countries.autoSub')}</small>` : '';
      const visual = item.auto
        ? '<svg><use href="#ic-globe"/></svg>'
        : flag(item.flag);
      return `<button class="country-row${selected ? ' is-selected' : ''}" type="button" data-code="${item.code}" aria-pressed="${selected}">
        <span class="flag-box">${visual}</span>
        <span class="country-name">${item[state.lang]}${sub}</span>
        <svg class="country-check"><use href="#ic-check"/></svg>
      </button>`;
    }).join('');
  }

  function renderProxyList() {
    $('#proxyList').innerHTML = PROXIES.map((item) => `
      <div class="proxy-row">
        <span class="proxy-flag">${flag(item.flag)}</span>
        <span class="proxy-main">
          <span class="proxy-addr">${item.address}</span>
          <span class="proxy-meta">${item.proto} · ${item.ms} ms</span>
        </span>
        <button class="icon-btn proxy-copy" type="button" aria-label="${t('aria.copy')}" data-proxy="${item.address}">
          <svg><use href="#ic-copy"/></svg>
        </button>
      </div>`).join('');
  }

  function render() {
    const phase = state.phase;
    const item = country();
    const isAuto = item.auto;
    const base = `state.${phase}`;

    app.dataset.phase = phase;
    $('#statusPill').textContent = t(`${base}.status`);
    $('#heroTitle').textContent = t(`${base}.title`);
    $('#heroSub').textContent = phase === 'connected' && isAuto
      ? t('state.connected.autoSub')
      : t(`${base}.sub`, { country: countryName() });
    $('#orbLabel').textContent = t(`${base}.label`);
    $('#orbHint').textContent = t(`${base}.hint`);
    $('#orbIcon use').setAttribute('href', phase === 'connected' ? '#ic-shield' : '#ic-power');
    $('#orb').setAttribute('aria-label', phase === 'connected' ? t('aria.disconnect') : t('aria.connect'));
    $('#orb').setAttribute('aria-pressed', String(phase === 'connected'));
    $('#routeName').textContent = countryName();
    $('#routeFlag').hidden = isAuto;
    $('#routeGlobe').hidden = !isAuto;
    $('#routeFlag').src = isAuto ? './assets/flags/nl.png' : `./assets/flags/${item.flag}.png`;
    $('#routeFlag').alt = '';
    $('#demoDrop').disabled = phase !== 'connected';
    $('#demoDrop').title = phase === 'connected' ? '' : t('demo.disabled');
    $('#keyUnit').textContent = t('key.days');
    $('#keyUntil').textContent = t('key.until');
    renderCountryList();
  }

  function setScreen(name) {
    state.screen = name;
    $$('.screen').forEach((screen) => {
      const active = screen.id === `screen-${name}`;
      screen.classList.toggle('is-active', active);
      screen.hidden = !active;
    });
    $$('.tab').forEach((tab) => {
      const active = tab.dataset.tab === name;
      tab.classList.toggle('is-active', active);
      tab.setAttribute('aria-selected', String(active));
    });
    closeSheet(false);
  }

  function showToast(message) {
    window.clearTimeout(state.toastTimer);
    toast.textContent = message;
    toast.classList.add('is-visible');
    state.toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 2400);
  }

  function openSheet(name) {
    state.lastFocus = document.activeElement;
    sheetLayer.hidden = false;
    countriesSheet.hidden = name !== 'countries';
    keySheet.hidden = name !== 'key';
    if (name === 'countries') {
      search.value = '';
      renderCountryList();
      window.setTimeout(() => $('.close-sheet', countriesSheet)?.focus(), 40);
    } else {
      window.setTimeout(() => $('.close-sheet', keySheet)?.focus(), 40);
    }
  }

  function closeSheet(restoreFocus = true) {
    if (sheetLayer.hidden) return;
    sheetLayer.hidden = true;
    countriesSheet.hidden = true;
    keySheet.hidden = true;
    if (restoreFocus && state.lastFocus && typeof state.lastFocus.focus === 'function') {
      state.lastFocus.focus();
    }
    state.lastFocus = null;
  }

  function toggleConnection() {
    if (state.phase === 'connecting' || state.phase === 'switching') return;
    window.clearTimeout(state.connectTimer);
    if (state.phase === 'connected') {
      state.phase = 'idle';
      render();
      return;
    }
    state.phase = 'connecting';
    render();
    state.connectTimer = window.setTimeout(() => {
      state.phase = 'connected';
      if (country().auto) state.country = 'nl';
      render();
    }, 1500);
  }

  function selectCountry(code) {
    const previous = state.country;
    state.country = code === 'auto' && state.phase === 'connected' ? 'nl' : code;
    closeSheet();
    if (state.phase === 'connected' && previous !== state.country) {
      window.clearTimeout(state.switchTimer);
      state.phase = 'switching';
      render();
      state.switchTimer = window.setTimeout(() => {
        state.phase = 'connected';
        render();
        showToast(t('toast.switched', { country: countryName() }));
      }, 900);
    } else {
      render();
    }
  }

  function simulateDrop() {
    if (state.phase !== 'connected') {
      showToast(t('toast.notConnected'));
      return;
    }
    window.clearTimeout(state.switchTimer);
    state.phase = 'switching';
    render();
    showToast(t('toast.demo'));
    state.switchTimer = window.setTimeout(() => {
      const order = ['nl', 'us', 'de', 'fi', 'gb'];
      const index = order.indexOf(state.country);
      state.country = order[(index + 1 + order.length) % order.length];
      state.phase = 'connected';
      render();
      showToast(t('toast.switched', { country: countryName() }));
    }, 1000);
  }

  function setLanguage(lang) {
    if (!I18N[lang]) return;
    state.lang = lang;
    window.clearTimeout(state.toastTimer);
    toast.classList.remove('is-visible');
    try { localStorage.setItem('poolnet.mockup.lang', lang); } catch (_) { /* noop */ }
    applyStatic();
    render();
    renderProxyList();
  }

  async function copyLink() {
    const value = 'https://poolnet.online/sub/free-demo';
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const temp = document.createElement('textarea');
      temp.value = value;
      temp.style.position = 'fixed';
      temp.style.opacity = '0';
      document.body.appendChild(temp);
      temp.select();
      try { document.execCommand('copy'); } catch (__) { /* noop */ }
      temp.remove();
    }
    showToast(t('toast.copy'));
  }

  // Events
  const orbButton = $('#orb');
  orbButton.addEventListener('click', () => {
    const burst = $('.orb-burst', orbButton);
    if (burst) {
      burst.classList.remove('run');
      void burst.offsetWidth;
      burst.classList.add('run');
    }
    toggleConnection();
  });
  orbButton.addEventListener('pointermove', (event) => {
    if (event.pointerType === 'touch') return;
    const rect = orbButton.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;
    orbButton.style.setProperty('--gx', `${Math.max(0, Math.min(100, x))}%`);
    orbButton.style.setProperty('--gy', `${Math.max(0, Math.min(100, y))}%`);
  });
  orbButton.addEventListener('pointerleave', () => {
    orbButton.style.setProperty('--gx', '50%');
    orbButton.style.setProperty('--gy', '26%');
  });
  $('#brandHome').addEventListener('click', () => setScreen('vpn'));
  $('#openProfile').addEventListener('click', () => setScreen('profile'));
  $$('.tab').forEach((tab) => tab.addEventListener('click', () => setScreen(tab.dataset.tab)));
  $('#openCountries').addEventListener('click', () => openSheet('countries'));
  $('#openKey').addEventListener('click', () => openSheet('key'));
  $('#sheetScrim').addEventListener('click', () => closeSheet());
  $$('.close-sheet').forEach((button) => button.addEventListener('click', () => closeSheet()));
  $('#closeKeyDone').addEventListener('click', () => closeSheet());
  $('#copyKey').addEventListener('click', copyLink);
  $('#demoDrop').addEventListener('click', simulateDrop);
  $('#proxyList').addEventListener('click', (event) => {
    const button = event.target.closest('[data-proxy]');
    if (!button) return;
    const value = button.dataset.proxy;
    navigator.clipboard?.writeText(value).catch(() => undefined);
    showToast(t('toast.copy'));
  });
  $('.lang-switch').addEventListener('click', (event) => {
    const button = event.target.closest('[data-lang]');
    if (button) setLanguage(button.dataset.lang);
  });
  $$('.menu-row').forEach((button) => button.addEventListener('click', () => showToast(t('toast.mock'))));
  search.addEventListener('input', renderCountryList);
  countryList.addEventListener('click', (event) => {
    const row = event.target.closest('[data-code]');
    if (row) selectCountry(row.dataset.code);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeSheet();
  });
  $$('.seg').forEach((button) => button.addEventListener('click', () => {
    $$('.seg').forEach((seg) => seg.classList.toggle('is-active', seg === button));
  }));

  // Initial state
  try {
    const saved = localStorage.getItem('poolnet.mockup.lang');
    if (saved === 'ru' || saved === 'en') state.lang = saved;
  } catch (_) { /* noop */ }
  applyStatic();
  renderProxyList();
  render();
  const clock = () => {
    const now = new Date();
    $('#clock').textContent = now.toLocaleTimeString(state.lang === 'en' ? 'en-GB' : 'ru-RU', { hour: '2-digit', minute: '2-digit' });
  };
  clock();
  window.setInterval(clock, 30000);
})();
