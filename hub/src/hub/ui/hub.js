/* Renders the pool section and the node map from /api/v1/stats, and owns the
   RU/EN switcher. Deliberately dependency-free: a landing page that loads a
   framework to show four numbers ships a supply chain and a second failure
   domain to every visitor.

   The stats endpoint publishes aggregates only. Per-node addresses stay behind
   /sub/{token}, because a public node list is a ready-made blocklist.

   i18n is a dictionary plus `data-i18n` keys, not a build step and not a
   server round trip: the page's markup is Russian and English overwrites it.
   That order is a decision. A visitor whose language we do not have still
   gets a working page, and the copy the tests pin is the copy that renders
   when JavaScript is off. */
(function () {
  "use strict";

  var STRINGS = {
    // Russian for the labels the *script* renders. The labels baked into the
    // HTML are deliberately absent: those live in the markup and are restored
    // from the ORIGINALS snapshot below, so duplicating them here would create
    // two Russian copies of one string — and `snapshot()` is what makes
    // "back to Russian" possible at all, because the markup's own text is gone
    // from the DOM the moment English overwrites it.
    ru: {
      "cull.empty": "Прогонов ещё не было: конвейер ждёт первого запуска.",
      "cull.raw": "Строк из источников",
      "cull.parsed": "Разобрано в конфиги",
      "cull.tcp": "Порт отвечает",
      "cull.tls": "Рукопожатие проходит",
      "cull.config": "Конфиг валиден",
      "cull.http": "Трафик реально идёт",
      "pool.protocols": "Протоколы",
      "pool.verified": "в подписке сейчас",
      "pool.known": "узлов в индексе",
      "pool.countries": "стран",
      "pool.unit": "нод",
      "map.empty": "Стран для карты пока нет: пул ждёт первого прогона.",
      "pool.countries.title": "Страна выхода",
      "pool.country.hint": "Нажми на страну — бот выдаст ссылку только на неё",
      "pool.gen.note": "Поколение",
      "pool.gen.after": "— подписки ссылаются на него; предыдущие остаются доступными.",
      "pool.empty": "Поколения ещё нет: первый прогон конвейера ждёт",
      "stats.error": "Не удалось прочитать состояние пула",
      "pool.retry": "Проверить состояние",
    },
    en: {
      "doc.title": "PoolNet — free decentralized VPN platform",
      "doc.desc":
        "A public index of working proxy configs, verified before they are " +
        "published. Free, no accounts, no traffic logs. Decentralized free VPN: " +
        "public index of verified proxy configs.",
      "nav.how": "How it works",
      "nav.pool": "Pool",
      "nav.clients": "Clients",
      "nav.status": "Status",
      "nav.cta": "Subscribe",
      "hero.kicker": "a free VPN from shared nodes — no accounts, no payment, no logs",
      "hero.h1": "From the public lists only <b>a fraction of nodes</b> reaches you",
      "hero.lede":
        "PoolNet finds other people's proxy configs, checks every one and publishes " +
        "only the survivors. Free, forever: no accounts, no payment, no premium tier. " +
        "Traffic goes through the participants' own nodes — this server only finds " +
        "and checks them.",
      "hero.cta1": "Get a subscription",
      "hero.cta2": "See the pool",
      "hero.aside": "a check takes ~10 minutes",
      "hero.warn":
        "<strong>These are other people's nodes.</strong> Treat them as hostile: " +
        "send no passwords, no sessions, no payments. Free means “without guarantees”.",
      "about.title": "What PoolNet is",
      "about.a.k": "A shared network, not a subscription service",
      "about.a.v":
        "Every participant both publishes and consumes: one person's nodes serve " +
        "everyone. Streaming platforms charge a monthly fee for this — here the fee " +
        "is zero, because there are no expensive servers to rent.",
      "about.b.k": "Checked, not promised",
      "about.b.v":
        "No node reaches the subscription until it passes six stages: from “the port " +
        "answers” to “traffic actually flows”. The failed ones stay out of rotation; " +
        "the run journal below shows that.",
      "about.c.k": "Live readings, not a warehouse",
      "about.c.v":
        "The index is not a bucket of stale rows. Open the pool or a country and you " +
        "see what works right now, when it was last published and how long it survived. " +
        "Everything is public and recomputable.",
      "summary.lane":
        "the last run — how many nodes it verified, not the size of the subscription",
      "summary.in": "Lines from sources",
      "summary.out": "Passed every check",
      "summary.share": "Survival share",
      "cull.title": "What happens to a node on the way",
      "cull.aside": "last run",
      "cull.loading": "Reading the readings…",
      "pool.title": "Pool right now",
      "pool.loading": "Reading the pool state…",
      "cull.empty": "No runs yet: the pipeline is waiting for its first pass.",
      "cull.raw": "Lines from sources",
      "cull.parsed": "Parsed into configs",
      "cull.tcp": "Port answers",
      "cull.tls": "Handshake completes",
      "cull.config": "Config is valid",
      "cull.http": "Traffic actually flows",
      "pool.protocols": "Protocols",
      "pool.verified": "in the subscription",
      "pool.known": "nodes in the index",
      "pool.countries": "countries",
      "pool.unit": "nodes",
      "map.empty": "No countries to map yet: the pool is waiting for its first run.",
      "pool.countries.title": "Exit country",
      "pool.country.hint": "Pick a country and the bot gives you that country's link",
      "pool.empty": "No generation yet: the first pipeline run is waiting on",
      "pool.gen.note": "Generation",
      "pool.gen.after": "— subscriptions point at this one.",
      "stats.error": "Could not read the pool state. Check status.",
      "pool.retry": "Check the status",
      "why.title": "Why it is free",
      "why.a.k": "No rented servers",
      "why.a.v":
        "The expensive part of any paid VPN is the servers. Here there are zero: " +
        "traffic goes through the participants' own machines, and the hub servers " +
        "only check and publish.",
      "why.b.k": "No billing",
      "why.b.v":
        "Accounts, dashboards and plan tiers do not exist. The bot hands out a token " +
        "in one step, and there is no one around to expire it.",
      "why.c.k": "No “buy more” counter",
      "why.c.v":
        "The usual free tier comes with a throttled speed, an ad tap and a running " +
        "clock. There is none — just as there is no paid tier.",
      "limits.title": "What may and may not go through a node",
      "limits.allow": "Fine",
      "limits.a1": "Reading sites, watching video, updating apps",
      "limits.a2": "Routing your ordinary HTTPS traffic manually",
      "limits.a3": "Sharing the pool link — it is public",
      "limits.a4": "Publishing your own nodes — that is the pool",
      "limits.deny": "Not fine",
      "limits.d1": "Signing into accounts or banks — the nodes are foreign",
      "limits.d2": "Making payments through a node",
      "limits.d3": "Torrenting: it gets the shared hosts blocked",
      "limits.d4": "Holding more of the pool than you need",
      "clients.title": "Where to paste the subscription",
      "clients.lede":
        "A subscription is an ordinary URL. Any client that can import from a link accepts " +
        "it: one URL hands out a list that refreshes itself.",
      "clients.a": "JSON with country groups",
      "clients.b": "base64 list",
      "clients.c": "YAML with country groups",
      "clients.d": "plain list",
      "clients.note":
        "The country is measured, not guessed from a hostname: a verified node is fetched " +
        "through <code>cdn-cgi/trace</code> and its real exit country goes into the config. " +
        "A mislabelled country is scored down.",
      "faq.title": "Frequent questions",
      "faq.q1": "Is it really free?",
      "faq.a1":
        "Yes, entirely. No plans, no trial period, no “advanced” features for money. " +
        "There is no catch, because payment serves nothing here.",
      "faq.q2": "Who pays for the servers?",
      "faq.a2":
        "Nobody, because there are none. The nodes of the network are other " +
        "participants' machines that shared their configs; hosting the registry — " +
        "verification, storage, subscriptions — costs less than the donations it gets.",
      "faq.q3": "Do you keep logs?",
      "faq.a3":
        "Traffic never passes through the hub, so there is nothing to log and nothing " +
        "to log it with. The checking database stores protocol counts, check outcomes " +
        "and counters — no addresses.",
      "faq.q4": "How safe is it?",
      "faq.a4":
        "Honest answer: like a stranger's server. It is not yours, nobody vetted it, " +
        "and it must not see your sessions. For reading sites it is fine; for anything " +
        "sensitive — your own tested node.",
      "faq.q5": "Why do nodes sometimes die?",
      "faq.a5":
        "Public lists exhaust themselves: a machine is switched off, a host blocks, the " +
        "owner changes a config. Every generation is a freshly verified cut; one dead " +
        "node shrinks the pool and the next run refills it.",
      "faq.q6": "How is this different from a regular VPN?",
      "faq.a6":
        "A regular VPN is rented servers the company fully controls. Here nodes are " +
        "published and checked publicly, and the selection formula is open and " +
        "recomputable.",
      "faq.q7": "How do I get one specific country?",
      "faq.a7":
        "The bot issues a subscription assembled from one country. The list below " +
        "carries only the countries whose nodes passed the last check; the bot gives " +
        "you the link for each.",
      "final.h2": "Try it — it takes two minutes",
      "final.lede":
        "The bot gives you a token and a link in a single message. No forms, no " +
        "requisites: one step and you are in the pool.",
      "final.cta": "Get a subscription in Telegram",
      "final.ghost": "Watch the pool live",
      "footer.line":
        "PoolNet does not proxy your data and does not store it. The sources are open, " +
        "the rubric is public and recomputable.",
      "footer.copy": "© 2026 poolnet.online — a public registry of working nodes",
    },
  };

  var COUNTRY_NAMES = {
    ru: {
      NL: "Нидерланды", DE: "Германия", FI: "Финляндия", GB: "Великобритания",
      UK: "Великобритания", FR: "Франция", SE: "Швеция", PL: "Польша",
      CZ: "Чехия", AT: "Австрия", CH: "Швейцария", LT: "Литва", LV: "Латвия",
      EE: "Эстония", MD: "Молдова", RO: "Румыния", BG: "Болгария", IT: "Италия",
      ES: "Испания", PT: "Португалия", IE: "Ирландия", DK: "Дания", NO: "Норвегия",
      BE: "Бельгия", CA: "Канада", TR: "Турция", KZ: "Казахстан", GE: "Грузия",
      AM: "Армения", RS: "Сербия", SK: "Словакия", SI: "Словения", HR: "Хорватия",
      HU: "Венгрия", GR: "Греция", UA: "Украина", JP: "Япония", SG: "Сингапур",
      HK: "Гонконг", KR: "Корея", AU: "Австралия", IN: "Индия", BR: "Бразилия",
      AR: "Аргентина", MX: "Мексика", ZA: "ЮАР", AE: "ОАЭ", IL: "Израиль",
      IS: "Исландия", LU: "Люксембург", MT: "Мальта", CY: "Кипр", AL: "Албания",
      TH: "Таиланд", TW: "Тайвань", VN: "Вьетнам", MY: "Малайзия",
      CR: "Коста-Рика", RU: "Россия", CL: "Чили",
      BY: "Беларусь", BA: "Босния", MK: "Македония",
      ME: "Черногория", AZ: "Азербайджан", UZ: "Узбекистан",
      PH: "Филиппины", NZ: "Новая Зеландия", ID: "Индонезия",
      unknown: "не измерено", US: "США",
    },
    en: {
      NL: "Netherlands", DE: "Germany", FI: "Finland", GB: "United Kingdom",
      UK: "United Kingdom", FR: "France", SE: "Sweden", PL: "Poland",
      CZ: "Czechia", AT: "Austria", CH: "Switzerland", LT: "Lithuania",
      LV: "Latvia", EE: "Estonia", MD: "Moldova", RO: "Romania", BG: "Bulgaria",
      IT: "Italy", ES: "Spain", PT: "Portugal", IE: "Ireland", DK: "Denmark",
      NO: "Norway", BE: "Belgium", CA: "Canada", TR: "Turkey",
      KZ: "Kazakhstan", GE: "Georgia", AM: "Armenia", RS: "Serbia",
      SK: "Slovakia", SI: "Slovenia", HR: "Croatia", HU: "Hungary", GR: "Greece",
      UA: "Ukraine", JP: "Japan", SG: "Singapore", HK: "Hong Kong", KR: "Korea",
      AU: "Australia", IN: "India", BR: "Brazil", AR: "Argentina",
      TH: "Thailand", TW: "Taiwan", VN: "Vietnam", MY: "Malaysia",
      BY: "Belarus", BA: "Bosnia", MK: "Macedonia",
      CR: "Costa Rica", RU: "Russia", CL: "Chile",
      ME: "Montenegro", AZ: "Azerbaijan", UZ: "Uzbekistan",
      PH: "Philippines", NZ: "New Zealand", ID: "Indonesia",
      MX: "Mexico", ZA: "South Africa", AE: "UAE", IL: "Israel",
      IS: "Iceland", LU: "Luxembourg", MT: "Malta", CY: "Cyprus",
      AL: "Albania", unknown: "not measured", US: "United States",
    },
  };

  //: Flag by country code. The hub's renderer keeps its own copy for share-URI
  //: remarks; this one is for the page. A code with no mapping renders the
  //: globe rather than a wrong flag — the page shows measured countries, so a
  //: missing flag is honest and a guessed one is not.
  var FLAGS = {
    NL: "🇳🇱", DE: "🇩🇪", FI: "🇫🇮", GB: "🇬🇧", UK: "🇬🇧", FR: "🇫🇷",
    SE: "🇸🇪", PL: "🇵🇱", CZ: "🇨🇿", AT: "🇦🇹", CH: "🇨🇭", LT: "🇱🇹",
    LV: "🇱🇻", EE: "🇪🇪", MD: "🇲🇩", RO: "🇷🇴", BG: "🇧🇬", IT: "🇮🇹",
    ES: "🇪🇸", PT: "🇵🇹", IE: "🇮🇪", DK: "🇩🇰", NO: "🇳🇴", BE: "🇧🇪",
    CA: "🇨🇦", TR: "🇹🇷", KZ: "🇰🇿", GE: "🇬🇪", AM: "🇦🇲", RS: "🇷🇸",
    CR: "🇨🇷",
    SK: "🇸🇰", SI: "🇸🇮", HR: "🇭🇷", HU: "🇭🇺", GR: "🇬🇷", UA: "🇺🇦",
    JP: "🇯🇵", SG: "🇸🇬", HK: "🇭🇰", KR: "🇰🇷", AU: "🇦🇺", IN: "🇮🇳",
    BR: "🇧🇷", AR: "🇦🇷", MX: "🇲🇽", ZA: "🇿🇦", AE: "🇦🇪", IL: "🇮🇱",
    IS: "🇮🇸", LU: "🇱🇺", MT: "🇲🇹", CY: "🇨🇾", AL: "🇦🇱", US: "🇺🇸",
    TH: "🇹🇭", TW: "🇹🇼", VN: "🇻🇳", MY: "🇲🇾", BY: "🇧🇾", BA: "🇧🇦",
    MK: "🇲🇰", ME: "🇲🇪", AZ: "🇦🇿", UZ: "🇺🇿", PH: "🇵🇭", NZ: "🇳🇿",
    ID: "🇮🇩", RU: "🇷🇺", CL: "🇨🇱",
  };

  //: Где узел выходит, на равнопрямоугольной карте мира: широта и долгота
  //: центроида страны по формулам x = (lon+180)/3.6, y = (75-lat)/1.35 —
  //: тем же формулам подчиняются сетка меридианов и параллели, поэтому
  //: точка обязана им соответствовать. Прежняя таблица писалась под старый
  //: квадратный viewBox и несла широты, сгруженные к пропорции высоты:
  //: Европа стояла у экватора, Австралия — в северном полушарии. Код
  //: страны без записи здесь пропускается из созвездия: точка на выдуманном
  //: месте — декор, выдающий себя за данные, а список стран ниже всё равно
  //: её несёт.
  var MAP_POS = {
    US: [22.8, 26.1], CA: [21.9, 12.6], MX: [21.5, 37.9], BR: [35.6, 63.6],
    AR: [32.2, 81.2], ZA: [56.9, 77], IN: [71.9, 38.6], AE: [65.1, 37.8],
    IL: [59.7, 32.3], TR: [59.8, 26.7], GE: [62.1, 24.3], AM: [62.5, 25.7],
    AZ: [63.2, 25.6], KZ: [68.6, 19.9], UZ: [67.6, 24.6], GB: [49.6, 16.5],
    IE: [47.8, 16.1], IS: [44.8, 7.5], FR: [50.7, 21], DE: [52.9, 17.6],
    NL: [51.5, 16.9], BE: [51.3, 18.1], LU: [51.7, 18.7], CH: [52.3, 20.9],
    AT: [53.9, 20.3], CZ: [54.3, 18.7], PL: [55.4, 17], SK: [55.5, 19.5],
    HU: [55.4, 20.6], SI: [54.1, 21.4], HR: [54.6, 21.8], BA: [54.9, 22.8],
    RS: [55.8, 22.9], ME: [55.4, 23.9], MK: [56, 24.7], AL: [55.6, 25.1],
    GR: [56.2, 26.6], BG: [57, 23.9], RO: [56.9, 21.5], MD: [57.9, 20.6],
    UA: [58.7, 19.3], BY: [57.6, 15.9], LT: [56.7, 14.7], LV: [56.9, 13.4],
    EE: [57.2, 12.1], FI: [57.2, 9], SE: [54.6, 10.7], NO: [52.8, 10],
    DK: [52.6, 14.1], IT: [53.5, 23.9], ES: [49, 25.8], PT: [47.7, 26.2],
    MT: [54, 29], CY: [59.2, 29.6], JP: [88.3, 28.5], SG: [78.8, 54.6],
    HK: [81.7, 39], KR: [85.5, 28.6], AU: [87.4, 74.3], NZ: [98, 86.5],
    TW: [83.6, 38], TH: [78.1, 44.4], VN: [79.5, 43.3], MY: [78.3, 52.4],
    PH: [84.1, 46], ID: [81.6, 57.3], CR: [26.6, 48.2], RU: [77.5, 10],
    CL: [30.2, 82], unknown: null,
  };

  var LAND = "M62.4 71.6L63.1 71.9L63.9 72.1L63.1 72.4L62.6 72.4L62.1 72.6L61.5 72.5L60.6 72.3L59.9 71.9L59.3 71.6L58.5 71L59 71.1L59.8 71.5L60.5 71.7L61 71.1L61.5 70.8L62.1 71.2ZM180.8 64.3L181.3 64.5L182 64.3L182.4 65L182.2 65.7L181.6 65.9L181.1 65.9L180.8 65.4L180.4 64.5ZM196.1 64.4L196.6 64.4L196.8 64.9L196.2 65.5L196.2 66L195.7 66L195.1 66.6L194.8 67.2L194.1 67.6L193.6 67.6L192.6 67.3L192.8 66.7L193.5 66.2L194.3 65.9L195.1 65.3L195.5 64.7L196 64.2ZM197 61.8L197.4 62.3L198.2 62.7L198.9 62.5L199 63.1L198.4 63.4L198.3 63.9L197.8 64.6L197.3 64.7L197.3 64.1L196.6 63.6L197.1 62.8L196.8 62.1L196.1 61.2L196.8 61.3L197 61.8ZM192.8 54L192.3 54L191.6 53.4L191.1 52.8L191.7 53L192.6 53.7ZM127.8 49.2L127.9 49.9L128 50.4L127.7 51L127.5 51.6L127.2 52.3L127 53.1L126.6 54.1L126.4 54.9L126.2 55.5L125.7 55.7L125.2 55.9L124.5 55.5L124.3 54.8L124.1 54.3L124.1 53.5L124.7 52.8L124.6 52.2L124.4 51.3L124.7 50.7L125.3 50.5L126 50.1L126.5 49.8L126.6 49.3L127.1 48.9L127.3 48.4L127.8 49.2ZM179.8 49.3L180.3 49.5L180.8 50L180.8 50.7L181.2 51.5L181.3 52.2L181.9 52.5L182.7 53L182.9 53.5L183.2 54.1L183.7 54.1L183.8 54.7L184.5 55.3L185.1 56.2L185.1 56.8L185.3 57.3L185.3 57.8L185 58.5L184.9 59.2L184.7 59.8L184.1 60.5L183.7 61.2L183.4 61.9L183.3 62.5L182.4 62.7L181.9 62.9L181.3 63.4L180.8 63.1L180.3 62.8L179.8 63.2L179.3 63.1L178.7 62.9L178.1 62.8L177.7 62L177.3 61.5L176.7 61.5L176.8 60.8L176 61.3L176.4 60.6L176.6 59.9L176.1 60.4L175.5 61.1L175.1 60.5L174.5 59.9L173.9 59.5L173 59.2L172 59.2L171.2 59.4L170.6 59.6L170.1 59.6L169.5 59.8L169 60L168.7 60.5L168.2 60.5L167.4 60.5L166.6 60.5L166.1 60.8L165.6 61.1L164.8 61.1L164.2 60.8L163.9 60.3L164.3 59.6L164 58.7L163.9 58L163.7 57.5L163.4 56.9L163 56.4L163 55.9L163.5 56.3L163.2 55.6L163.1 54.9L163.2 54.2L163.7 53.8L164.4 53.4L165.1 53.1L165.7 53L166.3 52.8L167.1 52.6L167.6 52.1L167.9 51.6L168.3 50.8L168.6 51.3L168.8 50.6L169.4 50L170.1 49.6L170.6 49.3L171.3 49.9L172 50L172.2 49.2L172.6 48.6L173.2 48.5L173.7 48.4L173.2 47.9L173.9 48L174.7 48.4L175.2 48.5L175.7 48.4L175.7 49.1L175.4 49.6L175.7 50.3L176.4 50.7L177 51L177.9 51.5L178.4 51L178.6 50.5L178.7 50L178.6 49.3L178.8 48.7L179 48L179.5 48.3L179.7 48.8L179.8 49.3ZM169.1 47.3L168.6 47.4L168.9 46.8L169.4 46.6L170 46.4L170.5 46.3L170 46.7L169.5 46.9ZM160.3 45.4L161.4 45.5L162.6 45.5L163.6 46L164.3 46.3L163.6 46.5L163 46.3L162.5 46.3L162 46.3L161.4 46.2L160.8 46L160.2 46L159.1 45.8L158.5 45.5L158.9 44.9L159.6 45L160.3 45.2ZM184.4 44.7L183.8 45L183.2 45.2L182.7 45L183.2 44.7L183.8 44.7L184.2 44L184.4 44.7ZM174.5 42.3L174.7 43.2L175.3 43.5L175.7 42.9L176.4 42.6L177.3 42.8L178.3 43.1L179.3 43.5L180.3 43.8L181 44.4L182 45L181.8 45.8L182.3 46.1L182.6 46.7L183.4 47L183.7 47.5L183.2 47.4L182.7 47.4L182.2 47.3L181.7 46.9L181.1 46.1L180.4 45.9L179.9 46.1L179.7 46.7L179.2 46.8L178.4 46.7L177.9 46.3L177.3 46.2L176.5 46.3L177 45.7L176.9 45.1L175.5 44.2L174.3 43.6L173.8 43.7L173.3 43.2L173.9 43L173.2 42.6L172.7 42.5L173.3 42.1L174.4 42.1ZM169.6 40.9L169.1 41.4L168.2 41.4L167.3 41.5L166.8 41.5L166.7 42L167.2 42.4L168.5 42L168 42.5L167.5 42.7L168 43.4L168.4 44.3L168.1 44.8L168.2 44.1L167.6 44.4L167.2 43.7L167.2 43.1L166.9 43.9L166.9 44.7L166.3 44.7L166.5 44.1L166.4 43.6L166.2 42.9L166.3 42.4L166.6 41.6L167.2 40.9L168.3 41.2L168.9 41.2L169.5 40.8ZM171.5 41L171.5 41.5L171.3 42.1L170.8 41.1L171.1 40.5L171.5 41ZM158.8 44.9L158.2 44.9L157.7 44.5L157 44L156.3 43.2L155.6 42L155.1 41.6L155 41.1L154.3 40.3L154 39.8L153 38.9L154.2 38.8L154.6 39.3L155.1 39.7L155.9 40.5L156.5 40.5L157.3 41.4L157.5 42.1L158 42.3L158.3 43L158.9 43.4L158.8 44.1L158.8 44.9ZM165.5 40.7L166.1 41.2L165.5 41.2L165.3 42.1L164.8 42.5L164.7 43L164.5 43.9L163.8 43.9L163.2 43.6L162.3 43.6L161.7 43.4L161.2 43.3L161.2 42.6L160.6 41.9L160.5 41.4L160.6 40.9L161.3 40.7L161.8 40.6L162.1 40.1L162.8 39.9L163.4 39.2L164.1 38.6L164.6 38.3L164.8 37.8L165.4 38.1L166.2 38.7L165.9 39.2L165.2 39.9L165.6 40.4ZM170.2 37L170.3 37.7L170.1 38.2L169.9 37.6L169.8 38.3L169 38.2L169 37.6L168.5 37.5L167.8 37.8L168 37.2L168.6 36.8L169.2 36.9L169.7 36.7L169.7 36.2L170.2 36.8ZM145.1 38.2L144.6 38.4L144.4 37.9L144.3 37.1L144.5 36.2L145.2 36.9L145.4 37.5L145.4 38.1ZM168.9 36L168.5 36.5L168 36.3L168.3 35.6L168.9 35.4L168.9 36ZM169.7 34.9L169.9 35.5L169.3 36L169.1 35.3L169 34.7L169.6 34.7ZM167.4 31.4L167.9 31.4L168.1 32.2L167.6 32.8L167.5 33.3L167.9 33.8L168.9 34L168.9 34.7L168.3 34.1L167.8 34L167.3 34.1L167.2 33.6L166.7 33.3L166.6 32.6L166.9 31.9L167.1 31.4ZM59.7 30.6L60.2 30.7L60.7 30.6L61.2 30.9L61.8 31.1L61.8 31.6L61.3 31.5L60.8 31.6L60.3 31.9L59.8 31.5L59.2 31.5L58.6 31.5L59.2 31.4L59.8 31.3L59.6 30.8ZM161.3 31.3L160.8 31.6L160.3 30.9L161.2 30.5L161.7 30.7L161.3 31.3ZM55.7 29L56.5 29.2L57.1 29.6L57.7 29.9L58.4 30.2L57.6 30.6L56.8 30.6L56.6 30.1L56 29.7L55.4 29.5L54.5 29.3L54 29.1L53.4 29.4L52.8 29.5L53.5 29L54.2 28.8L54.8 28.8L55.7 29ZM167.3 29L167.1 29.5L166.8 29L167.1 28L167.8 27.8L167.3 29ZM108.6 20.4L108.4 20.9L107.7 21.1L106.9 20.8L107.6 20.5L108.2 20.5ZM178.3 21L178.1 21.5L177.9 22.1L177.2 22.4L176.2 22.4L175.4 23.1L175 22.4L174.1 22.6L173.4 22.8L172.8 22.8L173.3 23.3L173 24.2L172.3 24.2L172.5 23.7L171.9 23.2L172.4 23L173.3 22.4L174.8 21.8L175.4 21.9L176 20.9L177.1 20.7L177.8 19.8L177.7 19.1L178.5 18.7L178.8 19.4L178.8 19.9L178.3 20.5L178.3 21ZM180 17.1L180.7 17L180.9 17.6L180 17.8L179.5 18.3L178.7 18L178.4 18.6L177.8 18.6L177.7 18L178.5 17.6L178.7 16.8L179.5 16.9L180 17.1ZM31.4 14.7L30.2 14.5L29.5 14.1L28.9 13.9L29.6 13.7L30.1 13.7L30.6 14.2L31.2 14.4ZM68.8 13.5L68.4 14L69.2 13.9L69.7 14.1L70.3 14.3L70.6 14.9L70.5 15.7L69.9 15.7L70 15.2L69.2 15.6L68.7 15.2L68.2 15.2L67.1 15.2L67.1 14.7L67.6 14.4L68.1 13.5L69 13L68.8 13.5ZM179.8 13.5L180.4 14.5L179.5 14.3L179.2 15.1L179.7 15.6L178.9 16.1L178.9 15.1L178.8 14.5L179 13.4L178.7 12.8L178.7 12.1L179.2 11.8L179.6 12.4L179.6 12.9L179.8 13.5ZM96.2 12.6L95.2 13L94.5 12.9L94.9 12.3L94.6 11.7L95.4 11.3L96.3 11L96.9 11.4L96.6 12.1L96.2 12.6ZM98.3 9.1L97.7 9.7L98.3 9.6L98.9 9.6L98.8 10.1L98.3 10.6L98.8 10.6L99.4 11.3L100.1 12L100.9 12.4L100.6 12.9L100.3 13.5L99.6 13.5L98.6 13.6L98 13.8L97.5 13.7L96.8 13.8L97.6 13.2L98.1 13.1L97.2 13L97.7 12.6L97.5 11.9L98.3 12L98 11.3L97.3 11.2L97.2 10.7L96.6 10.1L96.8 9.5L97.7 9.1L98.3 9.1ZM52.7 5.2L53.4 5.5L54 5.7L54.6 5.9L55.1 6.1L54.1 6.3L53.3 6.4L52.5 6.6L51.5 6.4L52 6.1L52.3 5.1ZM91.9 4.7L92.4 5.5L91.7 5.9L90.1 6.3L89.6 6.4L88.9 6.3L87.4 6.1L87.9 5.9L86.7 5.6L87.7 5.5L86.5 5.2L87.7 4.8L88.6 5.1L89.4 4.8L90.1 5L91 4.7L91.9 4.7ZM2.8 4.7L4.5 4.5L5.6 5L5.1 5.3L4.1 5.3L4.1 5.9L3.4 6L2.2 5.6L1.5 5.3L0.9 5.3L0.1 5.1L0 5.6L0 3.4L1.4 3.8L2.8 4.3ZM46.9 3.3L45.8 3.3L45.3 3.4L44.6 3.1L45.4 2.7L46 2.9L46.5 3.1ZM49.7 3.1L49.7 3.6L50.4 3.2L51.1 3.5L50.9 4L51.5 4.3L52.1 3.9L52.5 2.8L53.3 2.9L54.1 3L54.8 3.2L54.5 3.8L54.8 4.4L53.7 4.8L52.9 4.9L52.4 4.7L51.6 5.4L50.8 6.1L50 6.1L49.6 6.7L48.9 6.8L48.2 7.2L47.6 7.8L47.4 8.3L47.4 8.9L48.2 9L48.5 9.5L48.7 10L49.5 9.8L50.5 10.1L51.1 10.3L52.2 10.7L52.8 10.9L53.7 11L54.3 11L54.2 11.5L54.4 12.1L54.8 12.7L55.6 13.2L56.3 12.5L56 11.6L56.5 11L57.2 10.6L57.4 9.9L57.1 9.4L56.4 9L57 8.4L56.8 7.9L56.6 7L57.9 7.1L58.5 7.1L59 7L59.5 7.2L60.2 7.5L61.3 7.7L61.3 8.2L61.5 8.9L62 9L63.2 9L63.8 8.4L64.6 8.6L65.3 9.4L65.9 10L66.4 10.7L66.9 11L67.8 11.1L68.4 11.8L69 12.1L69.1 12.7L68.3 13.1L67.3 13.3L66.6 13.8L65.7 13.8L64.5 13.7L63.7 13.7L63.1 13.8L62.6 14.2L61.9 14.4L61.1 15.1L60.5 15.7L61 15.6L61.9 14.8L63 14.4L63.9 14.3L63.8 15L64 15.6L64.9 16.3L65.8 16.2L66.4 15.6L66.8 16.2L66.1 16.5L64.9 16.8L64.3 17.1L63.7 17.5L63.2 17L64.2 16.5L63.3 16.5L62.7 16.6L62.2 17L61.6 17.2L61 17.4L60.7 17.9L60.8 18.4L60.1 18.7L59.5 18.8L59 18.9L59.9 18.8L59.3 19.1L58.7 19.2L58.4 20L58.1 20.5L57.8 21L57.6 20.4L57.6 19.9L57.6 20.5L57.6 21.1L57.9 21.9L57 22.5L56.4 22.9L55.4 23.6L54.8 24.2L54.8 25L55 25.5L55.3 26.1L55.5 26.7L55.5 27.3L54.9 27.7L54.3 26.8L54 26.2L53.9 25.5L53.5 25L52.7 25.2L52 24.8L51.4 24.8L50.9 24.8L50.2 24.9L50.4 25.4L49.9 25.5L49.1 25.2L48.6 25.2L47.9 25.2L47.4 25.3L46.9 25.7L46.3 25.9L45.9 26.5L45.9 27.1L45.8 27.8L45.7 28.9L45.7 29.5L46 30.2L46.5 30.9L47.3 31.4L48 31.4L48.5 31.4L49.2 31.2L49.7 30.6L49.8 30L50.8 29.7L51.3 29.7L51.8 29.8L51.5 30.4L51.3 31.1L51 31.6L50.9 32.1L50.8 32.6L51.3 32.8L52 32.9L52.5 32.8L53 32.9L53.5 33.1L53.8 33.7L53.6 34.4L53.5 35.1L53.5 35.6L53.9 36.1L54.3 36.6L54.8 36.8L55.3 36.6L55.8 36.3L56.4 36.4L57 36.8L57.7 36.5L58.1 35.8L58.7 35.5L59.2 35.4L59.7 35.1L60.3 34.8L60.4 35.3L60.2 35.9L60.2 36.6L60.4 36L61 35.3L61.7 35.3L62.1 35.8L62.6 35.8L63.2 35.8L63.9 36.1L65 35.7L65.6 35.7L65.1 35.9L65.8 36.2L66.3 36.9L66.8 37L67.5 37.6L68 38.2L68.9 38.5L69.4 38.3L70 38.5L70.6 38.7L71.2 39.1L71.6 39.6L71.9 40.6L72.3 41.1L71.8 41.5L73 41.8L73 42.4L74.1 42.2L75.1 42.5L75.2 43.2L75.9 43L77 43.3L77.8 43.3L78.6 43.7L79.3 44.3L80.2 44.5L80.6 45.4L80.5 46.7L79.4 47.8L79.1 48.4L78.7 48.9L78.4 50.4L78.2 51.2L78 51.8L77.9 52.6L77.3 53.3L77.3 53.9L76.8 54.1L76.1 54.4L75.2 54.6L74.2 55L73.5 55.5L73.1 56L73 56.5L73 57.3L72.5 57.9L71.8 58.9L71.3 59.3L70.7 60.1L70.1 60.8L69.5 61.1L68.8 61L68.3 60.8L67.5 60.5L68.2 61.3L68.5 61.9L67.9 62.9L67.1 63.2L66 63.3L65.4 63.2L65.4 64L65.1 64.5L64.6 64.5L64 64.3L63.9 65L64.6 65L64.2 65.5L63.7 66.4L63.1 66.7L62.6 67L63 67.8L63.5 67.9L63.3 68.4L62.7 68.7L62.3 69.4L61.8 69.6L61.8 70.4L61.1 70.9L60.6 71.1L60.6 71.6L59.7 71.4L59.1 71L58.4 70.7L58.3 70L58 68.7L58.2 68.2L58.8 67.7L58 67.6L58.5 67.1L58.7 66.2L59.3 66.4L59.6 65.2L59.1 65.8L58.9 64.9L59.1 63.9L59.2 62.9L59.1 62.3L59.7 61.4L60.1 60.5L60.3 59.7L60.2 58.8L60.3 57.7L60.6 57L60.7 55.9L60.9 54.8L61.1 53.6L61 52.6L60.9 51.9L60.3 51.5L59.2 50.8L58.2 50.1L57.5 49.3L57.2 48.5L56.6 47.4L56.1 46.3L55.7 45.7L54.9 45.1L54.8 44.3L55.4 43.6L55.7 43.1L55 42.9L55 42.3L55.3 41.8L55.5 41.2L56.2 40.9L56.3 40.4L56.9 39.8L57.1 39.1L56.9 38.6L57 37.9L56.5 37.5L56.6 37L56 36.7L55.5 37L55.6 37.5L55.1 37.7L54.6 37.2L54 37.1L53.5 36.9L53.2 36.4L52.7 36.4L52.3 35.9L52.2 35.3L51.6 34.7L51.2 34.2L50.6 34.3L50.1 34.2L49.3 33.9L48.8 33.6L48.1 33L47.4 32.7L46.6 32.9L46 32.8L45.5 32.7L45 32.5L44 32.1L43.5 31.9L42.5 31.5L41.7 30.9L41.3 30.3L41.5 29.8L41.3 29.3L40.6 28.5L40 28L39.3 27.5L39.3 27L38.7 26.6L38.2 26.1L37.7 25.6L37.3 25L37.1 24.3L36.6 24.2L36.1 24.2L36.3 24.9L36.9 25.5L37.4 26.2L38 26.9L38.2 27.4L38.5 27.9L39 28.4L39 29L38.4 28.3L37.7 27.9L37.6 27.2L37 26.8L36.4 26.6L36.6 26L36.1 25.4L35.6 24.9L35.2 24.1L34.9 23.6L34.5 23L33.8 22.7L33.1 22.5L32.4 21.6L31.9 20.8L31.3 20L30.9 19.3L31 18.8L31 18.3L31 17.4L31.2 16.4L31.1 15.6L30.7 14.9L31.6 15L31.9 15.5L31.9 14.9L31.8 14.4L30.6 13.9L29.2 13.4L28.9 12.9L28.3 12.4L28.2 11.9L27.5 11.5L27.2 11L26.7 10.8L26.5 10.3L25.8 9.9L25.5 9.4L25 9.3L24.1 9.3L23.4 9.2L22.3 8.6L21.8 8.5L20.8 8.3L20 8.3L18.9 8.1L18.3 7.8L17.7 8L16.8 8.5L16.3 8.7L15.7 8.8L15.9 7.9L16.5 7.8L15.6 7.9L14.4 8.7L14.3 9.4L13.7 9.6L13.2 9.8L12.2 10.3L11.3 10.8L10.4 10.9L9.9 11.1L9.4 11.3L8.5 11.4L9 11.1L9.5 10.9L10.1 10.6L10.8 10.6L11.8 10L12.4 9.7L12.8 8.9L12.1 9.1L11.6 9.2L11.1 9.1L10.4 9.1L10.1 8.5L9 8.4L8.5 8.2L8.1 7.7L7.9 7.2L8.4 6.9L9 6.5L9.9 6.4L10.7 6.2L10.7 5.7L9.7 5.8L9.1 5.8L8.4 5.9L7.5 5.7L6.6 5.2L7.4 5L8.6 4.7L9.1 4.7L10.2 4.9L9.7 4.6L9 4.4L8.1 3.9L7.4 3.7L8.6 3.4L9.4 3.1L10.1 2.6L10.6 2.5L11.6 2.3L12.2 2.3L13 2L13.9 2.1L14.5 2.3L15.4 2.3L16.3 2.5L16.8 2.5L18 2.7L19.1 2.7L20.2 2.7L21.1 2.9L21.7 2.9L22.7 3.1L23.6 3.3L24.2 3.4L24.7 3.2L25.3 3L26.2 3.1L27 2.8L27.9 2.7L28.7 2.8L29.2 2.6L30.1 3.1L30.9 2.7L31.6 3L32.5 2.9L33.4 3.1L34.7 3.3L35.4 3.4L36 3.4L36.7 3.7L35.9 3.9L36.9 4.1L38.4 4L38.9 3.9L39.5 4.2L40.1 4L39.5 3.7L40.6 3.5L41.5 3.6L42 3.9L42.7 3.8L43.6 4.1L44.5 4L45.3 4L46.6 3.8L46.6 4.3L47 3.8L47.6 3.3L47.1 3L46.4 2.7L46.4 2.1L47.1 1.7L47.8 1.8L48.4 2L49.2 2.7L48.7 2.9L49.7 3.1ZM36.6 1L37.5 1.1L38.3 1.4L38.9 1.1L39.4 1.3L39.9 1.9L39.8 1.1L40.3 1L40.8 1.1L41.4 1.3L41.8 1.8L42.9 2.5L43.9 2.8L42.9 3.1L42.1 3.4L41.1 3.2L40.5 3.3L39.4 3.5L37.8 3.6L37 3.6L36 3.2L35.5 3.2L34.8 2.8L36 2.6L36.8 2.7L37.5 2.6L36.5 2.4L35.3 2.5L34.5 2.5L35.5 2.1L34.6 2.1L33.7 1.9L34.5 1.3L36 0.9L36.6 1ZM57.6 1.1L57 1.2L56.4 1.2L55.8 1.3L55.1 0.9L56.6 0.7L57.6 1.1ZM51.9 1L52.9 0.9L54.3 0.7L55.2 1.3L56.2 1.5L56.8 1.3L58 1.5L58.8 1.8L59.9 1.9L60.4 2.3L61.8 2.5L62.3 2.7L62.8 3.2L61.8 3.5L63.1 3.9L64 4L64.8 4.5L65.6 4.5L64.5 5.6L63.8 5.3L62.9 4.8L62.2 4.9L62.7 5.5L63.5 5.8L64.1 6.4L63.2 6.7L61.8 6.3L62.6 6.7L63.2 7.1L61.7 7L60.5 6.7L59.9 6.4L59.2 6L58.4 5.7L56.8 6L56.7 5.4L57.8 5.4L58.9 5.3L58.9 4.8L59.6 4.3L58.4 3.6L57.3 3.4L57.1 2.9L56.6 2.9L56.1 2.7L54.8 2.9L52.8 2.8L51.6 2.6L50.7 2.5L50.1 2.1L49.9 1.5L50.3 1L50.9 0.8L52.3 0.7ZM44.2 0.6L44.9 0.8L45.9 0.7L46.4 1.4L46.3 1.9L45.4 2.1L44.8 2L43.1 1.4L44.2 1.3L43.6 0.9L44.2 0.6ZM48.2 1.2L47.6 1.7L47 1.6L46.6 1.1L46.9 0.6L47.5 0.5L48.7 0.5L49.7 0.6L48.9 1.1L48.2 1.2ZM33.1 2L31.6 2.3L30 1.7L30.7 1.1L30.6 0.4L32.5 0.3L33.3 0.4L34.7 0.5L35.2 0.6L35.8 0.8L35.1 1L33.8 1.4L33.1 1.8ZM132 2.4L129.8 2.4L128.7 2L129.2 1.5L130.2 0.8L129.7 0.7L131.1 0.2L132.1 0L134 0L135.8 0L136.8 0L137.9 0L135.9 0L134.2 0L132.5 0.4L131.7 0.9L130.8 1.5L132 2.4ZM47.4 0L48 0L49.1 0L49.6 0L50.1 0L51.2 0L52 0L52.9 0L54 0L54.9 0L55.5 0L54.5 0.3L53.8 0.2L52.2 0.3L51 0.3L50.1 0.3L48.7 0.1L47.8 0L46.7 0L46 0L47.4 0ZM159.4 0L160.1 0L161.7 0L163 0L161.2 0.3L162.3 0.7L162.8 0.6L163.3 0.8L164.2 0.7L166 0.8L168.4 1.1L169.7 0.8L170.5 0.8L171.4 1.1L171.4 1.7L172.1 2.1L172.9 2.3L173.5 1.8L174.4 2L175.3 1.9L176.4 2L177.7 2L177.3 1.4L178 1.2L183.1 1.6L185 2.3L187.2 2.2L188.3 2.3L188.8 2.5L189.4 3.1L190.2 3L191.1 3L192.2 3.1L193.2 3L194.2 3.5L194.9 3.3L194.4 3L196.5 2.9L197.6 2.8L199.2 3.1L200 3.4L200 5.6L199.3 5.8L198.6 5.8L199.1 6.1L199.7 6.7L198.5 6.9L197 7.4L196.5 7.4L195.6 7.8L194.8 8.1L193.8 8L192.4 8.5L191.6 8.5L190.9 8.4L190 9.3L190.7 9.7L190.6 10.5L190.1 10.5L189.8 11L189.1 11.5L188.9 12.1L188.1 12.2L187.9 12.8L187.1 13.3L186.7 12.1L186.4 10.9L186.6 10.1L187.1 9.8L188 9.4L189 8.7L189.9 8.1L190.9 7.7L191.4 6.9L190.7 7L189 8L188.5 7.3L187.1 7.5L185.7 8.5L184.9 9L184 9L183.2 8.5L182.5 8.8L180.8 8.7L179 8.9L177.2 10L175.1 11.3L175.9 11.3L176.8 11.8L177.7 11.6L178.5 12.2L178.1 13.2L178.1 13.9L177.8 14.8L177 15.6L176 16.6L175.3 17.2L174.2 17.9L173.5 17.6L172.7 18L172.2 18.4L172.1 19L171.5 19.3L170.9 19.6L171.3 20.2L171.8 20.9L171.9 21.9L171.2 22.3L170.3 22.6L170.3 21.8L170.1 21.3L170.1 20.7L169.6 20.7L169.6 20.2L169.6 19.7L169 19.5L168.3 19.6L167.3 20.1L167.4 19.6L167.9 19.2L167.1 19.1L166.5 19.5L165.6 19.9L165.6 20.5L166.1 20.9L167.1 20.6L167.6 20.8L168.1 21.1L167.3 21.3L166.5 21.9L166.8 22.6L167 23.1L167.3 23.6L167.7 24.1L167.4 24.6L167.8 25.1L167.6 26L166.9 26.6L166.4 27.4L165.9 28L165.2 28.5L164.4 29L163.8 29.1L163.2 29.1L162.1 29.7L161.5 29.8L161.4 30.4L160.9 30L160.3 29.6L159.3 30.2L158.8 30.7L159.1 31.7L159.6 32.4L160.1 32.7L160.5 33.2L160.7 34.2L160.7 35.2L160.2 35.6L159.6 35.9L159.1 36.4L158.4 36.9L158.4 36.2L157.5 35.8L157 34.9L156.5 34.6L156 34.7L156.1 34.2L155.6 34.2L155.6 34.8L155.3 35.6L155.1 36.1L155.5 36.6L155.7 37.1L156.1 37.9L156.7 38.2L157.2 38.6L157.5 39.3L157.5 39.8L157.7 40.3L157.9 40.8L157 40.6L156.3 40.1L155.9 39.5L155.9 39L155.7 38.3L155.3 37.6L154.7 37L154.8 36.1L154.9 35.3L154.7 34.4L154.3 33.4L154.2 32.7L153.6 32.5L153 32.9L152.3 32.8L152.5 32.1L152.4 31.5L152 30.9L151.3 30.2L151.1 29.6L150.8 29L150.3 29L150.2 29.5L149.7 29.5L149 29.6L148.3 29.7L148.1 30.5L147.3 30.8L146.6 31.5L145.7 32.2L144.9 32.8L144.5 33.3L144.6 34L144.4 35L144.4 35.9L143.8 36.4L143.3 37.1L142.6 36.7L142.3 35.9L142.1 35.4L141.6 34.6L141.5 33.9L140.9 32.8L140.6 31.7L140.5 31L140.5 30.3L140.4 29.8L139.5 30.1L138.4 29.4L137.9 28.5L137.3 28L136.9 27.5L135.9 27.6L134.9 27.7L134.2 27.7L133.1 27.6L132.5 27.4L131.9 27.4L131.7 26.7L131 26.7L130.4 27L129.7 26.8L129.2 26.3L128.6 26.2L128.3 25.7L127.8 24.9L127.2 24.8L126.7 25L126.9 25.8L127.1 26.3L127.9 26.8L127.8 27.3L128.1 27.8L128.3 27.2L128.7 27.7L128.7 28.2L129.2 28.2L129.7 28.2L130.4 27.9L131.2 27.2L131.3 27.8L131.9 28.4L132.6 28.6L133 29.1L133 29.6L132.5 30.3L132 30.7L131.4 31.3L130.9 31.7L130.4 32.2L129.8 32.4L129.1 32.6L128.4 33.2L127.5 33.5L127 33.9L126.3 34.1L125.5 34.3L125 34.6L124.5 34.7L124 34.3L123.8 33.4L123.7 32.9L123.7 32.3L123.2 31.8L122.9 31.3L122.7 30.8L122.1 30.4L121.7 29.8L121.7 29.1L121.4 28.5L120.8 28.2L120.7 27.7L120.1 26.9L119.5 26.1L119.4 25.6L119 26.2L118.4 25.9L118 25.1L118.2 25.7L118.5 26.3L118.9 27.1L119.3 27.8L119.8 28.4L120.4 29.3L120.7 30L120.6 30.7L120.8 31.3L121.3 31.7L121.7 32.3L121.8 32.8L122.9 33.6L123.5 34.3L124.1 34.8L124 35.3L124.5 35.9L125.3 35.7L125.9 35.7L126.4 35.5L126.9 35.3L127.4 35.3L127.9 35.2L128.4 35L128.4 35.5L128.2 36L128.1 36.6L127.8 37.2L127.5 37.9L127 38.7L126.5 39.3L125.9 40.1L125.3 40.5L124.5 41.1L124 41.5L123.4 42.2L122.7 42.8L122.3 43.5L122 44.1L121.5 44.9L121.9 45.5L121.8 46.1L122 46.7L122.2 47.3L122.5 48.2L122.5 48.7L122.6 49.6L122.5 50.2L121.9 51L121.4 51.2L120.8 51.4L120.2 52L119.6 52.5L119.3 53.1L119.7 53.8L119.7 54.5L119.7 55.1L119 55.5L118.3 55.8L118.2 56.5L118 57.4L117.5 57.9L117 58.6L116.1 59.5L115.3 60.1L114.7 60.3L114 60.4L113.1 60.4L112.5 60.5L112 60.7L111.5 60.8L110.9 61L110.2 60.6L110 59.8L110.1 59.3L109.8 58.7L109.1 57.5L108.5 56.7L108.3 56.2L108 54.9L108 54.3L107.7 53.7L107.1 52.6L106.6 51.7L106.5 50.9L106.5 50.4L106.7 49.9L106.9 49.2L107.4 48.6L107.6 47.9L107.4 47.4L107.2 46.8L107.2 45.9L106.8 45.2L106.6 44.5L106.2 43.9L105.6 43.3L104.9 42.3L105.2 41.5L105.2 41L105.4 40.4L105.2 39.6L104.7 39.2L104.1 39.2L103.3 39.3L102.8 38.5L102 38.2L101.5 38.2L101 38.3L99.7 38.7L98.9 39L98.4 38.9L97.8 38.8L96.8 38.9L95.8 39.3L95 39L94.5 38.6L94 38.3L93.5 37.9L92.8 37.3L92.6 36.7L92.2 36.2L91.8 35.7L91.3 35.3L90.8 34.9L90.6 34.4L90.5 33.7L90.7 33L90.8 32.4L91 31.6L91 31.1L91 30.5L90.5 30L90.6 29.5L90.9 28.9L91.4 28.1L91.8 27.4L92.3 26.9L92.7 26.3L93.5 26L94.2 25.5L94.7 25L94.5 24.3L94.8 23.6L95.7 22.9L96.2 22.7L96.5 22.1L97.1 21.8L98 22L98.6 22.1L99.3 21.8L99.9 21.7L100.8 21.3L101.8 21.2L102.7 21.2L103.5 21L104.1 21L104.7 21.1L105.3 20.9L106.1 21.1L105.9 21.7L106 22.3L105.7 22.9L106.2 23.2L107 23.4L107.7 23.5L108.5 23.7L108.7 24.2L109.2 24.3L110 24.6L110.6 24.9L111.1 24.5L111 24L111.6 23.5L112.7 23.5L113.3 23.9L113.8 23.9L114.7 24.1L115.3 24.3L115.8 24.4L116.5 24.3L117.2 24.1L117.8 24.5L118.3 24.4L118.8 24.5L119.3 23.8L119.5 23.3L119.7 22.8L119.9 22L119.9 21.5L119.3 21.2L118.1 21.6L117.6 21.3L117 21.3L116.5 21.6L116 21.3L115.4 21.3L115 20.7L114.9 20L115.2 19.2L116 19.2L117.3 18.8L118 18.5L118.6 18.3L119.5 18.3L120.5 18.7L121.3 18.9L122 18.8L123.1 18.6L123 18L122.4 17.7L121.5 17.1L120.9 16.9L120.4 16.5L121.2 16L121.7 15.5L121.2 15.5L120.4 15.7L119.9 15.8L119.4 16L120.3 16.4L119.6 16.7L118.8 17L118 16.5L118.7 16.2L117.6 15.9L117.1 15.8L116.4 16.5L115.9 17.4L115.4 18L115.6 18.5L116.1 18.7L115.3 18.9L114.6 19.4L114.1 19L113.2 19.1L112.7 19.2L113 19.9L113.3 20.4L112.8 20.6L112.9 21.4L112 21.2L111.7 20.4L111.2 19.8L110.8 19.3L110.8 18.7L110.5 18.2L109.7 17.9L108.9 17.5L108.4 17.1L108.3 16.6L107.8 16.8L107.7 16.3L106.8 16.5L107 17.2L107.5 17.5L108.4 18.4L109 18.5L109.7 19L110.2 19.2L109.4 19.2L109.5 19.8L108.9 20.6L108.8 20.1L108.6 19.4L107.8 19L107.2 18.7L106.7 18.5L106.2 18.1L105.7 17.3L104.9 17L104.4 17.4L103.6 17.7L102.5 17.6L101.7 17.7L101.7 18.4L101.2 18.8L100.5 18.9L100.1 19.4L100.1 20.1L99.6 20.8L98.8 21.3L98.1 21.3L97.6 21.3L97 21.7L96.5 21.5L95.9 21.1L95.3 21.1L95.1 20.4L94.8 19.8L95.1 19L95 18.4L94.8 17.8L95.6 17.4L96.2 17.5L97 17.5L97.6 17.6L98.9 17.5L99.3 16.1L98.8 15.5L97.5 15L98.2 14.5L99.1 14.6L98.9 14L99.5 14.3L100.7 13.8L101.4 13.3L102.1 13L102.6 12.2L103.4 11.9L103.9 11.8L104.4 11.8L104.9 11.7L104.7 11.1L104.5 10.3L105.2 9.9L105.9 9.6L105.7 10.1L105.4 10.8L105.5 11.3L106.1 11.5L106.6 11.6L107.6 11.6L108.2 11.6L109.1 11.4L109.8 11.2L110.3 11.3L110.9 11.4L111.8 11L111.7 10.5L112 9.8L112.5 9.6L113 10L113.5 9.6L113 9.1L113.7 8.6L114.4 8.5L115 8.6L115.5 8.6L116.2 8.3L115.6 8.1L114.6 8.1L113.6 8.3L112.7 8.4L111.8 7.9L112 7.4L111.7 6.9L112.5 6.2L113.7 5.6L113.3 5L112.3 5.2L111.8 5.5L111 6.3L109.9 6.8L109.5 7.6L110.4 8.3L109.9 8.9L109.3 9L109.1 10L108.8 10.5L108.1 10.4L107.8 10.9L107.2 10.9L107 10.4L106.5 9.8L106.1 9L104.7 9.3L103.9 9.4L103.1 9.1L102.9 8.5L102.8 7.2L103.3 6.9L104.8 6.4L105.8 5.8L106.9 5.1L108.2 4L109.1 3.6L110.7 2.9L111.9 2.6L112.8 2.7L113.6 2.2L114.7 2.2L115.6 2.1L117.4 2.5L116.7 2.7L117.3 3L117.9 2.8L118.8 3.2L120.3 3.3L122.4 3.9L122.8 4.6L122.2 4.9L121.3 5L118.8 4.6L119.3 5.1L119.4 5.9L120.1 6.1L120.6 6.2L120.3 5.7L122 5.8L122.5 5.7L123.4 4.7L123.9 4.8L124.4 5L124.3 4.2L124.1 3.6L125.7 3.7L125.3 4.4L126.6 4.5L127.9 3.9L129.8 3.4L130.3 3.4L129.7 3.8L130.4 3.8L131.8 3.6L132.7 3.4L133.3 3.7L133.9 3.4L133.4 3L135.3 3L136 3.2L138.1 3.8L137.9 3.3L137.2 3.1L137.1 2.4L138.1 1.7L138.4 1.2L138.9 1.1L140.3 1.2L139.9 2L140.4 2.6L140.3 3.3L140.9 3.7L139.6 4.8L140.2 4.9L141.1 4.6L141.7 4L141.6 3.3L141 3.3L141.3 2.4L140.6 2L141.6 1.6L142.4 2.1L143.1 1.5L144.3 1.5L145.3 1.8L144.8 1.3L144.7 0.8L145.7 0.6L147 0.7L148.2 0.6L148.4 0L149.1 0L150.1 0L151.6 0L153.3 0L155 0L156 0L156.7 0L158 0L158.9 0L158.2 0L159.4 0ZM127.3 18.7L127.8 19.2L127.4 19.8L127.2 20.4L127.9 20.9L129 21.3L129.9 21.1L129.9 20.6L129.9 20L129.6 19.5L129.4 19L129.9 19.1L130.4 18.9L129.8 18.3L129.3 18.8L129.1 18.3L128.5 17.7L128.3 17.2L128.5 16.5L129 16.4L129.5 16.5L129.6 16L128.9 15.7L128.4 15.5L127.8 15.8L127.3 15.9L126.5 16.3L125.9 16.9L126.4 17.4L127 18.4ZM84.9 0L88.4 0L87.4 0L85.3 0L82.3 0L84.5 0L86.2 0L87.3 0L88.5 0L91.2 0L92.9 0L91 0L88.9 0L90.1 0L89.5 0L88.9 0L88 0L89 0L88.5 0L89.2 0.4L88 0.4L88.6 0.7L87.7 0.9L86.9 0.9L87.6 1.3L86.5 1.3L87 1.6L87.7 2L86.9 2.5L85.8 2L85.4 2.7L86.8 2.7L87.6 2.7L86.1 3.2L84.6 3.6L83 3.8L82.3 3.8L81.8 4L81 4.6L79.8 5L78.7 5.2L77.9 5.3L77.4 5.6L77.1 6.4L76.2 6.8L76.4 7.3L75.9 8.3L75.1 8.3L74.3 7.9L73.2 7.9L72.6 7.6L72.3 7L71.3 6.3L71 5.5L70.2 4.9L70 4.3L70.6 3.7L71.4 3.5L71.7 2.8L71.1 3L70.3 3.2L69.6 3L69.8 2.3L70.3 2.3L71.4 2.5L70.5 2.1L70 1.9L69.4 2L69.6 1.3L68.8 0.8L68.2 0.2L67.4 0L66 0L64.8 0L63.3 0L61.9 0L61.3 0L60.3 0L61.8 0L62.9 0L60.5 0L59.3 0L61.5 0L63.5 0L62.2 0L62.7 0L64.6 0L65.4 0L66.5 0L68.2 0L69.9 0L70.5 0L72 0L73.3 0L74.1 0L75.3 0L73.9 0L75.9 0L77.8 0L78.5 0L80.5 0L84.9 0Z";

  var state = { lang: "ru", data: null };

  // ------------------------------------------------------------------ #
  // shared links
  // ------------------------------------------------------------------ #

  //: Куда ведёт строка страны и кнопки подписки. Токена подписки на
  //: странице нет и быть не должно: `/api/v1/stats` публикует только
  //: счётчики, а токен в публичном HTML — это токен, опубликованный в
  //: интернете. Строку несёт бот, который проверяет подписку, выдаёт токен
  //: и отвечает шардом этой страны.
  var BOT_URL = "";

  function countryHref(code) {
    if (!BOT_URL) return "";
    return BOT_URL + "?start=" + encodeURIComponent(code);
  }

  //: Кнопки подписки ведут туда же, куда и строки стран: адрес бота —
  //: конфигурация оператора (`bot_username`), и она приходит тем же
  //: эндпоинтом. Пока он не ответил, кнопки держат заглушку в разметке —
  //: букмарклемает браузер только тот, кому и так было некуда идти.
  function wireCtaLinks() {
    var links = document.querySelectorAll("a[data-cta]");
    for (var i = 0; i < links.length; i++) {
      links[i].setAttribute("href", BOT_URL || links[i].getAttribute("href"));
    }
  }

  // ------------------------------------------------------------------ #
  // language
  // ------------------------------------------------------------------ #

  //: The page's own Russian, captured before English overwrites anything.
  //: Russian is the *source* language rather than one more entry in the
  //: dictionary, which is what makes "restore from markup" correct — the copy
  //: lives in the HTML, and duplicating it here would create two versions of
  //: the page's only always-correct text.
  //:
  //: Snapshotting is the fix for a specific failure: switching back to Russian
  //: after English had already replaced the innerHTML left every static string
  //: in English while the country names went Russian, i.e. a half-translated
  //: page — the exact complaint this page exists to answer.
  //: Without the snapshot there is nothing to restore to, because the original
  //: text is gone from the DOM the moment English lands.
  var ORIGINALS = {};
  (function snapshot() {
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i++) {
      ORIGINALS[nodes[i].getAttribute("data-i18n")] = readText(nodes[i]);
    }
  })();

  //: Text does not always live in the same place. For `<title>` and every
  //: ordinary element it is the element's content; for `<meta name=…>` it is
  //: the `content` attribute, where `innerHTML` reads and writes nothing at
  //: all. Writing "" there is the reason this indirection exists: a naive
  //: `snapshot()` stores `<meta>`'s inner HTML, which is always empty, so
  //: switching back to Russian blanks the page's description instead of
  //: restoring it — a missing description silently costs the page its
  //: snippet, and nothing on screen shows it went.
  function readText(el) {
    if (el.tagName === "META") return el.getAttribute("content") || "";
    return el.innerHTML;
  }

  function writeText(el, text) {
    if (el.tagName === "META") {
      el.setAttribute("content", text);
      return;
    }
    el.innerHTML = text;
  }

  function applyLang(lang) {
    state.lang = lang;
    var table = STRINGS[lang];
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var key = el.getAttribute("data-i18n");
      // Russian restores the snapshot; English replaces it. A missing key in
      // either direction is a no-op, which is the safe failure: an untranslated
      // element is a rough edge, whereas a blank one is a hole in the page.
      var text = (table && table[key]) || ORIGINALS[key] || "";
      if (!text) continue;
      writeText(el, text);
    }
    document.documentElement.setAttribute("lang", lang);
    var buttons = document.querySelectorAll(".lang button");
    for (var j = 0; j < buttons.length; j++) {
      var button = buttons[j];
      var chosen = button.getAttribute("data-lang") === lang;
      button.setAttribute("aria-pressed", chosen ? "true" : "false");
    }
    // The pool has probably already rendered; its labels are language-aware,
    // so a switch has to redraw them or the page ends up half-translated.
    if (state.data) render(state.data);
  }

  function initialLang() {
    // An explicit `?lang=` wins over everything. Two reasons, in order: a
    // shared link should land on the language it was shared in, and it makes
    // the switcher verifiable by a tool that cannot click.
    var match = /[?&]lang=([a-z]{2})/i.exec(location.search);
    if (match && STRINGS[match[1].toLowerCase()] !== undefined) {
      return match[1].toLowerCase();
    }
    // Prefer the visitor's own language only when it is one we actually have:
    // `navigator.language` is a locale prefix we may not ship, and guessing at
    // "fr" or "de" should not silently leave the page untranslated.
    var pref = (navigator.language || "").toLowerCase();
    return pref.indexOf("en") === 0 ? "en" : "ru";
  }

  function wireLang() {
    var buttons = document.querySelectorAll(".lang button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function () {
        applyLang(this.getAttribute("data-lang"));
      });
    }
    var start = initialLang();
    if (start !== "ru") applyLang(start);
  }

  function t(key) {
    var table = STRINGS[state.lang];
    if (table && table[key]) return table[key];
    // Fall back to English and, failing that, to the key itself. An empty
    // string is the one wrong answer: it would delete a label rather than
    // mis-translate it, and "11" with no word beside it is not a statistic.
    return (STRINGS.en && STRINGS.en[key]) || key;
  }

  function countryName(code) {
    var names = COUNTRY_NAMES[state.lang] || COUNTRY_NAMES.ru;
    return names[code] || names[code.toUpperCase()] || code;
  }

  /// Число в локали читаемой страницы.
  ///
  /// Локаль берётся из `state.lang`, а не из `navigator.language`: язык
  /// страницы уже выбран (и мог быть выбран явно через `?lang=`), и числа
  /// обязаны следовать за ним, а не за настройкой браузера, которая с ним
  /// может не совпадать. EN-страница с `59 013` и `0,13%` — русский
  /// разделитель разрядов и запятая посреди английского текста — читалась
  /// как перечисление двух чисел.
  function locale() {
    return state.lang === "en" ? "en-US" : "ru-RU";
  }

  function num(n) {
    return Number(n).toLocaleString(locale());
  }

  /// Доля в процентах, разделитель дробной части — по локали.
  /// `toFixed` всегда пишет точку; для `ru-RU` она заменяется на запятую.
  function percent(value) {
    var text = value.toFixed(2);
    return (state.lang === "en" ? text : text.replace(".", ",")) + "%";
  }

  function flag(code) {
    return FLAGS[(code || "").toUpperCase()] || "🌐";
  }

  /// Счётная форма существительного: `21 узлов` разобьёт глаз. Одна функция
  /// вместо `pool.unit` в словаре: форма зависит от числа, а не от языка.
  function unit(n) {
    n = Number(n) || 0;
    if (state.lang === "en") return n === 1 ? "node" : "nodes";
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return "узел";
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "узла";
    return "узлов";
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ------------------------------------------------------------------ #
  // stats
  // ------------------------------------------------------------------ #

  var host = document.getElementById("stats");
  if (!host) return;

  // The bot endpoint is fetched first and the pool second, and the order is
  // the point: a country card's href is built during `render`, so resolving
  // the bot URL afterwards would draw the first pass without links and then
  // redraw it — a visible flash of dead cards on a slow connection.
  //
  // A failure here is not an error the visitor needs to see. An unconfigured
  // install, or a `/api/v1/bot` that is down, means the cards stay plain
  // `<div>`s: everything else on the page still renders, which is strictly
  // better than an error banner over a pool that is perfectly healthy.
  fetch(host.dataset.botEndpoint, { headers: { accept: "application/json" } })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (d) {
      var name = (d && d.username) || "";
      BOT_URL = name ? "https://t.me/" + name : "";
      wireCtaLinks();
      loadPool();
    });

  function loadPool() {
    fetch(host.dataset.endpoint, { headers: { accept: "application/json" } })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (d) {
        state.data = d;
        render(d);
      })
      .catch(function (err) {
        host.innerHTML =
          '<p class="error">' + escapeHtml(t("stats.error")) + " (" +
          escapeHtml(String(err)) + "). <a href='/healthz'>" +
          escapeHtml(t("pool.retry")) + "</a>.</p>";
      });
  }

  function render(d) {
    var f = d.funnel || {};
    var raw = f.raw || 0;
    var kept = f.http || 0;

    // Сводная строка — три числа одного отношения: сколько вошло, сколько
    // осталось, какая доля. Пишутся в отдельные узлы разметки, а не в
    // `#stats`, потому что сводка стоит выше воронки и не должна исчезать,
    // когда пул перерисовывается.
    var into = document.getElementById("yield-in");
    if (into) into.textContent = raw ? num(raw) : "—";
    var out = document.getElementById("yield-out");
    if (out) out.textContent = raw ? num(kept) : "—";
    var pct = document.getElementById("yield-pct");
    if (pct) {
      pct.textContent = raw
        ? percent(kept / raw * 100)
        : "—";
    }

    renderCull(f);
    renderPool(d);
    renderMap(d);

    var gen = document.getElementById("pool-gen");
    if (gen) gen.textContent = d.generation || "";
  }

  /// Ступени отсева.
  ///
  /// Дорожка — доля от ПРЕДЫДУЩЕЙ ступени, и это не косметика. При доле от
  /// входа пять полос из шести имели бы ширину 0.3–13%, а последняя —
  /// 0.003%, то есть невидимую: читалась бы одна полоса, а остальные пять
  /// были бы точками на её фоне. Доля от предыдущей ступени отвечает на
  /// вопрос «сколько прошло ИМЕННО здесь», и все значения попадают в
  /// диапазон, который видно. Общая доля при этом не теряется — она стоит
  /// сверху страницы отдельным числом.
  var STEPS = [
    ["cull.raw", "raw"],
    ["cull.parsed", "parsed"],
    ["cull.tcp", "tcp"],
    ["cull.tls", "tls"],
    ["cull.config", "config"],
    ["cull.http", "http"]
  ];

  function renderCull(f) {
    var box = document.getElementById("cull-body");
    if (!box) return;
    // Ключ именно `cull.empty`, а не `cull.loading`: последний стоит в
    // разметке как `data-i18n`, и продублировать его в русском словаре
    // значило бы завести вторую русскую копию одной строки — ровно то, что
    // запрещает двусторонний тест словарей.
    if (!f || !f.raw) {
      box.innerHTML = '<p class="caption">' + escapeHtml(t("cull.empty")) + "</p>";
      return;
    }
    var prev = 0;
    var rows = STEPS.map(function (pair, i) {
      var key = pair[0];
      var field = pair[1];
      var n = f[field] || 0;
      // Первая ступень — вход, у неё нет предыдущей: полоса во всю ширину.
      var share = i === 0 ? 100 : prev > 0 ? (n / prev) * 100 : 0;
      var width = n > 0 ? Math.max(1, share) : 0;
      var lost = i === 0 ? 0 : Math.max(0, prev - n);
      var last = i === STEPS.length - 1;
      prev = n;
      return (
        '<div class="step" data-p="' + (last ? "1" : "0") + '" data-stage="' + field + '">' +
        '<div class="idx">' + (i + 1) + "</div>" +
        '<div class="what">' + escapeHtml(t(key)) + "</div>" +
        '<div class="bar"><div class="track"><i style="width:' +
        width.toFixed(2) + '%"></i></div></div>' +
        '<div class="drop">' +
        (lost ? "−" + num(lost) : "") + "</div>" +
        '<div class="kept">' + num(n) + "</div>" +
        "</div>"
      );
    }).join("");
    box.innerHTML = '<div class="cull">' + rows + "</div>";
  }

  function renderPool(d) {
    var box = document.getElementById("stats");
    if (!box) return;

    var html =
      '<div class="pool">' +
      '<div><div class="v">' + (d.verified != null ? num(d.verified) : "—") + "</div>" +
      '<div class="k label">' + escapeHtml(t("pool.verified")) + "</div></div>" +
      '<div><div class="v">' + (d.known != null ? num(d.known) : "—") + "</div>" +
      '<div class="k label">' + escapeHtml(t("pool.known")) + "</div></div>" +
      '<div><div class="v">' +
      ((d.by_country || []).filter(function (r) {
        return r.name && r.name !== "unknown";
      }).length) + "</div>" +
      '<div class="k label">' + escapeHtml(t("pool.countries")) + "</div></div>" +
      "</div>";

    var countries = (d.by_country || [])
      .filter(function (r) {
        return r.name && r.name !== "unknown";
      })
      .sort(function (a, b) {
        // Наибольшая ротация первой, затем по алфавиту: порядок страницы
        // должен быть байт-стабильным между загрузками.
        return b.n - a.n || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
      });

    if (countries.length) html += countryCards(countries);

    html += protocolBars(d.by_protocol);

    if (d.generation) {
      html +=
        '<p class="caption">' + escapeHtml(t("pool.gen.note")) + " <code>" +
        escapeHtml(d.generation) + "</code>" + escapeHtml(t("pool.gen.after")) + "</p>";
    } else {
      html +=
        '<p class="caption">' + escapeHtml(t("pool.empty")) + " <code>sing-box</code>.</p>";
    }

    box.innerHTML = html;
  }

  /// Страны — ранжированный список, а не сетка карточек.
  ///
  /// Двенадцать одинаковых плиток заставляют читать каждую; колонка чисел
  /// читается сканированием, а это ровно то, что здесь нужно: сравнить
  /// глубину ротации по странам. Полоса под строкой даёт распределению
  /// форму, которую столбик чисел не даёт.
  function countryCards(rows) {
    var max = rows.reduce(function (m, r) { return Math.max(m, r.n); }, 0);
    var cards = rows.map(function (r) {
      var code = String(r.name).toUpperCase();
      var width = max ? Math.round((r.n / max) * 100) : 0;
      var href = countryHref(code);
      // Якорь, когда есть куда идти, и обычный div, когда нет: `BOT_URL`
      // пуст на чистой установке, а `<a href="">` перезагружает страницу —
      // то есть каждая страна выглядит сломанной ссылкой.
      var open = href
        ? '<a class="country" href="' + escapeHtml(href) + '" data-cc="' +
          escapeHtml(code) + '"'
        : '<div class="country" data-cc="' + escapeHtml(code) + '"';
      var close = href ? "</a>" : "</div>";
      var attrs =
        (r.n === max ? ' data-top="1"' : "") + (r.n <= 1 ? ' data-thin="1"' : "");
      return (
        open + attrs + ">" +
        '<span class="flag">' + flag(code) + "</span>" +
        '<span class="name">' + escapeHtml(countryName(code)) + "</span>" +
        '<span class="lead" aria-hidden="true"></span>' +
        '<span class="count">' + num(r.n) +
        '<span class="unit">' + escapeHtml(unit(r.n)) + "</span></span>" +
        '<span class="track"><i style="width:' + width + '%"></i></span>' +
        close
      );
    }).join("");

    // Подсказка появляется только когда строки действительно ссылки:
    // инструкция под неактивным списком — это то, что посетитель не может
    // выполнить, и это хуже, чем отсутствие инструкции.
    var hint = countryHref("XX") && BOT_URL
      ? '<p class="hint">' + escapeHtml(t("pool.country.hint")) + "</p>"
      : "";
    return (
      '<h3 class="label">' + escapeHtml(t("pool.countries.title")) + "</h3>" +
      '<div class="countries">' + cards + "</div>" + hint
    );
  }

  /// Протоколы пула: сколько узлов каждого.
  ///
  /// `""` при пустом списке — секция без строк это заголовок над пустотой.
  /// Протокол — первое, что смотрит читатель, выбирая клиент, и потерять
  /// это значило бы ответить на вопрос «куда вставлять» раньше, чем на
  /// вопрос «что там вообще есть».
  function protocolBars(rows) {
    if (!rows || !rows.length) return "";
    var max = rows.reduce(function (m, r) { return Math.max(m, r.n); }, 0);
    return (
      '<h3 class="label mix-head">' + escapeHtml(t("pool.protocols")) + "</h3>" +
      '<div class="mix">' +
      rows
        .map(function (r) {
          return (
            '<div class="mix-row"><span class="name">' + escapeHtml(r.name) + "</span>" +
            '<span class="visual"><i style="width:' +
            (max ? Math.round((r.n / max) * 100) : 0) + '%"></i></span>' +
            '<span class="n">' + r.n + "</span></div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  /// Карта мира: узел — точка на реальной координате, под ними — контуры
  /// суши, сетка меридианов и звёздная пыль. Точка читается только тогда,
  /// когда под ней видно, где Земля: без контуров это россыпь крапинок.
  /// Суши выровнены той же развёрткой, что и точки, поэтому «декор» здесь
  /// показывается там же, где стоит страна. Радиус растёт с глубиной
  /// ротации, самая глубокая страна получает ореол и кольцо.
  function renderMap(d) {
    var box = document.getElementById("map");
    if (!box) return;
    var rows = (d.by_country || [])
      .filter(function (r) {
        return r.name && r.name !== "unknown" && MAP_POS[String(r.name).toUpperCase()];
      })
      .sort(function (a, b) { return a.n - b.n; });
    if (!rows.length) {
      box.innerHTML =
        '<div class="map-empty">' + escapeHtml(t("map.empty")) + "</div>";
      return;
    }
    var max = rows.reduce(function (m, r) { return Math.max(m, r.n); }, 0);
    var NS = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(NS, "svg");
    // Развёртка 200×75 — естественные пропорции мира (360°×135°): квадратный
    // viewBox сжимал карту в вертикальный столбец посреди широкой панели.
    svg.setAttribute("viewBox", "0 0 200 75");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    // Земля под всем: контуры суши Natural Earth (упрощённый 110m),
    // обрезанный по этой развёртке. За ним — сетка меридианов и
    // параллелей как опора для взгляда, поверх — звёздная пыль.
    if (LAND) {
      var land = document.createElementNS(NS, "path");
      land.setAttribute("d", LAND);
      land.setAttribute("class", "map-land");
      svg.appendChild(land);
    }
    // Опора для взгляда: тонкая сетка меридианов и звёздная пыль.
    // Контур суши уже стоит под ними.
    for (var gx = 20; gx <= 180; gx += 20) {
      var vline = document.createElementNS(NS, "line");
      vline.setAttribute("class", "map-line");
      vline.setAttribute("x1", gx);
      vline.setAttribute("x2", gx);
      vline.setAttribute("y1", 6);
      vline.setAttribute("y2", 69);
      svg.appendChild(vline);
    }
    [28.6, 41.7, 54.8].forEach(function (gy) {
      var hline = document.createElementNS(NS, "line");
      hline.setAttribute("class", "map-line");
      hline.setAttribute("x1", 4);
      hline.setAttribute("x2", 196);
      hline.setAttribute("y1", gy);
      hline.setAttribute("y2", gy);
      svg.appendChild(hline);
    });
    var seed = 42;
    function rnd() {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    }
    for (var si = 0; si < 110; si++) {
      var star = document.createElementNS(NS, "circle");
      star.setAttribute("class", "map-star");
      star.setAttribute("cx", (rnd() * 196 + 2).toFixed(2));
      star.setAttribute("cy", (rnd() * 69 + 3).toFixed(2));
      star.setAttribute("r", (0.1 + rnd() * 0.3).toFixed(2));
      star.setAttribute("opacity", (0.2 + rnd() * 0.45).toFixed(2));
      svg.appendChild(star);
    }

    var top = null;
    rows.forEach(function (r) {
      var code = String(r.name).toUpperCase();
      var pos = MAP_POS[code];
      var x = (pos[0] * 2).toFixed(2);
      var y = (pos[1] * 0.75).toFixed(2);
      // Две окружности: светило — ореол, глубина середняка читается по
      // радиусу. Точка глубоких стран ставится последней (значит, сверху).
      var halo = document.createElementNS(NS, "circle");
      halo.setAttribute("class", "map-halo");
      halo.setAttribute("cx", x);
      halo.setAttribute("cy", y);
      halo.setAttribute("r", Math.max(2.2, 5.8 * Math.sqrt(r.n / max)).toFixed(2));
      svg.appendChild(halo);
      var dot = document.createElementNS(NS, "circle");
      dot.setAttribute("class", "map-dot");
      dot.setAttribute("cx", x);
      dot.setAttribute("cy", y);
      dot.setAttribute("r", Math.max(0.9, 2.6 * Math.sqrt(r.n / max)).toFixed(2));
      svg.appendChild(dot);
      top = { r: r, code: code, pos: [pos[0] * 2, pos[1] * 0.75] };
    });
    // Подпись получает только самая глубокая страна: подпись у каждой точки —
    // шум, у одной — фокус на ответе «где сейчас глубже всего».
    if (top) {
      dotTop(svg, top, NS);
    }
    box.innerHTML = "";
    box.appendChild(svg);
  }

  function dotTop(svg, top, NS) {
    var ring = document.createElementNS(NS, "circle");
    ring.setAttribute("class", "map-ring");
    ring.setAttribute("cx", top.pos[0].toFixed(2));
    ring.setAttribute("cy", top.pos[1].toFixed(2));
    ring.setAttribute("r", "4.6");
    svg.appendChild(ring);
    // Зажим у краёв развёртки: NZ и JP почти касаются правой стенки,
    // FI — верхней. Подпись центрируется в точке и без зажима половина
    // букв уходит за кадр вместе с ореолом, при том что сама точка
    // остаётся видимой.
    var lx = Math.min(Math.max(top.pos[0], 8), 192);
    var ly = Math.max(top.pos[1] - 6, 4);
    var label = document.createElementNS(NS, "text");
    label.setAttribute("class", "map-code");
    label.setAttribute("x", lx.toFixed(2));
    label.setAttribute("y", ly.toFixed(2));
    label.textContent = top.code;
    svg.appendChild(label);
  }

  wireLang();
})();
