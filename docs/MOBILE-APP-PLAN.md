# PoolNet Mobile — план реализации под ключ

Версия: 2026-10-25. Статус: **draft для утверждения**. Основа: интерактивный
макет `web/site/app/`, текущий API `poolnet.online` и репозиторий
`evgen1yby-glitch/poolnet`.

> **Стоп-гейт.** Это ещё не план «нажимай и кодируй»: четыре ADR ниже должны
> быть закрыты до разработки UI и тем более до обещания кнопки «Подключиться».
> Иначе проект упрётся в лицензию ядра, App Review или юридическую модель.
>
> Документ не является юридической консультацией. Юридические пункты должны
> быть проверены профильным юристом по стране регистрации и рынкам магазинов.

### ADR-гейты (решение до Этапа 0)

- **ADR-001 — кто оператор.** PoolNet — каталог и клиент; узлы сторонние.
  Слово «свой туннель» означает собственный клиент/ядро, не собственные
  серверы. Если оператор всё же появится — меняются liability, privacy,
  стоимость и store-тексты.
- **ADR-002 — туннельное ядро.** Xray-core/MPL или sing-box/GPL; юридическая
  проверка, реальная сборка gomobile, замер RSS в iOS-расширении, fallback
  companion. Без этого никакого «Подключиться» в магазине.
- **ADR-003 — идентичность и лимит ключа.** App Attest/Play Integrity — это
  сигнал целостности, не удостоверение личности. Нужно решить: один активный
  ключ на установку, продление только после истечения, поддержка переустановки
  и CGNAT; иначе «один на устройство» — ложь.
- **ADR-004 — юрисдикция и магазины.** Доступность в странах, требования
  Apple/Google, экспортная классификация, privacy/erasure, ответственность за
  каталог прокси. Результат — матрица стран и подписанные legal-артефакты.

## 1. Решение в одном абзаце

Делаем **нативное приложение PoolNet** (iOS + Android) на Expo/React Native с
собственным VPN-клиентом и туннелем, а не оболочку вокруг браузера. Узлы —
публичные, сторонние; PoolNet не оператор. Первый релиз — закрытая бета:
подключение, выбор страны, бесплатный 7-дневный ключ, каталог прокси, статус
и диагностика. Релиз в магазины — только после ADR-002/004 и App Review /
Google Play VPN policy. Ориентир: **22–28 недель** для команды 4–6 человек;
MVP-компаньон без туннеля — 9–12 недель.

## 2. Границы продукта

### Входит

- iOS 16+ и Android 10+ (уточнить по аналитике; ниже — не отсекать старые
  устройства без причины).
- Подключение к публичным узлам из каталога PoolNet через собственный
  клиент/туннель (PoolNet не владеет узлами и не проксирует трафик).
- Выбор страны/узла, авто-выбор по задержке, избранное.
- Бесплатный ключ на 7 дней: **один активный ключ на установку**, повторная
  выдача только после истечения и не чаще одного раза в 24 часа. Attestation —
  риск-сигнал, не идентификатор личности; веб-фолбэк — один ключ на IP.
- Каталог публичных прокси с поиском, фильтрами и копированием.
- Статус сервисов, методика проверки, условия, приватность.
- RU/EN, тёмная и светлая темы, VoiceOver/TalkBack, Dynamic Type.
- Диагностика: версия, платформа, последний статус, экспорт лога без секретов.

### Не входит в первый релиз

- Аккаунты, синхронизация между устройствами, оплата, подписки Premium.
- Собственные VPN-серверы: PoolNet остаётся каталогом, не оператором.
- Продажа доступа, SLA, обещания скорости/анонимности.
- Настольные приложения и веб-кабинет.
- Автоматическое обновление узлов без согласия пользователя.
- Поддержка протоколов, которых нет в публичном Xray-пейлоаде PoolNet.

### Продуктовые принципы

1. Честность важнее красивой цифры: показываем задержку, срок и состояние.
2. Один акцентный цвет; спокойные поверхности; никаких «магических» экранов.
3. Разрешения запрашиваем в момент пользы, не на старте.
4. Пользователь всегда может отключиться, удалить ключ и данные.
5. Никаких тёмных паттернов, накрутки звёзд и скрытых платежей.
6. Трафик не проходит через PoolNet; это написано в onboarding и legal.

