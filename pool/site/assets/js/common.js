/**
 * Shared core for every page: helpers, the repo-link placeholder, the
 * theme/language chrome, the countdown to the next refresh and lazy access
 * to the published bundles. Page scripts (app/bench/check/files) register
 * through PP.onReady and only touch their own DOM.
 */
window.PP = (() => {
  const $ = (id) => document.getElementById(id);
  const { t, countryName } = window.I18N;
  const { flagSvg } = window.Flags;

  const CADENCE_MS = 15 * 60 * 1000;

  const fmt = (n) => (n === null || n === undefined ? '—' : n.toLocaleString('en-US'));
  const ago = (ts) => {
    const s = Math.max(0, Math.floor((Date.now() - ts) / 1000));
    const loc = window.I18N.lang === 'ru' ? 'ru' : 'en';
    if (s < 60) return loc === 'ru' ? 'только что' : 'just now';
    const v = Math.floor(s / 60);
    if (v < 60) return loc === 'ru' ? `${v} мин назад` : `${v} min ago`;
    const h = Math.floor(v / 60);
    if (h < 24) return loc === 'ru' ? `${h} ч назад` : `${h} h ago`;
    return loc === 'ru' ? `${Math.floor(h / 24)} дн назад` : `${Math.floor(h / 24)} d ago`;
  };
  const escapeHtml = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  /* ------------- clipboard + toast ------------- */
  function legacyCopy(text) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy');
    } catch {
      /* denied */
    }
    ta.remove();
  }

  function copy(text, message) {
    const done = () => message && toast(message, 'ok');
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done, () => {
        legacyCopy(text);
        done();
      });
    } else {
      legacyCopy(text);
      done();
    }
  }

  let toastTimer = null;
  function toast(msg, kind = 'ok') {
    const el = $('toast');
    if (!el) return;
    el.textContent = (kind === 'ok' ? '✓ ' : '') + msg;
    el.dataset.kind = kind;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      el.hidden = true;
    }, 2200);
  }

  function download(name, text) {
    const blob = new Blob([text], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /* ------------- repository links ------------- */
  const repoBase = () => `https://github.com/${document.body.dataset.repo || 'OWNER/REPO'}`;
  const repoUrl = (p) => `${repoBase()}/blob/main/${p}`;
  function patchRepoLinks() {
    const repo = document.body.dataset.repo;
    if (!repo) return;
    for (const c of document.querySelectorAll('.code')) {
      c.dataset.copy = c.dataset.copy.replace('OWNER/REPO', repo);
      c.querySelector('span')?.remove();
      c.textContent = c.dataset.copy;
    }
    for (const a of document.querySelectorAll('[data-repo-link]')) {
      a.href = a.classList.contains('btn') ? `https://github.com/${repo}` : `https://github.com/${repo}/data`;
      a.target = '_blank';
      a.rel = 'noopener';
    }
    for (const li of document.querySelectorAll('#filelist-protos a, #filelist-countries a')) {
      li.href = li.href.replace('OWNER/REPO', repo);
    }
  }

  /* ------------- bundles (lazy, memoised) ------------- */
  let metaPromise = null;
  let poolPromise = null;
  const loadMeta = () =>
    (metaPromise ??= fetch('data/meta.json').then((r) => {
      if (!r.ok) throw new Error(`meta.json: HTTP ${r.status}`);
      return r.json();
    }));
  const loadPool = () =>
    (poolPromise ??= fetch('data/proxies.json').then((r) => {
      if (!r.ok) throw new Error(`proxies.json: HTTP ${r.status}`);
      return r.json();
    }));

  /** Show a message instead of the page when a bundle fails to load. */
  function showLoadError(e) {
    const box = $('load-error');
    if (box) {
      box.hidden = false;
      box.textContent = `${t('error.data')}: ${e.message}`;
    }
    const sk = $('skeleton');
    if (sk) sk.hidden = true;
  }

  /* ------------- page chrome present everywhere ------------- */
  function wireChrome() {
    patchRepoLinks();

    for (const c of document.querySelectorAll('.code'))
      c.addEventListener('click', () => copy(c.dataset.copy, t('toast.copiedCommand')));

    $('theme-toggle')?.addEventListener('click', () => {
      const dark = document.documentElement.dataset.theme === 'dark';
      document.documentElement.dataset.theme = dark ? 'light' : 'dark';
      try {
        window.localStorage.setItem('theme', dark ? 'light' : 'dark');
      } catch {
        /* private mode */
      }
    });

    // the footer timestamp and the hero countdown read the same bundle
    loadMeta()
      .then((m) => {
        const fm = $('footer-meta');
        if (fm) {
          fm.textContent = t('footer.generated', {
            ISO: String(m.generatedIso).replace('T', ' ').slice(0, 16),
            RUN: m.runId ? `#${m.runId}` : 'local',
          });
        }
        startCountdown(m);
      })
      .catch((e) => showLoadError(e));
  }

  function startCountdown(meta) {
    const live = $('hero-live-text');
    if (!live || !meta.generatedIso) return;
    const tick = () => {
      const measured = Date.parse(meta.generatedIso);
      const left = CADENCE_MS - ((Date.now() - measured) % CADENCE_MS);
      const mm = String(Math.floor(left / 60000)).padStart(2, '0');
      const ss = String(Math.floor((left % 60000) / 1000)).padStart(2, '0');
      const text = `${t('hero.live', { MM: mm, SS: ss, AGO: ago(measured) })}`;
      if (live.textContent !== text) live.textContent = text;
      const due = left < 60000;
      const cls = due ? 'hero__live is-due' : 'hero__live';
      const p = live.parentElement;
      if (p && p.className !== cls) p.className = cls;
    };
    tick();
    setInterval(tick, 1000);
  }

  /* ------------- language changes ------------- */
  const langHooks = [];
  function onLanguageChange(fn) {
    langHooks.push(fn);
  }
  function initLanguageHooks() {
    document.addEventListener('languagechange', () => {
      for (const fn of langHooks) {
        try {
          fn();
        } catch (e) {
          console.error('languagechange hook failed', e);
        }
      }
    });
  }

  const ready = [];
  return {
    $,
    t,
    fmt,
    ago,
    escapeHtml,
    copy,
    toast,
    download,
    repoBase,
    repoUrl,
    patchRepoLinks,
    loadMeta,
    loadPool,
    showLoadError,
    onLanguageChange,
    countryName,
    flagSvg,
    /** a page script registers its initialiser here */
    onReady(fn) {
      ready.push(fn);
    },
    boot() {
      wireChrome();
      initLanguageHooks();
      for (const fn of ready) fn();
    },
  };
})();
