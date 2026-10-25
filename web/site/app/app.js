(function () {
  "use strict";

  var clock = document.querySelector(".clock");
  if (clock) {
    var now = new Date();
    clock.textContent = String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0");
  }

  var toastEl = document.getElementById("toast");
  var toastTimer = 0;
  function toast(text) {
    if (!toastEl) return;
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 1600);
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        document.execCommand("copy") ? resolve() : reject(new Error("copy failed"));
      } catch (error) {
        reject(error);
      } finally {
        document.body.removeChild(area);
      }
    });
  }

  document.addEventListener("click", function (event) {
    var copy = event.target.closest("[data-copy]");
    if (!copy) return;
    copyText(copy.getAttribute("data-copy")).then(function () {
      toast("Скопировано");
    }).catch(function () {
      toast("Не удалось скопировать");
    });
  });

  /* Connection orb: a local mock state, persisted so navigation feels real. */
  var orb = document.getElementById("connect");
  var connected = localStorage.getItem("poolnet-connected") !== "0";
  var statDown = document.querySelector('[data-stat="down"] b');
  var statUp = document.querySelector('[data-stat="up"] b');
  var statIp = document.querySelector('[data-stat="ip"] b');
  var pill = document.getElementById("conn-pill");
  var pillText = document.getElementById("conn-pill-text");
  var title = document.getElementById("conn-title");
  var sub = document.getElementById("conn-sub");

  function renderConnection() {
    if (!orb) return;
    orb.classList.toggle("connected", connected);
    orb.setAttribute("aria-pressed", connected ? "true" : "false");
    orb.setAttribute("aria-label", connected ? "Отключить VPN" : "Подключить VPN");
    var label = document.getElementById("orb-label");
    var hint = document.getElementById("orb-hint");
    if (label) label.textContent = connected ? "ЗАЩИЩЕНО" : "НЕ ПОДКЛЮЧЕНО";
    if (hint) hint.textContent = connected ? "нажмите, чтобы отключить" : "нажмите, чтобы подключиться";
    if (pill) pill.classList.toggle("off", !connected);
    if (pillText) pillText.textContent = connected ? "Защищено" : "Отключено";
    if (title) title.textContent = connected ? "Соединение защищено" : "VPN выключен";
    if (sub) sub.textContent = connected ? "Трафик идёт напрямую к узлу Amsterdam" : "Трафик больше не проходит через узел";
    if (statDown) statDown.innerHTML = connected ? '84.2<small>Mbps</small>' : '—';
    if (statUp) statUp.innerHTML = connected ? '12.4<small>Mbps</small>' : '—';
    if (statIp) statIp.textContent = connected ? "185.218.4.77" : "—";
  }
  if (orb) {
    renderConnection();
    orb.addEventListener("click", function () {
      connected = !connected;
      localStorage.setItem("poolnet-connected", connected ? "1" : "0");
      renderConnection();
      toast(connected ? "VPN подключён" : "VPN отключён");
    });
  }

  /* Selected server is local state shared by the connect and servers screens. */
  var saved = null;
  try { saved = JSON.parse(localStorage.getItem("poolnet-server") || "null"); } catch (error) { saved = null; }
  function applyServer(data) {
    if (!data) return;
    var cc = document.querySelector("#selected-server [data-cc]");
    var city = document.querySelector("#selected-server [data-city]");
    var country = document.querySelector("#selected-server [data-country]");
    if (cc) cc.textContent = data.cc;
    if (city) city.textContent = data.city;
    if (country) country.innerHTML = data.country + " · <span data-ping>" + data.ping + "</span> ms";
    var subline = document.getElementById("conn-sub");
    if (subline && connected) subline.textContent = "Трафик идёт напрямую к узлу " + data.city;
  }
  if (saved) applyServer(saved);

  var rows = document.querySelectorAll("[data-server]");
  rows.forEach(function (row) {
    if (saved && row.dataset.cc === saved.cc) row.classList.add("selected");
    if (!saved && row.dataset.cc === "NL") row.classList.add("selected");
    function choose() {
      var data = {
        cc: row.dataset.cc,
        city: row.dataset.city,
        country: row.dataset.country,
        ping: row.dataset.ping
      };
      localStorage.setItem("poolnet-server", JSON.stringify(data));
      rows.forEach(function (other) { other.classList.remove("selected"); });
      row.classList.add("selected");
      applyServer(data);
      toast("Выбрано: " + data.city);
    }
    row.addEventListener("click", function (event) {
      if (event.target.closest(".star")) return;
      choose();
    });
    row.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    });
    var star = row.querySelector(".star");
    if (star) {
      star.addEventListener("click", function (event) {
        event.stopPropagation();
        var on = !star.classList.contains("on");
        star.classList.toggle("on", on);
        star.setAttribute("aria-pressed", on ? "true" : "false");
        toast(on ? "Добавлено в избранное" : "Убрано из избранного");
        applyFilters();
      });
    }
  });

  /* Search + chips + protocol segment, shared by the two lists. */
  var search = document.getElementById("server-search") || document.getElementById("proxy-search");
  var listRows = document.querySelectorAll("#server-list .row, #proxy-list .proxy-row");
  var empty = document.getElementById("server-empty") || document.getElementById("proxy-empty");
  var chips = document.querySelectorAll(".chip[data-filter]");
  var segments = document.querySelectorAll(".segment [data-proto]");
  var activeFilter = "all";
  var activeProto = "all";

  function visible(row, query) {
    if (query && String(row.dataset.name || "").toLowerCase().indexOf(query) === -1) return false;
    if (activeProto !== "all" && row.dataset.proto && row.dataset.proto !== activeProto) return false;
    if (activeFilter === "fast") return row.dataset.filter === "fast";
    if (activeFilter === "fav") return Boolean(row.querySelector(".star.on"));
    if (activeFilter === "tls") return row.dataset.tls === "1";
    return true;
  }
  function applyFilters() {
    if (!listRows.length) return;
    var query = search ? search.value.trim().toLowerCase() : "";
    var shown = 0;
    listRows.forEach(function (row) {
      var ok = visible(row, query);
      row.style.display = ok ? "" : "none";
      if (ok) shown += 1;
    });
    if (empty) empty.classList.toggle("show", shown === 0);
  }
  if (search) search.addEventListener("input", applyFilters);
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      activeFilter = chip.dataset.filter;
      chips.forEach(function (other) {
        var on = other === chip;
        other.classList.toggle("on", on);
        other.setAttribute("aria-pressed", on ? "true" : "false");
      });
      applyFilters();
    });
  });
  segments.forEach(function (segment) {
    segment.addEventListener("click", function () {
      activeProto = segment.dataset.proto;
      segments.forEach(function (other) { other.classList.toggle("on", other === segment); });
      applyFilters();
    });
  });
  applyFilters();
})();