## 3. Роли и сценарии

| Роль | Задача | Критерий успеха |
| --- | --- | --- |
| Новый пользователь | Получить ключ и подключиться | ≤ 60 секунд от установки до статуса «Защищено» |
| Пользователь с ключом | Проверить срок, сменить страну | ≤ 10 секунд, без повторного ввода |
| Пользователь прокси | Найти и скопировать адрес | ≤ 15 секунд, понятная страна/задержка |
| Пользователь с проблемой | Понять, что не так | Диагностика + ссылка на статус |
| Оператор | Увидеть выдачу и отзывы | Нет утечек токенов; есть метрики отказов |

## 4. Пользовательский путь

1. Установка → splash (проверка минимальной версии).
2. Onboarding: «что это», «прямое соединение», «бесплатный ключ» → «Начать».
3. Дом: выбор «Получить ключ» или «У меня есть ссылка».
4. Разрешение VPN (iOS/Android) — в момент первого подключения, с объяснением.
5. Выдача ключа: challenge → 5-секундная пауза → ключ → автоматическое
   добавление подписки.
6. Подключение: статус connecting → connected; при ошибке — причина и
   «Повторить»/«Другой узел».
7. Серверы: поиск, авто, избранное; выбор сразу применяется к туннелю.
8. Прокси: отдельная вкладка, не мешает VPN-соединению.
9. Профиль: ключ, срок, диагностика, legal, GitHub, язык.

## 5. Экраны и состояния

### 5.1 Splash / update gate

- Логотип, проверка `/api/v1/app/bootstrap`.
- Состояния: загрузка, доступно обновление, обязательное обновление,
  нет сети, сервер недоступен.
- Кнопка «Повторить»; ссылка на статус. Не блокировать навсегда без выхода.

### 5.2 Onboarding

- 3 шага (или один экран + 3 смысловых блока), без карусели ради карусели.
- Объяснить: PoolNet — каталог; трафик идёт к стороннему узлу; ключ
  бесплатный; можно отключиться.
- CTA «Начать»; вторичная «У меня есть ключ».
- Показывать один раз; повторно доступно из профиля.

### 5.3 Подключение (Home)

- Состояния: `disconnected`, `preparing`, `connecting`, `connected`,
  `disconnecting`, `error`, `expired-key`, `no-network`.
- Орб — единственный главный CTA; кнопка доступна с клавиатуры и
  VoiceOver/TalkBack, min 56 pt.
- Под орбом: страна/город, задержка, IP, download/upload, время сессии.
- Быстрые действия: «Сменить узел», «Обновить ключ», «Диагностика».
- Ошибка: человеческий текст + технический код под disclosure; не «что-то
  пошло не так».
- Не показывать фейковые скорости/пинг. До первого замера — «—».
- Kill switch — в настройках. Split tunneling — только если он реально
  поддержан платформой и прошёл device-lab; иначе его нет в UI.

### 5.4 Серверы

- Список: страна, город, задержка, загрузка (если есть), избранное.
- Поиск по стране/коду/городу; фильтры «Все / Быстрые / Избранное».
- Авто-выбор: последняя проверка + задержка + страна; объяснить алгоритм.
- Состояния: пусто, ошибка загрузки, устаревший снимок (badge).
- Выбор узла: bottom sheet с деталями и «Подключиться».
- Не обещать «самый быстрый» — только «лучший из доступных сейчас».

### 5.5 Прокси

- Сегменты HTTP/HTTPS/SOCKS5, поиск, пагинация/виртуализация.
- Строка: адрес, страна, протокол, задержка, copy.
- Явно разделить «VPN» и «прокси»: прокси не включают туннель.
- Пустое состояние и подсказка сбросить фильтры.

### 5.6 Ключ

- Состояния: доступен, идёт проверка, выдача, активен, истёк, лимит на
  установку, лимит на IP, сервер недоступен.
- Показывать срок, дату, ссылку, кнопку копирования.
- **Один активный ключ на установку.** Продление — только после истечения,
  не чаще одного раза в 24 часа. App Attest/Play Integrity и хеш установки —
  риск-сигналы; при переустановке/смене устройства — контролируемое
  восстановление через поддержку или повторную аттестацию.
