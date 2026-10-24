<p align="center"><img src="web/site/assets/logo-96.png" width="96" alt="PoolNet"></p>

<h1 align="center">PoolNet</h1>

<p align="center">Открытый каталог проверенных VPN-узлов и прокси.<br>
Соединение идёт напрямую клиент → узел; мы не оператор узлов и не гарантируем их.</p>

<p align="center">
  <a href="https://poolnet.online"><img src="https://img.shields.io/badge/site-poolnet.online-7c5cff" alt="site"></a>
  <a href="https://github.com/evgen1yby-glitch/poolnet/tree/lists"><img src="https://img.shields.io/badge/lists-auto--updated-38bdf8" alt="lists"></a>
  <a href="https://github.com/evgen1yby-glitch/poolnet/actions/workflows/lists.yml"><img src="https://github.com/evgen1yby-glitch/poolnet/actions/workflows/lists.yml/badge.svg" alt="lists workflow"></a>
  <a href="https://github.com/evgen1yby-glitch/poolnet/actions/workflows/hub.yml"><img src="https://github.com/evgen1yby-glitch/poolnet/actions/workflows/hub.yml/badge.svg" alt="hub CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0%20%2B%20MIT-blue" alt="license"></a>
</p>

Единая платформа **PoolNet** (poolnet.online): открытая прокси-база
(HTTP / SOCKS4 / SOCKS5) и VPN-конфигурации (vless / ss / vmess / trojan) —
два пула, один стандарт проверки реальными соединениями, открытые данные и
статусы.

Репозиторий объединяет два прежних проекта: `hub` (freevpn, контрольная
плоскость VPN-пула) и `pool` (open-proxy-pool, движок прокси-базы).

## Что здесь есть

| Каталог | Что это | Стек | Лицензия |
| --- | --- | --- | --- |
| `web/site/` | Публичный сайт: главная, VPN, прокси-пул, методика, проверка узла, бесплатная подписка, статус | статический HTML/CSS/JS | — |
| `hub/` | VPN-пул: сбор из публичных источников, проверка в 6 этапов, публикация подписок, Telegram-бот, admin/status API | Python 3.11+, FastAPI, aiogram, SQLite | AGPL-3.0 |
| `pool/` | Прокси-база: 202 источника, дедупликация, проверка, бенчмарк источников, публикация JSON/TXT | Node ≥ 20.11, TypeScript | MIT |
| `docs/` | Документация объединения и эксплуатации | — | — |

