(function () {
  "use strict";
  var lang = (document.documentElement.lang || "ru").toLowerCase().startsWith("en") ? "en" : "ru";
  var T = lang === "en"
    ? { all: "All", channels: "channels", channelOne: "channel", channelFromOne: "channel", channelFew: "channels", channelMany: "channels", shown: "shown", of: "of", updated: "updated", watch: "Watch", open: "Open", source: "source", sourceOne: "source", sourceFew: "sources", sourceMany: "sources", sources: "sources", reserveOne: "backup", reserveFew: "backups", reserveMany: "backups", live: "live", web: "web", noData: "Catalog is not available yet.", error: "Could not load the channel catalog.", close: "Close", player: "Channel", external: "Open stream in a new tab", hlsError: "The stream did not start in this browser. Open it in an external player." }
    : { all: "Все", channels: "каналов", channelOne: "канал", channelFromOne: "канала", channelFew: "канала", channelMany: "каналов", shown: "показано", of: "из", updated: "обновлено", watch: "Смотреть", open: "Открыть", source: "источник", sourceOne: "источник", sourceFew: "источника", sourceMany: "источников", sources: "источников", reserveOne: "резерв", reserveFew: "резерва", reserveMany: "резервов", live: "live", web: "в браузере", noData: "Каталог пока не собран.", error: "Не удалось загрузить каталог каналов.", close: "Закрыть", player: "Канал", external: "Открыть поток в новой вкладке", hlsError: "Поток не запустился в браузере. Откройте его во внешнем плеере." };
  var step = window.innerWidth < 640 ? 24 : 60;
  var state = { q: "", category: "", limit: step };
  var data = null;
  var filtered = [];
  var hls = null;

  var grid = document.getElementById("tv-grid");
  var empty = document.getElementById("tv-empty");
  var count = document.getElementById("tv-count");
  var date = document.getElementById("tv-date");
  var more = document.getElementById("tv-more");
  var search = document.getElementById("tv-search");
  var category = document.getElementById("tv-category");
  var reset = document.getElementById("tv-reset");
  var sourceList = document.getElementById("tv-source-list");
  var player = document.getElementById("tv-player");
  var video = document.getElementById("tv-video");
  var playerTitle = document.getElementById("tv-player-title");
  var playerSub = document.getElementById("tv-player-sub");
  var playerError = document.getElementById("tv-player-error");
  var playerExternal = document.getElementById("tv-player-external");
  var playerClose = document.getElementById("tv-player-close");

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char];
    });
  }
  function initials(name) {
    return String(name || "?").trim().split(/\s+/).slice(0, 2).map(function (part) {
      return part.charAt(0);
    }).join("").toUpperCase();
  }
  function dateText(value) {
    try {
      return new Date(value).toLocaleString(lang === "en" ? "en-GB" : "ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch (error) {
      return value || "—";
    }
  }
  function plural(value, one, few, many) {
    var n = Math.abs(Number(value) || 0) % 100;
    var n1 = n % 10;
    if (n > 10 && n < 20) return many;
    if (n1 === 1) return one;
    if (n1 >= 2 && n1 <= 4) return few;
    return many;
  }
  function sourcesText(value) { return number(value) + ' ' + plural(value, T.sourceOne, T.sourceFew, T.sourceMany); }
  function channelsFrom(value) { return value === 1 ? T.channelFromOne : T.channels; }
  function number(value) {
    return Number(value || 0).toLocaleString(lang === "en" ? "en-US" : "ru-RU");
  }
  function filter() {
    var q = state.q.trim().toLowerCase();
    return (data.channels || []).filter(function (channel) {
      if (state.category && channel.category !== state.category) return false;
      if (!q) return true;
      return [channel.name, channel.category, channel.quality, channel.url].join(" ").toLowerCase().indexOf(q) !== -1;
    });
  }
  function logo(channel) {
    var url = channel.logo || "";
    var image = url.indexOf("https://") === 0
      ? '<img src="' + esc(url) + '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()">'
      : "";
    return '<div class="tv-logo"><span>' + esc(initials(channel.name)) + "</span>" + image + "</div>";
  }
  function card(channel, index) {
    var web = channel.web_playable;
    var action = web
      ? '<button class="tv-play" type="button" data-play="' + index + '">' + T.watch + '</button>'
      : '<a class="tv-play ext" href="' + esc(channel.url) + '" target="_blank" rel="noopener">' + T.open + ' ↗</a>';
    return '<article class="tv-card">' +
      '<div class="tv-card-top">' + logo(channel) + '<div class="tv-card-copy"><h3>' + esc(channel.name) + '</h3><p>' + esc(channel.category || "Прочее") + '</p></div></div>' +
      '<div class="tv-card-tags"><span class="tv-tag live">' + T.live + '</span><span class="tv-tag quality">' + esc(channel.quality || "HLS") + '</span>' + (web ? '<span class="tv-tag web">' + T.web + "</span>" : "") + ((channel.variants || []).length > 1 ? '<span class="tv-tag reserve">+' + ((channel.variants || []).length - 1) + ' ' + plural((channel.variants || []).length - 1, T.reserveOne, T.reserveFew, T.reserveMany) + '</span>' : "") + '</div>' +
      '<div class="tv-card-foot"><span class="tv-meta"><b>' + esc(channel.latency_ms) + ' ms</b> · ' + sourcesText((channel.sources || []).length) + '</span>' + action + "</div>" +
      "</article>";
  }
  function render() {
    filtered = filter();
    var slice = filtered.slice(0, state.limit);
    grid.innerHTML = slice.map(function (channel) { return card(channel, data.channels.indexOf(channel)); }).join("");
    var hasRows = filtered.length > 0;
    grid.hidden = !hasRows;
    empty.hidden = hasRows;
    if (!hasRows) empty.textContent = T.noData;
    more.hidden = filtered.length <= state.limit;
    count.innerHTML = "<b>" + number(slice.length) + "</b> " + T.shown + " " + T.of + " <b>" + number(filtered.length) + "</b> " + channelsFrom(filtered.length);
    date.textContent = data.generated_at ? T.updated + " " + dateText(data.generated_at) + " UTC" : "";
    document.querySelectorAll(".tv-logo img").forEach(function (img) {
      img.addEventListener("error", function () { img.remove(); });
    });
  }
  function fillSelect(select, values, placeholder) {
    select.innerHTML = '<option value="">' + esc(placeholder) + "</option>" + values.map(function (value) {
      return "<option value=\"" + esc(value) + "\">" + esc(value) + "</option>";
    }).join("");
  }
  function stats() {
    var stats = data.stats || {};
    document.getElementById("tv-total").textContent = number(stats.channels);
    document.getElementById("tv-web").textContent = number(stats.web_playable);
    document.getElementById("tv-sources-count").textContent = number((data.sources || []).length);
    document.getElementById("tv-updated").textContent = dateText(data.generated_at);
    var sources = data.sources || [];
    sourceList.innerHTML = sources.map(function (source) {
      var ok = source.ok;
      return '<div class="tv-src"><span>' + esc(source.id) + '</span><b class="' + (ok ? "" : "bad") + '">' + (ok ? number(source.items) : "offline") + "</b></div>";
    }).join("");
    var counts = {};
    data.channels.forEach(function (channel) { counts[channel.category] = (counts[channel.category] || 0) + 1; });
    var order = Array.isArray(data.category_order) ? data.category_order.slice() : [];
    Object.keys(counts).forEach(function (name) { if (order.indexOf(name) === -1) order.push(name); });
    category.innerHTML = '<option value="">' + (lang === "en" ? "Genre" : "Жанр") + "</option>" + order.filter(function (name) { return counts[name]; }).map(function (name) {
      return '<option value="' + esc(name) + '">' + esc(name) + " · " + counts[name] + "</option>";
    }).join("");
  }
  var playerChannel = null;
  var playerQueue = [];
  var playerIndex = 0;
  var playerSwitching = false;

  function stopPlayer() {
    if (hls) { try { hls.destroy(); } catch (error) {} hls = null; }
    playerChannel = null;
    playerQueue = [];
    playerIndex = 0;
    playerSwitching = false;
    try { video.pause(); } catch (error) {}
    video.removeAttribute("src");
    video.load();
    player.hidden = true;
    document.body.classList.remove("tv-modal-open");
  }
  function showPlayerError() {
    playerError.hidden = false;
    playerError.textContent = T.hlsError;
  }
  function playAt(index) {
    if (!playerChannel || index >= playerQueue.length) { showPlayerError(); return; }
    playerIndex = index;
    playerError.hidden = true;
    var source = playerQueue[index].url;
    playerSub.textContent = (playerChannel.category || "HLS") + (index ? " · " + T.reserveOne + " " + (index + 1) : "");
    if (hls) { try { hls.destroy(); } catch (error) {} hls = null; }
    try { video.pause(); } catch (error) {}
    video.removeAttribute("src");
    video.load();
    if (window.Hls && window.Hls.isSupported()) {
      hls = new Hls({ enableWorker: true, lowLatencyMode: false });
      hls.loadSource(source);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, function () { video.play().catch(function () {}); });
      hls.on(Hls.Events.ERROR, function (_event, detail) {
        if (!detail || !detail.fatal || playerSwitching) return;
        playerSwitching = true;
        window.setTimeout(function () { playerSwitching = false; playAt(index + 1); }, 350);
      });
    } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = source;
      video.play().catch(function () {});
      video.addEventListener("error", function () { playAt(index + 1); }, { once: true });
    } else {
      showPlayerError();
    }
  }
  function showPlayer(channel) {
    playerChannel = channel;
    playerQueue = (channel.variants || []).filter(function (item) { return item.url && item.web_playable; });
    if (!playerQueue.length && channel.web_playable) playerQueue = [{ url: channel.url, web_playable: true }];
    playerTitle.textContent = channel.name;
    playerError.hidden = true;
    playerExternal.href = channel.url;
    player.hidden = false;
    document.body.classList.add("tv-modal-open");
    if (!channel.web_playable || !playerQueue.length) {
      playerSub.textContent = channel.category || "HLS";
      showPlayerError();
      return;
    }
    playAt(0);
  }
  function bind() {
    search.addEventListener("input", function () { state.q = search.value; state.limit = step; render(); });
    category.addEventListener("change", function () { state.category = category.value; state.limit = step; render(); });
    reset.addEventListener("click", function () {
      search.value = ""; category.value = "";
      state.q = ""; state.category = ""; state.limit = step;
      render();
    });
    more.addEventListener("click", function () { state.limit += step; render(); });
    grid.addEventListener("click", function (event) {
      var button = event.target.closest("[data-play]");
      if (!button) return;
      showPlayer(data.channels[Number(button.dataset.play)]);
    });
    playerClose.addEventListener("click", stopPlayer);
    player.addEventListener("click", function (event) { if (event.target === player) stopPlayer(); });
    document.addEventListener("keydown", function (event) { if (event.key === "Escape" && !player.hidden) stopPlayer(); });
  }
  fetch("/tv/channels.json", { cache: "no-store" })
    .then(function (response) { if (!response.ok) throw new Error(String(response.status)); return response.json(); })
    .then(function (payload) {
      data = payload;
      stats(); bind(); render();
    })
    .catch(function () {
      grid.innerHTML = '<div class="tv-empty">' + esc(T.error) + "</div>";
      empty.hidden = true;
    });
})();