- Веб-версия остаётся один ключ на IP в 24 часа.
- Никаких «5 звёзд за ключ»: это накрутка и плохой UX.
- После выдачи — необязательный GitHub-star CTA, не блокирующий доступ.

### 5.7 Профиль и настройки

- Ключ и срок; тема (system/dark/light); язык (system/RU/EN).
- Kill switch, auto-connect, DNS (system/DoH только если проверено).
- Split tunneling: в iOS v1 **не обещаем** per-app; на Android — только если
  проходит device-lab и store-политику. Если фича не подтверждена — её нет в
  UI, а не «серая» кнопка.
- Показывать матрицу поддержки платформ в настройках/FAQ.
- Диагностика: экспорт redacted-лога, проверка узла, статус.
- Legal: terms, privacy, security, методика; версия и build.
- Удаление локальных данных (ключ, настройки, кэш) с подтверждением.
- Аккаунтов нет → нет «удалить аккаунт»; это указать в privacy.

### 5.8 Системные экраны

- iOS: запрос VPN-конфигурации, Face ID? (не требуется), фоновое уведомление
  о разрыве.
- Android: foreground notification «VPN включён», отключение, always-on.
- Deep links: **не передавать bearer-токен в URL.** Только короткоживущий
  одноразовый claim-code, который приложение обменивает на токен; universal
  link `https://poolnet.online/app/`, associated domains. Токен — в
  Keychain/Keystore, не в clipboard/логах/аналитике.
- Share sheet для ссылки подписки, с предупреждением «ссылка = доступ».

## 6. Визуальная система

Берём язык макета: obsidian, один акцент violet `#8B5CFF`, зелёный только для
состояния connection, тёплые/холодные серые не смешивать.

- Типографика: Inter Tight (display/body), JetBrains Mono (данные, IP,
  латентность). Шкала: 34/28/20/16/14/12/10; tabular-nums для чисел.
- Радиусы: 22 карточки, 16 вложенные, 12 кнопки, 999 pills. Одна система.
- Отступы: 4 pt база; экран 18 pt; карточки 14–20 pt.
- Тени только для bottom sheet/nav; без декоративных.
- Иконки: единый stroke-набор 1.7, 20/24 pt; без emoji.
- Тёмная тема — основная; светлая обязательна до релиза.
- Motion: tab switch — нативный; орб — 220 мс spring на состояние;
  bottom sheet — native; Reduce Motion → crossfade.
- Состояния: skeleton повторяет форму контента; empty с действием; ошибка
  inline; offline badge.
- Accessibility: контраст ≥ 4.5:1, targets ≥ 44 pt, Dynamic Type XL,
  VoiceOver labels, фокус, отключение анимаций.

## 7. Техническая архитектура

### 7.1 Клиент

- Expo SDK (актуальный стабильный) + Expo Router + TypeScript.
- React Native Reanimated, Gesture Handler, FlashList, expo-image,
  expo-haptics, expo-secure-store, MMKV для несекретного кэша.
- TanStack Query для API, Zustand для локального состояния; без глобального
  «app context».
- Нативные модули: iOS Network Extension (Packet Tunnel Provider), Android
  VpnService + foreground service.
- Монорепо: `mobile/` с `app/`, `src/`, `modules/tunnel-ios/`,
  `modules/tunnel-android/`, `assets/`, `scripts/`.
- `prebuild`/CNG; нативные папки не коммитить, если не требуется.

### 7.2 Туннельное ядро — решение до кода

Кандидаты:

1. **Xray-core (MPL-2.0)** — совпадает с `verified-xray` payload PoolNet.
   MPL не означает автоматическую совместимость с App Store: нужны notice,
   исходники изменённых MPL-файлов и юридическое заключение.
2. **sing-box (GPL-3.0 + ограничение имени)** — шире протоколы, но GPL и
   условия App Store конфликтуют без сильной legal-позиции; вероятно,
   приложение должно быть GPL целиком, плюс ограничение имени.
3. **Companion без туннеля** — быстро, но не выполняет обещание «Подключить»
   и рискован для App Review (minimum functionality).

