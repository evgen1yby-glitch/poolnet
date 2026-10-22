/**
 * The check page: paste an address, get a full request through it. The
 * checking itself runs on the edge API (/v1/check), this page only talks to
 * it and renders the verdict.
 */
(() => {
  const { $, t, escapeHtml } = window.PP;

  let proto = 'http';

  function show(html) {
    $('check-result').innerHTML = html;
  }

  function wire() {
    const form = $('check-form');
    const input = $('check-input');
    const run = $('check-run');
    if (!form || !input || !run) return;

    for (const chip of document.querySelectorAll('#check-form .chip')) {
      chip.addEventListener('click', () => {
        proto = chip.dataset.checkProto;
        for (const c of document.querySelectorAll('#check-form .chip')) c.classList.toggle('is-on', c === chip);
        input.focus();
      });
    }

    for (const ex of document.querySelectorAll('[data-example]')) {
      ex.addEventListener('click', () => {
        input.value = ex.dataset.example;
        proto = ex.dataset.exampleProto || proto;
        for (const c of document.querySelectorAll('#check-form .chip'))
          c.classList.toggle('is-on', c.dataset.checkProto === proto);
        form.requestSubmit();
      });
    }

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      check();
    });

    async function check() {
      const raw = input.value.trim();
      const m = /^(?:(socks5|socks4|https?):\/\/)?(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,5})$/.exec(raw);
      if (!m) {
        show(`<p class="checker__error">${escapeHtml(t('check.error.input'))}</p>`);
        return;
      }
      // an explicit scheme in the input always wins over the chip row
      const protocol = m[1] === undefined ? proto : m[1].replace('https', 'http');
      const addr = `${m[2]}:${m[3]}`;
      show(
        `<p class="checker__wait"><span class="checker__spin" aria-hidden="true"></span>${escapeHtml(
          t('check.checking', { ADDRESS: addr }),
        )}</p>`,
      );
      run.disabled = true;
      try {
        const api = document.body.dataset.api || '';
        if (!api || /your-worker\.workers\.dev/.test(api)) {
          show(`<p class="checker__error">${escapeHtml(t('check.error.noapi'))}</p>`);
          return;
        }
        const res = await fetch(`${api.replace(/\/$/, '')}/v1/check?proxy=${addr}&proto=${protocol}`, {
          signal: AbortSignal.timeout(35000),
        });
        const body = await res.json().catch(() => null);
        if (!res.ok || !body) {
          const why = res.status === 429 ? t('check.error.rate') : t('check.error.net');
          show(`<p class="checker__error">${escapeHtml(why)}</p>`);
          return;
        }
        const head = body.alive
          ? `<p class="checker__verdict checker__verdict--alive">${escapeHtml(t('check.alive'))}</p>`
          : `<p class="checker__verdict checker__verdict--dead">${escapeHtml(t('check.dead'))}` +
            ` <span class="checker__reason">${escapeHtml(body.error ?? '')}</span></p>`;
        const rows = [
          ['drawer.protocol', protocol],
          ['drawer.latency', body.latencyMs !== null && body.latencyMs !== undefined ? `${body.latencyMs} ms` : '—'],
          ['drawer.exit', body.remoteIp ?? '—'],
        ];
        show(
          `${head}<dl class="checker__grid">${rows
            .map(([k, v]) => `<dt>${t(k)}</dt><dd>${escapeHtml(String(v))}</dd>`)
            .join('')}</dl>`,
        );
      } catch {
        show(`<p class="checker__error">${escapeHtml(t('check.error.net'))}</p>`);
      } finally {
        run.disabled = false;
      }
    }
  }

  wire();
  window.PP.boot();
})();
