/**
 * The benchmark page: every published list measured by this pipeline's own
 * checks, ranked by the share of entries that answered a full request. The
 * rows arrive inside meta.json's `benchmark` block, so this page loads one
 * bundle and renders a table.
 */
(() => {
  const { $, t, fmt, escapeHtml, download, toast, loadMeta, showLoadError, onLanguageChange } = window.PP;

  const benchState = { rows: [], sort: 'live', q: '' };
  let bench = null;

  /** attach the trend (rank movement) to every row from the source history */
  function buildRows(b, sourceHistory) {
    const hist = (sourceHistory || [])[(sourceHistory || []).length - 2];
    const rows = (b.sources || []).map((r, i) => {
      const rank = b.ranks?.[r.id] ?? i + 1;
      const prev = hist?.ranks?.[r.id];
      const trend = prev === undefined ? null : prev - rank;
      return { ...r, rank, trend };
    });
    return rows;
  }

  function benchRows() {
    const q = benchState.q.trim().toLowerCase();
    const filtered = q ? benchState.rows.filter((r) => r.id.toLowerCase().includes(q)) : [...benchState.rows];
    const cmp = {
      live: (a, b) => b.liveRate - a.liveRate || b.alive - a.alive,
      alive: (a, b) => b.alive - a.alive,
      latency: (a, b) => (a.medianLatency ?? 9e9) - (b.medianLatency ?? 9e9),
      candidates: (a, b) => b.candidates - a.candidates,
      stale: (a, b) => (b.staleDays ?? -1) - (a.staleDays ?? -1),
      trend: (a, b) => (b.trend ?? -99) - (a.trend ?? -99),
    }[benchState.sort];
    return filtered.sort(cmp);
  }

  function renderBenchmark() {
    const body = $('bench-body');
    if (!body || !bench) return;
    const rows = benchRows();
    body.innerHTML = rows
      .map(
        (r) => `<tr>
        <td class="rank">${r.rank}</td>
        <td data-cell="src"><span class="bench__id">${escapeHtml(r.id)}</span></td>
        <td data-cell="live">
          <span class="uptime">
            <span class="uptime__bar"><span class="uptime__fill" style="--w:${Math.min(100, r.liveRate * 100).toFixed(2)}%"></span></span>
            <span class="uptime__n">${(r.liveRate * 100).toFixed(r.liveRate < 0.001 ? 3 : 1)}%</span>
          </span>
        </td>
        <td data-cell="alive" class="num">${fmt(r.alive)}</td>
        <td data-cell="cands" class="num dim">${fmt(r.candidates)}</td>
        <td data-cell="lat" class="num">${r.medianLatency === null || r.medianLatency === undefined ? '—' : Math.round(r.medianLatency) + ' ms'}</td>
        <td data-cell="elite" class="num">${r.eliteRate === null || r.eliteRate === undefined ? '—' : Math.round(r.eliteRate * 100) + '%'}</td>
        <td data-cell="stale" class="num ${r.staleDays !== null && r.staleDays > 90 ? 'stale' : ''}">${r.staleDays === null || r.staleDays === undefined ? '—' : r.staleDays + 'd'}</td>
        <td data-cell="trend" class="num">${
          r.trend === null
            ? '<span class="dim">—</span>'
            : r.trend > 0
              ? `<span class="up">▲${r.trend}</span>`
              : r.trend < 0
                ? `<span class="down">▼${-r.trend}</span>`
                : '<span class="dim">=</span>'
        }</td>
      </tr>`,
      )
      .join('');
    $('bench-foot').textContent = t('bench.measured', {
      TIME: bench.generatedIso ?? new Date(bench.generatedAt).toISOString().slice(0, 16).replace('T', ' '),
      ALIVE: fmt(bench.cycle.alive),
      SOURCES: fmt(bench.sources.length),
    });
  }

  function wire() {
    $('bench-q')?.addEventListener('input', (e) => {
      benchState.q = e.target.value;
      renderBenchmark();
    });
    for (const b of document.querySelectorAll('#bench-sort .chip')) {
      b.addEventListener('click', () => {
        benchState.sort = b.dataset.bench;
        for (const o of document.querySelectorAll('#bench-sort .chip')) o.classList.toggle('is-on', o === b);
        renderBenchmark();
      });
    }
    $('bench-export')?.addEventListener('click', () => {
      const head = 'rank,source,live_rate,alive,candidates,median_latency_ms,elite_rate,stale_days,trend';
      const lines = benchRows().map((r) =>
        [
          r.rank,
          r.id,
          (r.liveRate * 100).toFixed(3),
          r.alive,
          r.candidates,
          r.medianLatency ?? '',
          r.eliteRate === null ? '' : (r.eliteRate * 100).toFixed(1),
          r.staleDays ?? '',
          r.trend ?? '',
        ].join(','),
      );
      download(`proxy-benchmark-${benchRows().length}.csv`, head + '\n' + lines.join('\n'));
      toast(t('bench.export'), 'ok');
    });
  }

  loadMeta()
    .then((m) => {
      bench = m.benchmark;
      if (!bench) throw new Error('meta.json has no benchmark block');
      benchState.rows = buildRows(bench, m.sourceHistory);
      renderBenchmark();
      wire();
    })
    .catch((e) => {
      console.error('bench page failed', e);
      showLoadError(e);
    });

  onLanguageChange(() => renderBenchmark());

  window.PP.boot();
})();