**Рекомендация:** отдельный 2-недельный spike Xray-core + gomobile на обоих
платформах. Критерии прохода: сборка iOS extension, замер RSS на старейшем
поддерживаемом устройстве, юридическое письмо по MPL, реальное подключение
3 протоколов. Решение фиксируется ADR-002. Если spike не проходит — не
обещать подключение в первой версии, выпускать companion и честно писать
«открыть в Happ/Hiddify».

### 7.3 iOS

- Отдельный target `PacketTunnel` с NetworkExtension entitlement.
- App Group для обмена выбранным конфигом/токеном; keychain доступ только
  нужным группам.
- `NEPacketTunnelProvider`, `NEOnDemandRule`, `includeAllNetworks`,
  DNS settings, IPv4/IPv6 routes, MTU.
- Kill switch: `includeAllNetworks`/on-demand; проверить поведение при
  отсутствии сети.
- Split tunneling: маршруты/исключения; если платформа не даёт надёжно —
  скрыть фичу, не имитировать.
- Xray core в extension; память extension ограничена (жёсткий предел iOS
  может убить процесс) — замерить RSS на старом устройстве до UI-разработки.
- `NEVPNManager` для конфигурации + `NEPacketTunnelProvider` для туннеля;
  App Review 5.4 требует именно Network Extension, не приватные API.
- Обязательные строки Info.plist, privacy manifest и required-reason APIs.

### 7.4 Android

- `VpnService`, foreground service с корректным типом для target SDK.
- `Builder.addRoute`, `addDisallowedApplication` (split tunneling),
  `setBlocking` (kill switch), `setUnderlyingNetworks`.
- Всегда-включённый VPN и автозапуск — системные настройки, не принудительно.
- Уведомление с действием «Отключить», канал уведомлений.
- Учитывать OEM-агрессивное убийство процессов; диагностика.
- Network security config, no cleartext для API.

### 7.5 Backend/API

Существующее использовать по максимуму:

- `GET /api/v1/stats`, `/api/status.json`, `/pool/*`, `/api/proxies`,
  `/sub/<token>` — без дублирования.
- Добавить:
  - `GET /api/v1/app/bootstrap?platform=&version=&locale=` — min version,
    feature flags, лимиты, legal/support URLs.
  - `POST /api/v1/app/attest` — обмен App Attest/Play Integrity на короткий
    app-токен; тело не логировать.
  - `POST /api/v1/app/free/claim` — challenge + attestation + install hash;
    ответ: token, expires_at, subscription; 429 с Retry-After.
  - `GET /api/v1/app/nodes` — публичные метаданные узлов (без секретов),
    если нужен выбор до подписки.
  - `GET /api/v1/app/diagnostics` — статус, версия поколения, stale.
- Никаких новых эндпоинтов, отдающих сырые IP/логи/токены.
- Версионирование `/api/v1`, контрактные тесты, ETag/Cache-Control.
- Feature flags: отключение выдачи ключей/туннеля без релиза приложения.

### 7.6 Данные и приватность

- На сервере: `app_installations` (хеш install ID, платформа, дата, статус
  attestation, срок ключа), `app_claims` (уникальность на установку/сутки),
  `app_challenges` (одноразовый nonce, TTL 300 с, привязка к install hash).
- Сырой IP не хранить; для веб-фолбэка — уже существующий хеш. Для erasure —
  удаление по install hash и документированный процесс.
- Токен подписки — bearer; хранить в Keychain/Keystore, не в логах/аналитике.
- Срок хранения: claims 30 дней, diagnostics 7 дней, crash 30 дней; указать
  в privacy.
- Нет рекламных SDK; аналитика opt-in, события без содержимого URL.

### 7.7 Анти-абьюз

- App Attest (iOS) / Play Integrity (Android) + серверная проверка как
  **риск-сигнал**, не как удостоверение личности.
- Один **активный** ключ на установку; повторная выдача только после
  истечения и не чаще 24 часов. Веб — один на IP.
- Серверная идемпотентность (idempotency key), challenge single-use,
  уникальные индексы, транзакция claim + issue; replay-тесты.
- Глобальный суточный бюджет, per-attestation лимиты, 429/Retry-After.
- Не наказывать CGNAT-пользователей: в приложении лимит по установке; в вебе
  оставить честное предупреждение про общий IP.
