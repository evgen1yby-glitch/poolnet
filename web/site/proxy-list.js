// The proxy table's controls: search, protocol/grade chips, country and page
// size, and pagination. The rows come from `/api/proxies` one page at a time —
// the publication is tens of thousands of rows, so the browser never downloads
// the whole list.
//
// State lives in the query string, so a filtered view is linkable and the back
// button works. Russian is the source language; the two dictionaries below
// cover the interface strings, while row contents (addresses, grades, protocol
// names) are language-neutral.

(function () {
  const en = (document.documentElement.lang || "ru").startsWith("en");
  const text = en
    ? {
        all: "all countries",
        show: (from, to, total, gen) =>
          total ? `showing ${from}–${to} of ${total} · updated ${gen} UTC` : "no proxies match these filters",
        page: (page, pages) => `${page} / ${pages}`,
        prev: "Previous page",
        next: "Next page",
        loading: "loading…",
        error: "Could not load the list. Try again.",
        failed: "request failed",
        labels: ["#", "Proxy", "Protocol", "Grade", "Latency", "Uptime", "Country"],
      }
    : {
        all: "все страны",
        show: (from, to, total, gen) =>
          total ? `показано ${from}–${to} из ${total} · обновлено ${gen} UTC` : "по этим фильтрам ничего нет",
        page: (page, pages) => `${page} / ${pages}`,
        prev: "Предыдущая страница",
        next: "Следующая страница",
        loading: "загрузка…",
        error: "Не удалось загрузить список. Попробуйте ещё раз.",
        failed: "ошибка запроса",
        labels: ["#", "Прокси", "Протокол", "Класс", "Задержка", "Аптайм", "Страна"],
      };

  const body = document.getElementById("ptbody");
  const search = document.getElementById("f-search");
  const country = document.getElementById("f-country");
  const perPage = document.getElementById("f-per");
  const info = document.getElementById("pg-info");
  const pageLabel = document.getElementById("pg-page");
  const prev = document.getElementById("pg-prev");
  const next = document.getElementById("pg-next");
  if (!body || !search || !country || !perPage || !prev || !next) return;

  const params = new URLSearchParams(location.search);
  const state = {
    page: Math.max(1, parseInt(params.get("page") || "1", 10) || 1),
    per: [10, 25, 50, 100].includes(parseInt(params.get("per") || "", 10))
      ? parseInt(params.get("per"), 10)
      : window.matchMedia("(max-width:34rem)").matches
        ? 25
        : 50,
    q: params.get("q") || "",
    country: (params.get("country") || "").toUpperCase(),
    proto: split(params.get("proto")),
    grade: split(params.get("grade")),
  };

  function split(value) {
    return (value || "")
      .split(",")
      .map((part) => part.trim().toLowerCase())
      .filter(Boolean);
  }

  const esc = (value) =>
    String(value).replace(/[&<>"']/g, (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]),
    );

  const chips = (selector) => Array.from(document.querySelectorAll(selector));
  const selected = (selector) =>
    chips(`${selector}.on`).map((node) => node.dataset.proto || node.dataset.grade);

  function press() {
    chips("[data-proto]").forEach((node) =>
      node.setAttribute("aria-pressed", node.classList.contains("on") ? "true" : "false"),
    );
    chips("[data-grade]").forEach((node) =>
      node.setAttribute("aria-pressed", node.classList.contains("on") ? "true" : "false"),
    );
  }

  function syncChips() {
    chips("[data-proto]").forEach((node) => {
      if (state.proto.length) node.classList.toggle("on", state.proto.includes(node.dataset.proto));
    });
    chips("[data-grade]").forEach((node) => {
      if (state.grade.length) node.classList.toggle("on", state.grade.includes(node.dataset.grade));
    });
    // A URL that omits the parameter means "no filter": turn every chip on,
    // which is the page's default. An explicit list leaves the others off.
    if (!state.proto.length) chips("[data-proto]").forEach((node) => node.classList.add("on"));
    if (!state.grade.length) chips("[data-grade]").forEach((node) => node.classList.add("on"));
    press();
  }

  function writeUrl() {
    const next = new URLSearchParams();
    if (state.page > 1) next.set("page", String(state.page));
    if (state.per !== 50) next.set("per", String(state.per));
    if (state.q) next.set("q", state.q);
    if (state.country) next.set("country", state.country);
    const proto = selected("[data-proto]");
    if (proto.length && proto.length < 3) next.set("proto", proto.join(","));
    const grade = selected("[data-grade]");
    if (grade.length && grade.length < 4) next.set("grade", grade.join(","));
    const query = next.toString();
    history.replaceState(null, "", query ? `?${query}` : location.pathname);
  }

  function mountFlags() {
    if (window.Flags && window.Flags.mount) window.Flags.mount(body);
  }

  function renderRows(rows) {
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="7" class="pa" style="padding:1.6rem .95rem">${esc(
        text.show(0, 0, 0, ""),
      )}</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map((row) => {
        const rawUptime = row.uptime_30d ?? row.uptime_7d;
        const knownUptime = rawUptime != null && rawUptime !== "";
        const uptime = knownUptime ? Math.max(0, Math.min(100, Number(rawUptime))) : null;
        const grade = String(row.grade || "unknown");
        const label = (index) => ` data-label="${esc(text.labels[index])}"`;
        return (
          `<tr><td class="pa"${label(0)}>${esc(row.rank)}</td>` +
          `<td class="addr"${label(1)}>${esc(row.address)}</td>` +
          `<td${label(2)}><span class="pb">${esc(String(row.protocol).toUpperCase())}</span></td>` +
          `<td${label(3)}><span class="pb g-${esc(grade)}">${esc(grade)}</span></td>` +
          `<td class="num"${label(4)}>${esc(row.latency_ms)} ms</td>` +
          `<td class="up"${label(5)}><span class="upb"><i style="width:${uptime ?? 0}%"></i></span>${uptime == null ? "—" : `${uptime}%`}</td>` +
          `<td class="num"${label(6)}><span class="ccx" data-cc="${esc(row.country)}">${esc(row.country)}</span></td></tr>`
        );
      })
      .join("");
    mountFlags();
  }

  function renderCountries(countries) {
    if (country.options.length !== countries.length + 1) {
      country.innerHTML = "";
      const all = document.createElement("option");
      all.value = "";
      all.textContent = `${text.all} (${countries.reduce((sum, item) => sum + item.n, 0)})`;
      country.append(all);
      countries.forEach((item) => {
        const option = document.createElement("option");
        option.value = item.cc;
        const name = window.Flags ? window.Flags.countryName(item.cc) : item.cc;
        option.textContent = `${item.cc} — ${name}`;
        country.append(option);
      });
      country.value = state.country;
    }
  }

  function apply(payload) {
    renderCountries(payload.countries || []);
    country.value = state.country;
    renderRows(payload.rows || []);
    const total = payload.total || 0;
    const from = total ? (payload.page - 1) * payload.per + 1 : 0;
    const to = Math.min(payload.page * payload.per, total);
    info.textContent = text.show(from, to, total, payload.generated_utc || "—");
    pageLabel.innerHTML = `<b>${esc(payload.page)}</b> / ${esc(payload.pages)}`;
    prev.disabled = payload.page <= 1;
    next.disabled = payload.page >= payload.pages;
    prev.setAttribute("aria-label", text.prev);
    next.setAttribute("aria-label", text.next);
    state.page = payload.page;
  }

  let inFlight = 0;
  function load() {
    const query = new URLSearchParams({ page: state.page, per: state.per });
    const proto = selected("[data-proto]");
    const grade = selected("[data-grade]");
    if (proto.length && proto.length < 3) query.set("proto", proto.join(","));
    if (grade.length && grade.length < 4) query.set("grade", grade.join(","));
    if (state.country) query.set("country", state.country);
    if (state.q) query.set("q", state.q);
    const ticket = ++inFlight;
    info.textContent = text.loading;
    fetch(`/api/proxies?${query.toString()}`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(text.failed);
        return response.json();
      })
      .then((payload) => {
        if (ticket !== inFlight) return; // a newer filter won the race
        apply(payload);
        writeUrl();
      })
      .catch(() => {
        if (ticket === inFlight) info.textContent = text.error;
      });
  }

  function reset() {
    state.page = 1;
    state.q = search.value.trim();
    // The country picker has names; the search box may be given a name too.
    // Translate it instead of promising a name search the API cannot do.
    const named = window.Flags && window.Flags.codeForName
      ? window.Flags.codeForName(state.q)
      : null;
    if (named && !country.value) {
      state.country = named;
      state.q = "";
      search.value = "";
    } else {
      state.country = country.value;
    }
    state.proto = selected("[data-proto]");
    state.grade = selected("[data-grade]");
    // Turning the last chip off reads as "show nothing"; the useful reading is
    // "no filter", so restore all chips instead of rendering an empty table.
    if (!state.proto.length) {
      chips("[data-proto]").forEach((node) => node.classList.add("on"));
      state.proto = selected("[data-proto]");
    }
    if (!state.grade.length) {
      chips("[data-grade]").forEach((node) => node.classList.add("on"));
      state.grade = selected("[data-grade]");
    }
    load();
  }

  search.value = state.q;
  perPage.value = String(state.per);
  syncChips();
  if (!state.proto.length && !state.grade.length) {
    state.proto = selected("[data-proto]");
    state.grade = selected("[data-grade]");
  }

  chips("[data-proto]").forEach((node) =>
    node.addEventListener("click", () => {
      node.classList.toggle("on");
      press();
      reset();
    }),
  );
  chips("[data-grade]").forEach((node) =>
    node.addEventListener("click", () => {
      node.classList.toggle("on");
      press();
      reset();
    }),
  );
  let timer = 0;
  search.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(reset, 250);
  });
  country.addEventListener("change", reset);
  perPage.addEventListener("change", () => {
    state.per = parseInt(perPage.value, 10) || 50;
    state.page = 1;
    load();
  });
  prev.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      load();
    }
  });
  next.addEventListener("click", () => {
    state.page += 1;
    load();
  });

  load();
})();
