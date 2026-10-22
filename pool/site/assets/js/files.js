/**
 * The files page: what the pipeline publishes, where it lives, and how much
 * of it there is. Everything here is derived from one bundle.
 */
(() => {
  const {
    $,
    t,
    fmt,
    escapeHtml,
    loadMeta,
    showLoadError,
    onLanguageChange,
    flagSvg,
    countryName,
    repoBase,
    repoUrl,
    patchRepoLinks,
  } = window.PP;

  function buildLists(m) {
    $('filelist-protos').innerHTML = ['http', 'socks4', 'socks5']
      .map((p) => {
        const n = m.byProtocol[p] || 0;
        const file = p === 'http' ? 'http.txt' : `${p}.txt`;
        return `<li><a href="${repoUrl(`data/${file}`)}" data-external>
          <span>data/${file}</span><span class="count">${fmt(n)}</span></a></li>`;
      })
      .join('');
    $('filelist-countries').innerHTML =
      m.countries
        .slice(0, 5)
        .map(
          (c) => `<li><a href="${repoUrl(`data/country/${c.cc}.txt`)}" data-external>
          <span>${flagSvg(c.cc)} ${c.cc} · ${countryName(c.cc)}</span><span class="count">${fmt(c.n)}</span></a></li>`,
        )
        .join('') +
      `<li><a href="${repoBase()}" data-external><span>${t('files.allCountries', { COUNT: m.countries.length })}</span><span class="count">→</span></a></li>`;

    const topSrc = m.sources.slice(0, 6);
    const srcMax = Math.max(...topSrc.map((s) => s.alive), 1);
    $('sources-list').innerHTML = topSrc
      .map(
        (s) => `<li>
          <span class="src__name" title="${escapeHtml(s.id)}">${escapeHtml(s.id)}</span>
          <span class="src__bar"><i style="width:${(s.alive / srcMax) * 100}%"></i></span>
          <span class="src__n">${fmt(s.alive)}</span>
        </li>`,
      )
      .join('');
  }

  let meta = null;

  loadMeta()
    .then((m) => {
      meta = m;
      buildLists(meta);
      patchRepoLinks();
    })
    .catch((e) => showLoadError(e));

  onLanguageChange(() => {
    if (meta) buildLists(meta);
  });

  window.PP.boot();
})();