- Устройства без GMS/attestation — отдельная политика (fallback/ручная
  проверка), а не тихий отказ.
- Ротация ключей, отзыв, журнал без PII.
- Мониторинг всплесков; ручной рубильник на выдачу.

## 8. API-контракты (черновик)

```http
GET /api/v1/app/bootstrap?platform=ios&version=1.2.0&locale=ru
200 {"min_version":"1.2.0","features":{"tunnel":true,"free_key":true},
     "limits":{"claim_hours":24,"wait_seconds":5},
     "urls":{"terms":"…","privacy":"…","status":"…"}}
```

```http
POST /api/v1/app/attest
{"platform":"ios","attestation":"…","key_id":"…","challenge":"…"}
200 {"app_token":"…","expires_in":900}
```

```http
POST /api/v1/app/free/challenge
Authorization: Bearer <app_token>
{"install_hash":"…"}
200 {"challenge":"…","expires_in":300}
```

```http
POST /api/v1/app/free/claim
Authorization: Bearer <app_token>
Idempotency-Key: <uuid>
{"challenge":"…","install_hash":"…"}
200 {"token":"…","expires_at":"…","subscription":"https://…/sub/…"}
429 {"error":"…","code":"claim_cooldown","retry_after":86399}
```

Требования к контракту до Этапа 2:

- OpenAPI-файл — источник истины; клиент генерируется из него.
- `app_token` — короткоживущий подписанный JWT (15 мин), ротация ключей,
  отзыв; body attestation никогда не логируется.
- `challenge` — одноразовый, TTL 300 с, привязан к install hash и app_token;
  повторное использование → 409/400 без деталей.
- Идемпотентность claim: уникальный индекс `(install_hash, day)` + транзакция
  «claim → issue»; повтор с тем же Idempotency-Key возвращает тот же ключ,
  другой ключ — 429.
- Ошибки: единый `{"error": "human", "code": "…", "retry_after": n?}`; не
  раскрывать существование токена/установки.
- DDL: `app_installations(install_hash PK, platform, created_at, last_seen,
  attestation_state, active_token_hash, expires_at)`;
  `app_claims(install_hash, claim_day, token_hash, created_at, PK(install_hash,
  claim_day))`; `app_challenges(nonce PK, install_hash, issued_at, used_at)`.
- Сквозные тесты: replay, конкурентные claim, смена часового пояса, 429,
  истёкший challenge, отозванный app_token.

## 9. Юридическое и магазины

### Apple

- Apple Developer Program, отдельный Bundle ID и App Group.
- Network Extension entitlement; App Review поясняет, зачем VPN и что
  приложение не собирает трафик.
- Privacy Nutrition Label: какие данные (диагностика, идентификатор
  установки) и зачем; «не отслеживать» по умолчанию.
- Export compliance: шифрование — да; стандартное/https; получить
  классификацию у юриста.
- 4.2 minimum functionality: туннель и офлайн-состояния; не только WebView.
- 5.4 VPN apps: Network Extension (`NEVPNManager` для конфигурации +
  `NEPacketTunnelProvider` для туннеля), никаких приватных API.
- Privacy manifest + required-reason APIs; аудит до сборки.
- Скриншоты 6.9"/6.5"/5.5" (по требованиям), иконка 1024, описание, support
  URL, privacy policy, review notes, тестовый ключ.
- Store-readiness gate: отдельный pre-permission экран с объяснением VPN,
  скриншот этого экрана приложить к review notes.

### Google Play

- Google Play Console, App Signing, target API актуальный.
- VPN policy: VpnService, **prominent disclosure до включения**, Data safety
  table, отсутствие скрытой рекламы/слежки.
- Foreground service declaration с точным `foregroundServiceType` для
  target SDK; уведомление с действием «Отключить».
- New personal developer accounts: обязательное закрытое тестирование в
  течение срока из Console (проверить перед планированием), затем production.
- Store listing RU/EN, feature graphic, screenshots phone/tablet; Data safety
  маппинг: diagnostics, install identifier, no location/traffic content.
- Store-readiness gate: disclosure screen, Data safety, FGS declaration,
  privacy policy и тестовый APK/AAB.

### Общее

