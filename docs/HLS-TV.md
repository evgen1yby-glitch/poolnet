# HLS TV checker and `/tv` page

Status: implemented on `poolnet.online/tv` (RU) and `/en/tv` (EN).

## Product rule

HLS TV is a catalog of **publicly reachable HLS links**, not a broadcaster and not a
video proxy. PoolNet does not host, cache or rebroadcast video. The page links
out; inline playback is offered only when the stream is HTTPS and permits CORS.
The catalog is separate from the VPN/proxy business and never changes access to
VPN.

## Page

- Route: `/tv` (RU), `/en/tv` (EN); linked from the primary navigation and footer.
- First screen: category, one primary action, link to the verification method.
- Catalog: search and genre categories; country is not a filter.
- Downloads: `/tv/channels.m3u` (all live streams with reserves) and `/tv/channels.json` (full metadata).
  result count, incremental "show more" (60 per step).
- Cards: logo/monogram, name, genre, HLS quality, latency, source count,
  live marker. Web-playable cards open an in-page HLS.js player; other working
  streams open in an external player.
- Verification section: four stages and source status, with attribution and a
  legal note.
- No account, no tracking, no EPG, no user-submitted URLs.

## Sources

The checker fetches a source registry, merges channels and probes each variant.

| Source | Use | Notes |
|---|---|---|
| `iptv-org/api` channels + streams + feeds + logos | canonical metadata, languages, logos, variants | Primary source |
| `iptv-org/iptv` `languages/rus.m3u` | Russian-language channel IDs and fallback URLs | Primary source |
| `iptv-org/iptv` countries `ru`, `by`, `kz` | country playlists | Primary source |
| `Free-TV/IPTV` country playlists RU/BY/KZ | additional free-to-air links | Secondary |
| `ngrch/iptv` `ru.m3u` | Russian regional/long-tail URLs | Secondary |
| `maxviazov/aptv-playlists` `rus.m3u` | curated Russian list with EPG-matched names | Secondary |
| `smolnp/IPTVru` `IPTVru.m3u` | Russian/Belarusian long-tail list | Secondary |
| `ntvampire/IPTV` `index.m3u` | Russian channel list with EPG | Secondary |
| `UtMax/KazRusIPTV` `KazRusIPTV.m3u8` | Kazakhstan/Russia channel list | Secondary |
| `naggdd/iptv` | duplicate Russian list; duplicate URLs become reserves | Reserve source |
| `ttmttm/iptv_2026`, `mftvbox/iptv-org` | iptv-org forks | Not used, duplicates |
| `Hannstcott/SunshineTr` | different regional catalog | Not used |
| `iptv-org/database` | upstream database behind the API | Metadata indirectly |

The registry lives in `scripts/hls_tv_checker.py` (`M3U_SOURCES`). Adding a source
requires a stable public URL, a country hint when the playlist has none, and a
spot-check that it is not a fork of an existing source. Forum aggregators and
SEO playlist sites (4PDA, iptv-rus, smart-iptv, etc.) were reviewed but not
integrated: their links are unstable, unlicensed or already duplicate iptv-org.

## Checker

`scripts/hls_tv_checker.py` is a standalone standard-library Python script.

1. Fetch iptv-org metadata and M3U playlists with size/time limits.
2. Parse M3U attributes (`tvg-id`, logo, group, country) and API feeds.
3. Keep country in `RU/BY/KZ` internally; require Russian language from feeds, the Russian
   language playlist, or a Cyrillic name for BY/KZ. Country is not exposed as a filter.
4. Merge by canonical `tvg-id` and normalized name; drop reserve/quality words.
5. Deduplicate variants by URL and channels by canonical name and final URL.
6. Probe each stream:
   - master and media manifest must be HTTP 200 and `#EXTM3U`;
   - select an ABR variant when present;
   - last segment must answer 200/206 and look like TS/fMP4, not HTML;
   - require no `EXT-X-ENDLIST` for a live channel;
   - record quality, latency, source count, HTTPS, CORS and `web_playable`;
   - keep every surviving source URL as a reserve, not just the first.
7. Write `web/site/tv/channels.json` atomically (current implementation writes
   after the full run).
8. Log source counts, probe counts and errors to stderr.

Run:

```sh
python3 scripts/hls_tv_checker.py \
  --output web/site/tv/channels.json \
  --workers 48 --timeout 7 --max-variants 2
```

At the time of writing the production run produced 709 live unique channels, 294 web-playable, with 0 duplicate URLs and 0 duplicate names. 280 channels have at least one reserve stream. Counts move with each 30-minute run.
BY/KZ are smaller because only Russian-language live streams that survived the
checker are published.

## Categories

The raw groups from API and M3U are normalised into one Russian taxonomy. "Кинозалы", "Кино и сериалы" and "Классика" become **Кино**; "Развлечения"/"Entertainment" become **Развлекательные**; "Познавательные" merge into **Документальные**; "Информационные" into **Новости**; "Основные"/"Популярные"/regional country labels into **Общие**; regional labels into **Региональные**. Unknown groups become **Прочее**, never a raw English/emoji group.

Current distribution: Кино — 180, Общие — 132, Региональные — 78, Новости — 50, Музыка — 50, Документальные — 49, Развлекательные — 44, Детям — 35, Спорт — 30, Религия — 17, Путешествия — 9, Магазины — 6, Сериалы — 5, Культура — 4, Образ жизни — 4, Юмор — 4, Кулинария — 3, Авто — 2, Бизнес — 2, Семья — 2, Наука — 1, Политика — 1, Образование — 1. Countries are metadata only; the page filters by genre, not by country.

## Logos

Every channel has a visual tile. A real logo is published only after an HTTPS fetch returns an image signature (PNG/JPEG/WebP/GIF/SVG); the logo is resolved by `tvg-id` or the source's `tvg-logo`. A dead, HTML or non-image URL is cleared and the card uses a deterministic monogram built from the channel name. Current snapshot: 469 validated logos, 240 monograms. The page also has an `onerror` fallback, so a logo that dies between runs never leaves a broken image.

## Output schema

```json
{
  "generated_at": "2026-10-27T19:54:00+00:00",
  "duration_s": 93.2,
  "sources": [{"id": "iptv-org-api", "ok": true, "items": 31676}],
  "stats": {
    "channels": 709,
    "web_playable": 294,
    "countries": {"RU": 696, "BY": 2, "KZ": 11},
    "with_logo": 469
  },
  "channels": [{
    "id": "Belarus24.by",
    "name": "Belarus-24",
    "country": "BY",
    "country_name": "Беларусь",
    "category": "Новости",
    "quality": "1080p",
    "url": "https://...",
    "latency_ms": 240,
    "web_playable": true,
    "sources": ["iptv-org", "free-tv-belarus"],
    "variants": [{"url": "https://...", "quality": "1080p"}]
  }]
}
```

`web_playable` is a browser capability flag, not a guarantee: CORS can change.
The page falls back to an external-player link on a player error.

## Schedule

`deploy/poolnet-tv.service.in` + `poolnet-tv.timer` run the checker every 30
minutes at `:12` and `:42`, with a 20-minute start timeout. The service writes
only `web/site/tv/channels.json`; it does not touch the VPN pool.

## Verification

- `scripts/site_links.py` includes `/tv` and checks internal links.
- `scripts/site_smoke.py` loads `/tv` and `/en/tv` at 390 and 1440.
- `hub/tests/test_site.py` checks both page routes, canonical/hreflang, and
  English/Russian parity.
- Checker output must have zero duplicate URLs, zero duplicate country/name
  pairs, all channels `live=true`, and a non-empty `web_playable` subset.
- Manual browser check: filters, search, country chips, show more, player open,
  player close, external fallback.

## Risks and boundaries

- **Rights:** public availability is not the same as permission to rebroadcast.
  The page links only; it does not host or proxy. Honor takedown requests.
- **Geo-blocking:** a stream can be live from the checker host and dead for a
  user. Latency/status is a point-in-time result.
- **CORS:** only HTTPS + CORS streams can play inline; everything else is an
  external link.
- **Source rot:** playlists change. The 30-minute run is the freshness contract;
  if a source fails, the page keeps the last published result.
- **Security:** the checker accepts only http(s), uses timeouts and response
  limits, and should reject private/loopback targets if source URLs are ever
  added from untrusted input.
- **No EPG or DRM:** out of scope for this iteration.
