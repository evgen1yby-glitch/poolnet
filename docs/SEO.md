# Поиск и распространение

Техническая часть уже сделана:

- `https://poolnet.online/sitemap.xml` — 16 индексируемых URL с `lastmod`,
  `changefreq` и `priority`; `hreflang` RU/EN — в `<head>` каждой страницы;
- `robots.txt` разрешает сайт и закрывает `/admin`, `/api/`, `/metrics`,
  `/status/data`, `/sub/`;
- внутренние ссылки — clean URLs (`/free`, `/proxy`), старые `.html`
  отвечают 301 на канонический адрес;
- на каждой странице есть `title`, `description`, `canonical`, `hreflang`,
  Open Graph/Twitter Card и общая картинка `assets/og.png` 1200×630;
- главная размечена как `WebSite`, страница прокси — как `Dataset`;
- GitHub-репозиторий имеет описание, 11 тем, README на двух языках, скриншоты
  и ссылки на автосписки; поиск GitHub по темам и README работает сразу.

Что нужно сделать владельцу (без этого Google/Яндекс не узнают о домене
быстро):

1. **Google Search Console** — добавить `poolnet.online`, подтвердить DNS
   TXT-записью, отправить `https://poolnet.online/sitemap.xml`.
2. **Яндекс Вебмастер** — добавить домен, подтвердить DNS, отправить sitemap,
   включить «Переобход страниц» для `/` и `/proxy`.
3. **Bing Webmaster Tools** — импортировать из Google Search Console.
4. Через 1–3 дня проверить `site:poolnet.online`; первые результаты обычно
   появляются после обхода, не мгновенно.
5. Для GitHub-поиска достаточно текущих topics (`vpn`, `proxy-list`,
   `free-vpn`, `sing-box`, `xray`, `clash`) и слов в README: «бесплатные
   списки прокси», «free proxy list», «free VPN».

Индексирование не гарантирует позиции: конкуренция в нише высокая, а
репутация нового домена начинается с нуля. Технические сигналы и живое
обновление данных уже дают поисковикам причину возвращаться.