- Terms, Privacy, Security, методика, abuse contact; юрисдикция и ограничения
  по странам — с юристом.
- Не обещать анонимность/безопасность; предупреждение о сторонних узлах.
- Возрастной рейтинг; доступность; экспортный контроль.
- Политика удаления данных и ответы на запросы.
- Legal workstream (владелец, дата, артефакт): матрица доступности стран,
  ECCN/self-classification, data map + erasure, ответственность каталога
  прокси, trademark search, тексты store-листинга.

## 10. Качество и тестирование

- Unit: парсинг конфигов, state machine туннеля, claim/retry.
- Contract: bootstrap/attest/claim/sub; mock 429/500/timeouts.
- E2E Maestro: onboarding, ключ, смена узла, deep link, ошибка сети,
  навигация и визуальные состояния.
- Native/device-lab (не Maestro): реальное подключение, kill switch, DNS/IPv6
  leaks, captive portal, network handover, background/foreground, VPN
  permission denial. Maestro не доказывает работу туннеля.
- Toolchain pinned: Expo SDK/RN/Node/package manager; CNG vs bare workflow
  решение и воспроизводимый `prebuild`/EAS build.
- iOS/Android matrix: 2 старых + 2 актуальных устройства, малый/большой
  экран, темная/светлая, RU/EN, Dynamic Type XL.
- Сети: Wi-Fi ↔ LTE, captive portal, IPv6-only, DNS failure, throttling,
  airplane mode, сон/пробуждение, входящий звонок.
- Безопасность: OWASP MASVS, MobSF, проверка логов, keychain, jailbreak/root
  (не как единственная защита), MITM на тестовом узле.
- Производительность: cold start < 2 с, память < 150 МБ, батарея — замер
  1 ч idle/active, размер сборки, 60 fps.
- Accessibility: VoiceOver/TalkBack, контраст, targets, Reduce Motion.
- Definition of Done для каждого экрана — из skill `appllama` (состояния,
  motion, safe area, empty/error, store strings).

## 11. CI/CD и релизы

- GitHub Actions: lint, typecheck, unit, contract; PR preview build EAS.
- EAS Build/Submit: подписанные iOS/Android; секреты только в GitHub/EAS.
- Версии: semver + build number; changelog; тег `mobile-vX.Y.Z`.
- EAS Update только JS/assets; туннель — только новый бинарник.
- Каналы: `development` → `preview` (TestFlight/internal) → `production`.
- Staged rollout 5% → 20% → 50% → 100%; стоп по crash-free < 99.5% или
  connect success < 95%.
- Feature flags на сервере: отключить туннель/ключи/прокси без релиза.
- Откат: halt staged rollout + серверный feature flag/kill switch + ускоренный
  hotfix. Магазины не откатывают уже установленные бинарники; предыдущая
  сборка доступна только как новый релиз.
- Миграции БД — заранее, обратная совместимость с прошлой версией.

## 12. Мониторинг и поддержка

- Sentry (crash, non-fatal) с redaction; метрики: install→connect, claim
  success, tunnel failure by reason, key expiry, crash-free.
- Сервер: healthcheck/проверка свежести уже есть; добавить алерты по
  claim 5xx, attestation failures, росту 429, stale generation.
- Статус-страница; support email; форма abuse; SLA ответа 2 рабочих дня.
- В приложении — диагностика и экспорт лога (без токена/IP).
- Privacy requests: удаление локальных данных, ответ по политике.
- Post-launch: еженедельный разбор ошибок, monthly release cadence.

## 13. План по этапам

| Недели | Результат / ворота |
| --- | --- |
| 1–2 | ADR-001…004, legal-письмо, entitlement подан, OpenAPI/DDL, EAS skeleton |
| 3–5 | Дизайн-система, все экраны на mock-данных, RU/EN, light/dark, preview |
| 6–8 | Ключ, app attestation, прокси-каталог, профиль, deep links, closed alpha |
| 9–10 | Spike ядра: сборка, RSS, протоколы, юридическое подтверждение — **stop/go** |
| 11–20 | iOS/Android туннель, reconnect, kill switch, device-lab, beta |
| 21–25 | Hardening, store assets, privacy/disclosure, review, closed testing |
| 26–28 | Staged rollout, 2 недели стабильной беты, 100% релиз |