Данные прогонов (`data/`, `*/data/`), секреты и окружение в `main` не попадают:
каталог публикации создаётся на сервере, а сайт и API читают его через
`POOLNET_POOL_DIR` / `HUB_SITE`. Публичные снимки лежат отдельно, в ветке
[`lists`](https://github.com/evgen1yby-glitch/poolnet/tree/lists).

## Автоматические списки

Ветка `lists` обновляется GitHub Actions каждые 15 минут из опубликованных
проверенных данных. Это те же узлы, что видит сайт: прокси-цикл и VPN-поколение,
без ручной сборки.

| Что | Ссылка |
| --- | --- |
| Все прокси | [pool/all.txt](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/all.txt) |
| HTTP / SOCKS5 / SOCKS4 | [HTTP](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/http.txt) · [SOCKS5](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/socks5.txt) · [SOCKS4](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/socks4.txt) |
| JSON с метаданными | [proxies.json](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/pool/proxies.json) |
| VPN для Happ / Hiddify | [sing-box base64](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/vpn/verified-sing-box.base64) |
| VPN для Xray / v2rayNG | [xray base64](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/vpn/verified-xray.base64) |
| Clash / mihomo | [clash](https://raw.githubusercontent.com/evgen1yby-glitch/poolnet/lists/vpn/verified-sing-box.clash) |

Ссылку можно добавлять в клиент как подписку. Для персонального ключа на 7 дней
лучше использовать [poolnet.online/free](https://poolnet.online/free): он
показывает срок и не зависит от снимка ветки.

## Как это работает

Оба пула проверяют записи **реальными соединениями**, а не пингом:

- VPN-узел: строка источника → разбор протокола → TCP → TLS → поднятая
  конфигурация → сквозной HTTP-запрос. Не прошёл этап — не попал в выдачу.
- Прокси: очередь публичных списков → дедупликация → выборка → проверка
  соединения и анонимности → публикация. Каждый цикл обновляет выдачу и
  бенчмарк источников.

Сайт не проксирует трафик: соединение клиента идёт напрямую к узлу. PoolNet —
каталог опубликованных списков и проверяющая сторона, не оператор узлов.

## Архитектура

Слои, поток данных, контракты `/api/status.json`, `/api/check` и `/pool/*`,
отказы и раскладка репозитория — в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Сайт двуязычный (RU/EN, переключатель в шапке), страны помечены SVG-флагами.
Числа на страницах `web/site` рендерятся из живых опубликованных данных
(`pool/data` и хранилища `hub`); если данных нет, страницы сохраняют
статический снимок и не показывают пустые блоки.

## Бесплатная подписка
На `/free` любой посетитель получает ключ на 7 дней (`POST /api/free-subscription`,
`source=web`, без аккаунта и Telegram). Выдача ограничена 5 ключами в час на
подсеть /24 при burst 3. Ключи бота/панели видны в `/admin` со сроком,
источником и последним обращением. Платной страницы нет.

## Админка
Открыть: **https://poolnet.online/admin**. Вход — секрет оператора
(`HUB_BOT_SECRET` из окружения сервера). По умолчанию панель доступна с любого
IP; защита — секрет и лимит 5 попыток входа за 15 минут. Необязательный
`HUB_ADMIN_IPS=1.2.3.4,5.6.7.8` (через запятую) ограничивает доступ этими
адресами: остальным отвечает 404. В панели видны сроки, источник и последнее
обращение подписок, есть выдача/продление/отзыв.

## Запуск

```sh
# hub: веб/API (сайт отдаётся, если указан HUB_SITE)
pip install -e "./hub[dev]"
HUB_SITE=web/site POOLNET_POOL_DIR=pool/data python -m hub serve --port 8090

# pool: один цикл и публикация в data/
cd pool
npm ci
npm run cycle
```

Общие точки стыковки:

- `GET /api/status.json` — статус обоих пулов одним запросом для статус-страницы;
- `GET /api/check?proxy=host:port&proto=http|socks4|socks5` — живая проверка одного узла;
- `GET /pool/*` — опубликованные файлы прокси-базы (`http.txt`, `socks5.txt`,
  `country/XX.txt`, `proxies.json`, `meta.json`, `stats.json`, `all.txt`).

## Проверки (как в CI)

CI ставит `pip install -e "./hub[dev]"`, поэтому получает ровно тот ruff,
который закреплён в `hub/pyproject.toml` (**0.6.9**). Локально сделайте то же
самое; `make` откажется запускать произвольный ruff с PATH:

```sh
python3 -m venv .venv
.venv/bin/pip install -e "./hub[dev]"
cd pool && npm ci && cd ..
make check RUFF=.venv/bin/ruff        # lint + test + site
```

Или по отдельности: `make lint RUFF=.venv/bin/ruff`, `make test`, `make site`.
Без `RUFF=` Makefile берёт `python3 -m ruff` и проверяет, что это 0.6.9;
несовпадение — ошибка с подсказкой, а не тихий прогон другими правилами.
Те же хуки доступны через `pre-commit install` (`.pre-commit-config.yaml`),
а секреты дополнительно проверяются gitleaks в CI.

## План

Поэтапный план объединения и переключения продакшена — в [`PLAN.md`](PLAN.md).
Аудит текущего состояния и очередь исправлений — в
[`docs/AUDIT-2026-10-24.md`](docs/AUDIT-2026-10-24.md).
