/**
 * The main page: hero statistics, pool composition, the time machine and
 * the proxy table with its filters, pager and detail drawer. Everything
 * shared with the other pages lives in common.js (window.PP).
 */
(() => {
  const {
    $,
    t,
    fmt,
    escapeHtml,
    copy,
    download,
    toast,
    loadMeta,
    loadPool,
    showLoadError,
    onLanguageChange,
    flagSvg,
    countryName,
  } = window.PP;

  const state = {
    meta: null,
    pool: [],
    filtered: [],
    protos: new Set(['http', 'socks4', 'socks5']),
    grades: new Set(['elite', 'anonymous', 'transparent', 'unknown']),
    country: '',
    q: '',
    page: 1,
    perPage: 50,
    compact: false,
    sortKey: 'quality',
    sortDir: -1,
  };

  const GRADE_RANK = { elite: 0, anonymous: 1, unknown: 2, transparent: 3 };
  const PROTO_LABEL = { http: 'HTTP', socks4: 'SOCKS4', socks5: 'SOCKS5' };

  function quality(p) {
    const anon = p.grade === 'elite' ? 1 : p.grade === 'anonymous' ? 0.72 : p.grade === 'transparent' ? 0.3 : 0.45;
    const speed =
      p.latency === null || p.latency === undefined ? 0.25 : Math.min(1, Math.max(0.05, 1 - p.latency / 8000));
    const up = (p.uptime7d === null || p.uptime7d === undefined ? p.uptime24h : p.uptime7d) ?? 50;
    return anon * 0.45 + speed * 0.3 + (up / 100) * 0.25;
  }

  /* ---------------- hero + composition ---------------- */
  function renderHero() {
    const m = state.meta;
    $('stat-alive').textContent = fmt(m.total);
    $('stat-sources').textContent = `${m.sourcesOk}/${m.sourcesTotal}`;
    $('stat-countries').textContent = fmt(m.countries.length);
    $('stat-latency').textContent =
      m.medianLatencyMs !== null && m.medianLatencyMs !== undefined ? `${m.medianLatencyMs} ms` : '—';
    $('pool-summary').textContent = t(m.poolTruncated ? 'pool.summaryTruncated' : 'pool.summary', {
      NUM: fmt(m.poolTotal ?? m.total),
      SHOWN: fmt(m.total),
      MED: m.medianLatencyMs ?? '—',
      P95: m.p95LatencyMs ?? '—',
    });
  }

  const LAT_BUCKETS = [
    ['< 100', 0, 100],
    ['100–300', 100, 300],
    ['300–600', 300, 600],
    ['0.6–1.2s', 600, 1200],
    ['1.2–2.4s', 1200, 2400],
    ['2.4s+', 2400, Infinity],
  ];

  function renderComposition() {
    const counts = LAT_BUCKETS.map(() => 0);
    let measured = 0;
    for (const p of state.pool) {
      if (p.latency === null || p.latency === undefined) continue;
      measured++;
      const i = LAT_BUCKETS.findIndex(([, lo, hi]) => p.latency >= lo && p.latency < hi);
      if (i >= 0) counts[i]++;
    }
    const max = Math.max(...counts, 1);
    $('hist').innerHTML = LAT_BUCKETS.map(
      ([label, ,], i) => `<div class="hist__col" title="${label} — ${counts[i]}">
          <span class="hist__bar" style="--h:${Math.round((counts[i] / max) * 100)}%"></span>
          <span class="hist__x">${label}</span>
        </div>`,
    ).join('');
    $('hist-legend').innerHTML = `<span>${t('hist.measured', { N: fmt(measured) })}</span><span>${t('hist.peak', {
      RANGE: LAT_BUCKETS[counts.indexOf(max)]?.[0] ?? '—',
    })}</span>`;
    $('comp-latency-hint').textContent = t('comp.hint', {
      MED: state.meta.medianLatencyMs ?? '—',
      P95: state.meta.p95LatencyMs ?? '—',
    });

    const grades = [
      ['elite', state.meta.anonymity.elite || 0],
      ['anonymous', state.meta.anonymity.anonymous || 0],
      ['transparent', state.meta.anonymity.transparent || 0],
      ['unknown', state.meta.anonymity.unknown || 0],
    ];
    const total = grades.reduce((s, [, n]) => s + n, 0) || 1;
    $('segbar').innerHTML = grades
      .map(([g, n]) => `<span class="segbar__seg segbar__seg--${g}" style="width:${(n / total) * 100}%"></span>`)
      .join('');
    $('grade-legend').innerHTML = grades
      .map(([g, n]) => `<span><i class="dot dot--${g}"></i>${t(`grade.${g}`)} ${Math.round((n / total) * 100)}%</span>`)
      .join('');
  }

  function buildCountrySelect() {
    const sel = $('country');
    for (const c of state.meta.countries) {
      const o = document.createElement('option');
      o.value = c.cc;
      o.textContent = `${flagSvg(c.cc)} ${c.cc} · ${countryName(c.cc)} (${c.n})`;
      sel.appendChild(o);
    }
  }

  /* ---------------- filtering / sorting ---------------- */
  function applyFilters() {
    const q = state.q.trim().toLowerCase();
    state.filtered = state.pool.filter((p) => {
      if (!state.protos.has(p.protocol)) return false;
      if (!state.grades.has(p.grade)) return false;
      if (state.country && p.country !== state.country) return false;
      if (q) {
        const hay = `${p.host}:${p.port} ${p.country || ''} ${countryName(p.country) || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const cmp = {
      id: (a, b) => a.host.localeCompare(b.host) || a.port - b.port,
      protocol: (a, b) => a.protocol.localeCompare(b.protocol) || quality(b) - quality(a),
      grade: (a, b) => GRADE_RANK[a.grade] - GRADE_RANK[b.grade] || quality(b) - quality(a),
      latency: (a, b) => (a.latency ?? 9e9) - (b.latency ?? 9e9),
      country: (a, b) => (a.country || 'ZZ').localeCompare(b.country || 'ZZ') || quality(b) - quality(a),
      quality: (a, b) => quality(a) - quality(b),
    }[state.sortKey];
    state.filtered.sort((a, b) => cmp(a, b) * state.sortDir);
  }

  /* ---------------- rendering ---------------- */
  function render() {
    applyFilters();
    const totalPages = Math.max(1, Math.ceil(state.filtered.length / state.perPage));
    state.page = Math.min(state.page, totalPages);
    const start = (state.page - 1) * state.perPage;
    const rows = state.filtered.slice(start, start + state.perPage);
    $('empty').hidden = state.filtered.length > 0;
    $('tbody').innerHTML = rows
      .map((p, i) => {
        const lat = p.latency === null || p.latency === undefined ? '—' : `${p.latency} ms`;
        const latCls = p.latency === null ? '' : p.latency < 300 ? 'lat--fast' : p.latency < 1200 ? '' : 'lat--slow';
        const up = (p.uptime7d === null || p.uptime7d === undefined ? p.uptime24h : p.uptime7d) ?? null;
        const upLabel = up === null || up === undefined ? '—' : `${up}%`;
        return `<tr data-id="${p.id}" tabindex="0">
        <td class="rank">${start + i + 1}</td>
        <td data-cell="proxy">
          <span class="addr">${p.host}:${p.port}</span>
          ${p.mitm ? '<span class="chip-tls" title="TLS">TLS</span>' : ''}
          ${p.exitIp === null || p.exitIp === undefined ? `<span class="chip-exit" title="${t('row.exitUnknown')}">${t('row.exitShort')}</span>` : ''}
        </td>
        <td data-cell="proto"><span class="badge badge--${p.protocol}">${PROTO_LABEL[p.protocol]}</span></td>
        <td data-cell="grade"><span class="badge badge--${p.grade}">${p.grade}</span></td>
        <td data-cell="latency"><span class="lat ${latCls}">${lat}</span></td>
        <td data-cell="uptime">
          <span class="uptime">
            <span class="uptime__bar"><span class="uptime__fill" style="--w:${up || 0}%"></span></span>
            <span class="uptime__n">${upLabel}</span>
          </span>
        </td>
        <td data-cell="country"><span class="country">${flagSvg(p.country)}<span class="country__name">${countryName(p.country || '')}</span></span></td>
        <td data-cell="actions">
          <button type="button" class="row-action" data-copy="${p.id}" title="${p.id}" aria-label="Copy ${p.id}">
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="1.8"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></g></svg>
          </button>
        </td>
      </tr>`;
      })
      .join('');
    $('pager-info').textContent = state.filtered.length
      ? `${(start + 1).toLocaleString('en-US')}–${Math.min(start + state.perPage, state.filtered.length).toLocaleString('en-US')} of ${state.filtered.length.toLocaleString('en-US')}`
      : '';
    $('prev').disabled = state.page <= 1;
    $('next').disabled = state.page >= totalPages;
    $('skeleton').hidden = true;
    $('tbody').hidden = false;
    writeHash();
  }

  /* ---------------- drawer ---------------- */
  let current = null;
  function openDrawer(id, { silent = false } = {}) {
    const p = state.pool.find((x) => x.id === id);
    if (!p) return;
    current = p;
    $('drawer-title').textContent = `${p.host}:${p.port}`;
    $('drawer-proto').textContent = PROTO_LABEL[p.protocol];
    $('drawer-proto').className = `badge badge--${p.protocol}`;
    $('drawer-gauges').innerHTML = '';
    $('drawer-dl').innerHTML = [
      [t('drawer.grade'), p.grade],
      [t('drawer.latency'), p.latency === null || p.latency === undefined ? '—' : `${p.latency} ms`],
      [t('drawer.exit'), p.exitIp || `— ${t('drawer.exitUnverified')}`],
      [t('drawer.location'), countryName(p.country) || '—'],
      [t('drawer.tls'), p.mitm ? t('drawer.tlsBad') : t('drawer.tlsOk')],
      [t('drawer.sources'), p.sources ?? '—'],
      [t('drawer.lastCheck'), window.PP.ago(p.lastOk)],
      [t('drawer.uptime24'), p.uptime24h === null || p.uptime24h === undefined ? '—' : `${p.uptime24h}%`],
    ]
      .map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`)
      .join('');
    $('drawer').hidden = false;
    document.body.classList.add('drawer-open');
    if (!silent) $('drawer').querySelector('.drawer__panel')?.focus();
  }

  function closeDrawer() {
    $('drawer').hidden = true;
    document.body.classList.remove('drawer-open');
    current = null;
  }

  /* ---------------- url state ---------------- */
  function writeHash() {
    const p = new URLSearchParams();
    if (state.q) p.set('q', state.q);
    p.set('p', String(state.page));
    history.replaceState(null, '', `#${p.toString()}`);
  }

  function readHash() {
    const p = new URLSearchParams(location.hash.slice(1));
    state.q = p.get('q') || '';
    $('q').value = state.q;
    if (p.get('proto')) {
      state.protos = new Set(p.get('proto').split(',').filter(Boolean));
      for (const b of document.querySelectorAll('#proto-chips .chip'))
        b.classList.toggle('is-on', state.protos.has(b.dataset.proto));
    }
    if (p.get('grade')) {
      state.grades = new Set(p.get('grade').split(',').filter(Boolean));
      for (const b of document.querySelectorAll('#grade-chips .chip'))
        b.classList.toggle('is-on', state.grades.has(b.dataset.grade));
    }
    state.country = p.get('cc') || '';
    if (state.country) $('country').value = state.country;
    if (p.get('sort')) {
      const sortKeys = ['id', 'protocol', 'grade', 'latency', 'country', 'quality'];
      state.sortKey = sortKeys.includes(p.get('sort')) ? p.get('sort') : 'quality';
      state.sortDir = Number(p.get('dir') || -1);
      for (const b of document.querySelectorAll('.sortbtn')) b.removeAttribute('data-dir');
      const btn = document.querySelector(`.sortbtn[data-sort="${state.sortKey}"]`);
      if (btn) btn.dataset.dir = state.sortDir === 1 ? 'asc' : 'desc';
    }
    if (p.get('n')) {
      const n = Math.floor(Number(p.get('n')));
      state.perPage = Number.isFinite(n) && n >= 1 ? Math.min(n, state.pool.length || 1) : state.perPage;
      $('per-page').value = String(state.perPage);
    }
    if (p.get('dense')) setCompact(true);
    if (p.get('p')) {
      const pg = Math.floor(Number(p.get('p')));
      state.page = Number.isFinite(pg) && pg >= 1 ? pg : 1;
    }
  }

  /* ---------------- density ---------------- */
  function setCompact(on) {
    state.compact = on;
    document.body.classList.toggle('is-compact', on);
    $('density').setAttribute('aria-pressed', String(on));
  }

  /* ---------------- time machine ---------------- */
  const tmState = { playing: false, timer: null, point: -1, wired: false };

  function tmApply(index) {
    const hist = state.meta.history || [];
    if (!hist.length) return;
    const i = Math.max(0, Math.min(hist.length - 1, index));
    const p = hist[i];
    tmState.point = i;
    $('stat-alive').textContent = fmt(p.total);
    $('stat-countries').textContent =
      typeof p.countries === 'number' ? fmt(p.countries) : p.countriesTop?.length ? fmt(p.countriesTop.length) : '—';
    $('stat-latency').textContent =
      p.medianLatency === null || p.medianLatency === undefined ? '—' : `${Math.round(p.medianLatency)} ms`;
    const when = new Date(p.ts).toISOString().slice(0, 16).replace('T', ' ');
    $('tm-hint').textContent = t('tm.mode', { TIME: when });
    $('tm-reset').hidden = false;
    const slider = $('tm-slider');
    if (slider) slider.value = String(i);
  }

  function tmReset() {
    tmState.point = -1;
    tmStop();
    renderHero();
    $('tm-reset').hidden = true;
    tmScaleDates();
    const slider = $('tm-slider');
    if (slider) slider.value = String(Math.max(0, (state.meta.history || []).length - 1));
  }

  function tmPlay() {
    if (tmState.playing) return;
    const hist = state.meta.history || [];
    if (hist.length < 2) return;
    tmState.playing = true;
    $('tm-play').textContent = t('tm.pause');
    let i = tmState.point >= 0 ? tmState.point : 0;
    const step = () => {
      if (!tmState.playing) return;
      tmApply(i);
      i++;
      if (i >= hist.length) {
        tmStop();
        return;
      }
      tmState.timer = setTimeout(step, 220);
    };
    step();
  }

  function tmStop() {
    tmState.playing = false;
    clearTimeout(tmState.timer);
    $('tm-play').textContent = t('tm.play');
  }

  function wireTimeMachine() {
    const slider = $('tm-slider');
    const hist = state.meta.history || [];
    if (!slider || !hist.length) return;
    if (tmState.wired) return tmLabels();
    tmState.wired = true;
    slider.max = String(hist.length - 1);
    slider.value = String(hist.length - 1);
    slider.addEventListener('input', () => {
      tmStop();
      tmApply(Number(slider.value));
    });
    $('tm-play').addEventListener('click', () => (tmState.playing ? tmStop() : tmPlay()));
    $('tm-reset').addEventListener('click', tmReset);
    tmLabels();
  }

  /** the scale shows the real dates, the way a timeline control should */
  function tmScaleDates() {
    const hist = state.meta.history || [];
    if (!hist.length) return;
    const locale = window.I18N.lang === 'ru' ? 'ru-RU' : 'en-US';
    const day = (ts) => new Date(ts).toLocaleDateString(locale, { day: 'numeric', month: 'short' });
    $('tm-from').textContent = day(hist[0].ts);
    $('tm-to').textContent = day(hist[hist.length - 1].ts);
  }

  /** labels only - never moves the slider, the user's position stays put */
  function tmLabels() {
    const hist = state.meta.history || [];
    if (!$('tm-slider') || !hist.length) return;
    $('tm-hint').textContent = t('tm.points', { N: hist.length });
    tmScaleDates();
    if (tmState.point >= 0) tmApply(tmState.point);
  }

  /* ---------------- wiring ---------------- */
  function wire() {
    let debounce = null;
    $('q').addEventListener('input', (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => {
        state.q = e.target.value;
        state.page = 1;
        render();
      }, 90);
    });

    for (const b of document.querySelectorAll('#proto-chips .chip')) {
      b.addEventListener('click', () => {
        const v = b.dataset.proto;
        if (state.protos.has(v)) state.protos.delete(v);
        else state.protos.add(v);
        b.classList.toggle('is-on');
        state.page = 1;
        render();
      });
    }
    for (const b of document.querySelectorAll('#grade-chips .chip')) {
      b.addEventListener('click', () => {
        const v = b.dataset.grade;
        if (state.grades.has(v)) state.grades.delete(v);
        else state.grades.add(v);
        b.classList.toggle('is-on');
        state.page = 1;
        render();
      });
    }

    $('country').addEventListener('change', (e) => {
      state.country = e.target.value;
      state.page = 1;
      render();
    });
    $('per-page').addEventListener('change', (e) => {
      state.perPage = Number(e.target.value);
      state.page = 1;
      render();
    });

    for (const b of document.querySelectorAll('.sortbtn')) {
      b.addEventListener('click', () => {
        const key = b.dataset.sort;
        if (state.sortKey === key) {
          state.sortDir *= -1;
        } else {
          state.sortKey = key;
          state.sortDir = key === 'latency' || key === 'grade' || key === 'protocol' || key === 'country' ? 1 : -1;
        }
        for (const o of document.querySelectorAll('.sortbtn')) o.removeAttribute('data-dir');
        b.dataset.dir = state.sortDir === 1 ? 'asc' : 'desc';
        render();
      });
    }

    $('prev').addEventListener('click', () => {
      state.page--;
      render();
      $('pool').scrollIntoView({ block: 'start' });
    });
    $('next').addEventListener('click', () => {
      state.page++;
      render();
      $('pool').scrollIntoView({ block: 'start' });
    });

    $('tbody').addEventListener('click', (e) => {
      const copyBtn = e.target.closest('[data-copy]');
      if (copyBtn) {
        e.stopPropagation();
        const p = state.pool.find((x) => x.id === copyBtn.dataset.copy);
        if (p)
          copy(
            `${p.protocol}://${p.host}:${p.port}`,
            t('toast.copied', { TEXT: `${p.protocol}://${p.host}:${p.port}` }),
          );
        return;
      }
      const tr = e.target.closest('tr[data-id]');
      if (tr) openDrawer(tr.dataset.id);
    });
    $('tbody').addEventListener('keydown', (e) => {
      const tr = e.target.closest('tr[data-id]');
      if (tr && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        openDrawer(tr.dataset.id);
      }
    });

    for (const b of document.querySelectorAll('[data-close]')) b.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !$('drawer').hidden) closeDrawer();
    });

    $('drawer-copy-line').addEventListener('click', () => {
      if (current) copy(`${current.protocol}://${current.host}:${current.port}`, t('toast.copiedLine'));
    });
    $('drawer-copy-json').addEventListener('click', () => {
      if (current) copy(JSON.stringify(current, null, 2), t('toast.copiedJson'));
    });
    $('drawer-curl').addEventListener('click', () => {
      if (!current) return;
      const scheme = current.protocol === 'socks5' ? 'socks5h' : current.protocol === 'socks4' ? 'socks4' : 'http';
      copy(t('drawer.curlscheme', { SCHEME: scheme, HOST: current.host, PORT: current.port }), t('toast.copiedCurl'));
    });

    $('copy-best').addEventListener('click', () => {
      const taken = state.filtered.slice(0, 10);
      copy(
        taken.map((p) => `${p.protocol}://${p.host}:${p.port}`).join('\n'),
        t('toast.copied', { TEXT: `${taken.length} ${window.I18N.lang === 'ru' ? 'прокси' : 'proxies'}` }),
      );
    });

    $('export-txt').addEventListener('click', () => {
      const lines = state.filtered.map((p) => `${p.protocol}://${p.host}:${p.port}`);
      download(`proxy-pool-${state.filtered.length}.txt`, lines.join('\n'));
      toast(t('toast.exported', { N: fmt(state.filtered.length) }), 'ok');
    });

    $('density').addEventListener('click', () => setCompact(!state.compact));

    $('reset-filters').addEventListener('click', () => {
      state.q = '';
      $('q').value = '';
      state.protos = new Set(['http', 'socks4', 'socks5']);
      state.grades = new Set(['elite', 'anonymous', 'transparent', 'unknown']);
      state.country = '';
      $('country').value = '';
      state.page = 1;
      for (const b of document.querySelectorAll('.chip')) b.classList.add('is-on');
      render();
    });

    document.addEventListener('keydown', (e) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement;
      if (e.key === '/' && !typing) {
        e.preventDefault();
        $('q').focus();
      }
      if (!typing && e.altKey) {
        if (e.key === 'ArrowRight') $('next').click();
        if (e.key === 'ArrowLeft') $('prev').click();
      }
    });

    wireTimeMachine();
  }

  /* ---------------- boot ---------------- */
  function skeleton(n = 8) {
    const cells = Array.from({ length: 8 }, () => '<td><span class="sk"></span></td>').join('');
    $('skeleton').innerHTML = Array.from({ length: n }, () => `<tr>${cells}</tr>`).join('');
  }

  async function load() {
    const [meta, pool] = await Promise.all([loadMeta(), loadPool()]);
    state.meta = meta;
    state.pool = Array.isArray(pool) ? pool : [];
    renderHero();
    renderComposition();
    $('skeleton').hidden = true;
    $('tbody').hidden = false;
    buildCountrySelect();
    readHash();
    render();
  }

  skeleton();
  load()
    .then(wire)
    .catch((e) => showLoadError(e));

  // a language switch re-renders every dynamic string on this page
  onLanguageChange(() => {
    if (!state.meta) return;
    if (tmState.point >= 0) tmApply(tmState.point);
    renderHero();
    renderComposition();
    readHash();
    render();
    if (current) openDrawer(current.id, { silent: true });
  });

  window.addEventListener('hashchange', () => {
    readHash();
    render();
  });

  window.__pool = { state, openDrawer };

  window.PP.boot();
})();