Сроки — ориентир, не обещание: App Review, entitlement и Google closed testing
не зависят от команды. Буфер 30–50% уже включён.

### Этап 0 — решения и фундамент (2 недели)

- ADR-001…004: оператор, ядро/лицензия, идентичность/лимит, юрисдикция.
- Юрист: VPN/App Store/Google Play, privacy, export, trademark.
- Аккаунты Apple/Google, Bundle ID, App Group, entitlement (подать заранее —
  одобрение entitlement может занять недели).
- Backend: OpenAPI, DDL, app_installations/app_claims/app_challenges,
  bootstrap contract, feature flags.
- CI: `mobile/` skeleton, CNG-vs-bare решение, lint/test, EAS project.
- **Выход:** ADR подписаны; сборка «Hello» на TestFlight/internal; письменный
  legal-ответ по ядру.

### Этап 1 — дизайн-система и каркас (3 недели)

- Токены, компоненты, темная/светлая, RU/EN, иконки.
- Навигация 5 вкладок, onboarding, splash/update gate.
- API client, error model, offline/caching, secure storage.
- Аналитика/краши с opt-in.
- **Выход:** все экраны на mock-данных; UI-тесты; preview build.

### Этап 2 — ключ и каталог (3 недели)

- App Attest/Play Integrity + bootstrap/attest/claim.
- Free key: один активный на установку, продление после истечения, ошибки,
  лимиты, идемпотентность.
- Прокси-каталог, поиск, фильтры, copy, stale badge.
- Профиль, legal, диагностика, deep links.
- **Выход:** можно получить ключ и пользоваться каталогом без туннеля.

### Этап 3 — туннель (10–12 недель)

- **3.0 Spike (2 недели, stop/go):** Xray-core + gomobile, сборка iOS
  extension, RSS на старом устройстве, 3 протокола, юридическое письмо.
  Провал → companion-only релиз без кнопки «Подключиться».
- iOS Packet Tunnel, Android VpnService, общий state machine.
- Конфиг из подписки, выбор страны, reconnect, network change, kill switch.
- Split tunneling: iOS v1 нет; Android — только после device-lab. DNS/IPv6 —
  только проверенные настройки.
- Battery/perf, interruption, localization, accessibility.
- **Выход:** реальное подключение на тестовой матрице; 95%+ успешных
  подключений; ноль DNS/IPv6 leaks в тестах.

### Этап 4 — hardening, магазины и бета (5–7 недель)

- Security review, MobSF, OWASP, логи/секреты, privacy manifest.
- Store assets, privacy labels, disclosure screen, review notes,
  TestFlight/closed testing (учесть обязательный срок Google для новых
  аккаунтов).
- App Review / Google review может занять 1–3 недели; заложить буфер.
- Staged rollout, crash gates, support runbook, 2 недели стабильной беты.
- **Выход:** публичный релиз 100% после стабильной беты и пройденных
  store-гейтов.

### Этап 5 — после запуска (постоянно)

- Еженедельный triage, monthly release, обновление ядра, ротация сертификатов.
- A/B только на текстах/онбординге, не на безопасности.
- Метрики и обратная связь; удаление неиспользуемых фич.

## 14. Команда, сроки, стоимость

- 1 product/design (0.75–1 FTE), 2 mobile (iOS/Android или RN+натив),
  1 backend, 0.75 QA, 0.5 DevOps/security, юрист (по договору).
  Итого ≈ 4.5–5.5 FTE на пике.
- **22–28 недель** с буфером 30–50%; при одном разработчике — 9–12 месяцев.
- Критический путь: entitlement iOS → spike ядра → туннель → review →
  закрытое тестирование. Любая задержка на одном из них сдвигает релиз.
- Постоянные расходы: Apple $99/год, Google $25, EAS $0–300/мес,
  мониторинг $0–100/мес, домен/почта, юридическая проверка (рыночно).
- Не включать в оценку стоимость трафика: PoolNet не проксирует.

## 15. Риски и решения

| Риск | Вероятность | Влияние | Решение |
| --- | --- | --- | --- |
| Лицензия ядра несовместима с магазином | Средняя | Высокое | ADR-002, юридическое письмо, measured spike, fallback companion |
| App Review отклонит VPN | Средняя | Высокое | Entitlement, NEVPNManager, review notes, тестовый ключ |
| Google Play отклонит VPN | Средняя | Высокое | disclosure, Data safety, foreground service |
| Туннель нестабилен на OEM | Высокая | Среднее | матрица устройств, always-on, диагностика |
| Абуз ключей | Высокая | Среднее | attestation как риск-сигнал, idempotency, install hash, бюджет, рубильник |
| CGNAT блокирует веб-ключ | Средняя | Среднее | app-лимит по установке; честный текст |
| Сторонние узлы опасны | Высокая | Высокое | предупреждения, не для sensitive, no logs |
| Утечка токена/лога | Низкая | Высокое | secure store, redaction, review, no analytics |
| Долгий iOS entitlement | Средняя | Среднее | параллельный Android, early application |
| Scope creep (аккаунты/оплата) | Высокая | Среднее | YAGNI; только после traction |
| Нагрузка на API | Средняя | Среднее | кэш/ETag, rate limits, CDN |

## 16. Backlog по эпикам (MVP)

1. **Foundation:** repo, EAS, theme, navigation, API client, feature flags.
2. **Onboarding/legal:** 3 экрана, privacy, terms, consent.
3. **Free key:** bootstrap, attest, challenge, claim, countdown, errors,
   one active per installation, renewal after expiry.
4. **Connect:** tunnel state machine, permission, IP/latency, reconnect.
5. **Servers:** catalog, search, favorite, auto, per-country shard.
6. **Proxy:** list, search, filters, pagination, copy.
7. **Profile/settings:** theme, language, diagnostics, delete local data.
8. **Observability:** Sentry, redacted logs, metrics, support links.
9. **Release:** icons, screenshots, store text, review, staged rollout.

## 17. Критерии приёмки релиза

- [ ] Один активный ключ на установку; продление после истечения и не чаще
  24 ч; 429 с понятным Retry-After; идемпотентность проверена.
- [ ] Подключение/отключение работает на iOS и Android; нет утечки DNS/IPv6.
- [ ] Kill switch и авто-подключение проверены на реальных устройствах.
- [ ] Split tunneling либо работает, либо отсутствует (без имитации);
  матрица поддержки опубликована.
- [ ] Bearer-токен не появляется в URL, clipboard, логах и аналитике;
  deep link использует одноразовый claim-code.
- [ ] OpenAPI, DDL и контрактные тесты совпадают с реализацией.
- [ ] Crash-free ≥ 99.5%, connect success ≥ 95% на бете 2 недели.
- [ ] Все экраны: light/dark, RU/EN, Dynamic Type XL, VoiceOver/TalkBack.
- [ ] Cold start < 2 с; память и батарея в бюджете; 60 fps в ключевом flow.
- [ ] Магазины: privacy labels, VPN disclosure, review notes, support URL.
- [ ] Legal: terms/privacy/security/abuse опубликованы, юрист подтвердил.
- [ ] Rollback и feature flags проверены; on-call runbook готов.

## 18. Открытые решения (нужны до Этапа 0)

1. Туннельное ядро: Xray-core / sing-box / companion-only.
2. Аккаунты: анонимно навсегда или Sign in with Apple/Google позже.
3. География магазинов и юридические ограничения.
4. Минимальные iOS/Android версии.
5. Нужен ли split tunneling в v1.
6. Бюджет на Apple/Google/legal и состав команды.
7. Название приложения и bundle ID (PoolNet / PoolNet VPN).
8. Поддержка: email, Telegram, GitHub Issues — что публично.
9. CNG + config plugins или bare workflow; кто владеет нативными модулями.
10. Операторская модель: каталог навсегда или появление своих узлов.

## 19. Что уже готово в репозитории

- Интерактивный макет: `web/site/app/` (6 экранов) и
  `https://poolnet.online/app/`.
- API подписок, прокси, статус, healthcheck, one-key-per-IP/day для веба.
- Публичные списки и автоматическая ветка `lists`.
- CI, лицензии, security/contributing, аудит и SEO.

Следующий шаг после утверждения плана — Этап 0: ADR по ядру и юридическая
проверка. Без этого нельзя честно обещать кнопку «Подключиться» в магазинах.
