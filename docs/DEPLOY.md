# Переключение продакшена на PoolNet

Runbook для сервера, где объединённый репозиторий заменяет прежние `hub`
(:8444) и демо-пул (:8931). Домен `poolnet.online`, DNS и TLS уже настроены;
ниже — установка, окружение, systemd, nginx и откат по шаблонам из `deploy/`.

## 1. Дерево, пользователь и зависимости

```sh
git clone <репозиторий> /opt/poolnet
cd /opt/poolnet

# Служебный пользователь без логина. Имя строчными: оно же используется в
# путях, юнитах и EnvironmentFile, регистр в systemd имеет значение.
groupadd --system poolnet
useradd --system --gid poolnet --home-dir /opt/poolnet \
  --shell /usr/sbin/nologin poolnet
chown -R poolnet:poolnet /opt/poolnet

pip install -e "./hub[dev]"        # или requirements в системный python3
cd pool && npm ci --no-audit --no-fund && cd ..
```

Проверки перед установкой (все должны быть зелёными). Ruff ставится из
`[dev]` и закреплён на 0.6.9 — та же версия, что в CI:

```sh
cd hub && ruff --version && ruff check src tests && pytest && cd ..
cd pool && npm run typecheck && npm run lint \
  && node --import tsx --test test/*.test.ts && cd ..
python scripts/site_links.py
```

## 2. Окружение

Оба юнита читают `EnvironmentFile`, поэтому значения не попадают в git:

```sh
install -d -o root -g poolnet -m 750 /etc/poolnet
cat >/etc/poolnet/poolnet.env <<'EOF'
# Публичный origin: на него смотрят заголовки подписок и ссылки бота.
HUB_BASE_URL=https://poolnet.online
# Bearer операторской подписки и общий секрет для bot/revoke.
HUB_TOKEN=<токен подписок>
HUB_CHANNEL_ID=<id канала>
# Вход в https://poolnet.online/admin. Без него панель закрыта.
HUB_BOT_SECRET=<секрет админки>
# Необязательно: оставить панель только этим адресам (иначе — любой IP).
# HUB_ADMIN_IPS=1.2.3.4,5.6.7.8
# Необязательно: суточный бюджет бесплатных веб-ключей (по умолчанию 2000).
# HUB_FREE_DAILY_LIMIT=2000
# HUB_FREE_WAIT_SECONDS=5
# HUB_FREE_CLAIM_HOURS=24
# HUB_FREE_SECRET=<отдельная соль для хешей IP и challenge>
EOF
chmod 640 /etc/poolnet/poolnet.env
chown root:poolnet /etc/poolnet/poolnet.env

# pool.env: бюджеты цикла и ключи источников. Без них цикл берёт дефолты
# движка и может уйти на сотни тысяч кандидатов вместо выборки.
cat >/etc/poolnet/pool.env <<'ENVFILE'
OPP_MAX_NEW_PER_CYCLE=3000
OPP_PER_SOURCE_MIN=150
OPP_CONCURRENCY=350
GFP_API_KEY=<ключ источника gfp, если используется>
# Публичный IP этого сервера. Публикация не выпускает прокси с этим exit-IP:
# иначе отражение чекера выглядит как «рабочий» прокси. Обязательно для прода.
OPP_SERVER_IP=<публичный IPv4 сервера>
ENVFILE
chmod 640 /etc/poolnet/pool.env
chown root:poolnet /etc/poolnet/pool.env
```

Секреты `HUB_BOT_SECRET` и `HUB_TOKEN` генерируются один раз:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

`HUB_BASE_URL` должен совпадать с публичным доменом (без завершающего `/`):
от него зависят `subscription-userinfo`, `profile-web-page-url` и ссылки,
которые выдаёт `/api/free-subscription`.

### Перенос данных со старой установки

Если пул уже публиковался из другого чекаута, скопировать его состояние до
первого запуска таймера — иначе очередь и история начнутся с нуля:

```sh
rsync -a /old/checkout/data/  /opt/poolnet/pool/data/
rsync -a /old/checkout/.state/ /opt/poolnet/pool/.state/
rsync -a /old/checkout/.work/  /opt/poolnet/pool/.work/
cp -p /old/checkout/.env.local /opt/poolnet/pool/.env.local
chown -R poolnet:poolnet /opt/poolnet/pool/data \
  /opt/poolnet/pool/.state /opt/poolnet/pool/.work
```

VPN-данные прежнего `hub` переносятся в `/opt/poolnet/hub/data` (или юнит
получает существующий каталог через `@HUB_ROOT@`). Старый планировщик
(cron/systemd) после этого отключается, демо-порты (:8931 и т. п.)
останавливаются: файлы раздаёт `/pool/*` нового hub.

## 3. systemd

Шаблоны содержат плейсхолдеры `@DIR@`, `@USER@`, `@GROUP@`, `@NODE@`,
а юнит хуба ещё `@HUB_ROOT@` (каталог данных VPN-пула) и `@POOL_DIR@`
(каталог публикации прокси-пула). Подставляйте строчные `poolnet`:

```sh
sed -e 's|@DIR@|/opt/poolnet|g' -e 's|@USER@|poolnet|g' \
    -e 's|@GROUP@|poolnet|g' -e 's|@HUB_ROOT@|/opt/poolnet/hub|g' \
    -e 's|@POOL_DIR@|/opt/poolnet/pool/data|g' deploy/poolnet.service.in \
    >/etc/systemd/system/poolnet.service

sed -e 's|@DIR@|/opt/poolnet|g' -e 's|@USER@|poolnet|g' \
    -e 's|@GROUP@|poolnet|g' -e 's|@NODE@|/usr/bin/node|g' \
    deploy/poolnet-pool.service.in >/etc/systemd/system/poolnet-pool.service

install -m 0644 deploy/poolnet-pool.timer /etc/systemd/system/

install -d -o poolnet -g poolnet /opt/poolnet/hub/data
systemctl daemon-reload
systemctl enable --now poolnet.service poolnet-pool.timer
```

Первый цикл пула можно прогнать вручную до включения таймера:

```sh
sudo -u poolnet env OPP_DATA_DIR=/opt/poolnet/pool/data \
  /usr/bin/node /opt/poolnet/pool/node_modules/.bin/tsx src/index.ts cycle
```

Проверка хуба: `curl -s http://127.0.0.1:8090/api/status.json | head -c 200`.
Каталоги `@HUB_ROOT@` и `@POOL_DIR@` можно указать существующие (например,
данные прежнего `hub` и живую публикацию пула), тогда переносить их не нужно.
`pool.available: false` означает, что первый цикл ещё не опубликовал файлы.

## 4. Домен, nginx и TLS

DNS `poolnet.online` и `www` указывают на сервер, сертификат Let's Encrypt
выпущен и обновляется штатным таймером certbot:

```sh
certbot certonly --webroot -w /var/www/certbot -d poolnet.online -d www.poolnet.online
install -m 0644 deploy/nginx-poolnet.conf.in /etc/nginx/conf.d/poolnet.conf
nginx -t && systemctl reload nginx
```

`ssl_certificate` указывает на `/etc/letsencrypt/live/poolnet.online/`.
Проверка: `curl -sS https://poolnet.online/api/status.json`,
`https://poolnet.online/`, `/pool/http.txt`, `/status`.

## 5. Админка и старые адреса

Панель работает на том же домене: **https://poolnet.online/admin**. Вход —
`HUB_BOT_SECRET`; лимит 5 попыток за 15 минут. Если задан `HUB_ADMIN_IPS`,
запросы с других адресов получают 404, включая loopback. Проверка:

```sh
curl -s -o /dev/null -w '%{http_code}\n' https://poolnet.online/admin
# 303 → /admin/login без сессии; 404 → вы не в HUB_ADMIN_IPS
```

Старые адреса включаются только после того, как новый домен отвечает:

```sh
sed 's|@IP_DASHED@|<IP-через-дефис>|g' deploy/legacy-redirect.conf.in \
    >/etc/nginx/conf.d/poolnet-legacy.conf
nginx -t && systemctl reload nginx
```

`:8444` отдаёт `301` на домен (подписки продолжают работать), `:8931/data/*`
— на `/pool/*`, остальное — на `/proxy`. Старые юниты останавливаются, когда
в логах редиректов не остаётся запросов; тогда же удаляются старые vhost и
`poolnet-legacy.conf`.

## 6. Откат

Остановить `poolnet.service`, вернуть старые юниты (`systemctl enable --now
hub-api …`), убрать `poolnet-legacy.conf` и перезагрузить nginx. Каталоги
данных не пересекаются (`hub/data`, `pool/data`), поэтому откат не теряет
опубликованное.

## 5. Бэкапы и ретеншн

`deploy/poolnet-backup.timer` снимает согласованный `sqlite3 .backup` базы и
архив `pool/.state` + `pool/data` ежедневно в 03:15 UTC; хранятся 14 копий.
`deploy/poolnet-retention.timer` раз в неделю удаляет `checks` старше 30 дней
и обрезает `events.ndjson` до 20 000 последних строк.

```sh
install -d -o astrobot -g astrobot -m 700 /var/backups/poolnet
sed -e 's|@DIR@|/home/dev/poolnet|g' -e 's|@USER@|astrobot|g' \
  -e 's|@GROUP@|astrobot|g' deploy/poolnet-backup.service.in \
  | sudo tee /etc/systemd/system/poolnet-backup.service >/dev/null
sudo cp deploy/poolnet-backup.timer deploy/poolnet-retention.timer \
  /etc/systemd/system/
sed -e 's|@DIR@|/home/dev/poolnet|g' -e 's|@USER@|astrobot|g' \
  -e 's|@GROUP@|astrobot|g' deploy/poolnet-retention.service.in \
  | sudo tee /etc/systemd/system/poolnet-retention.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now poolnet-backup.timer poolnet-retention.timer
# Проверка: sudo systemctl start poolnet-backup.service && ls -lh /var/backups/poolnet
```

## 6. Автосписки в GitHub

Ветку `lists` обновляет GitHub Actions (`.github/workflows/lists.yml`) и
резервный таймер этой машины — оба собирают снимок из `/pool/*` и `/vpn/*`.
Таймеру нужен SSH-ключ с write-доступом к репозиторию (по умолчанию
`~/.ssh/id_ed25519_github`, можно переопределить `POOLNET_GITHUB_KEY`):

```sh
sed -e 's|@DIR@|/home/dev/poolnet|g' -e 's|@USER@|astrobot|g' \
  -e 's|@GROUP@|astrobot|g' deploy/poolnet-lists.service.in \
  | sudo tee /etc/systemd/system/poolnet-lists.service >/dev/null
sudo cp deploy/poolnet-lists.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now poolnet-lists.timer
```

## 7. Мониторинг

`deploy/poolnet-healthcheck.timer` каждые 5 минут проверяет `/healthz` (возраст
VPN-поколения) и `/api/status.json` (свежесть прокси-пула). При сбое таймер
пишет в journal; если задан `POOLNET_ALERT_WEBHOOK`, отправляет туда JSON
`{"text": "..."}`. Порог пула — 2 часа, VPN — 6 часов, переопределяется
`POOLNET_MAX_POOL_HOURS`/`POOLNET_MAX_VPN_HOURS`.

```sh
sed -e 's|@DIR@|/home/dev/poolnet|g' -e 's|@USER@|astrobot|g' \
  -e 's|@GROUP@|astrobot|g' deploy/poolnet-healthcheck.service.in \
  | sudo tee /etc/systemd/system/poolnet-healthcheck.service >/dev/null
sudo cp deploy/poolnet-healthcheck.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now poolnet-healthcheck.timer
```

Старый IP-endpoint `:8444` теперь отвечает `301` на `https://poolnet.online`;
его шаблон — `hub/deploy/nginx-hub-8444.conf.in`.

Проверка восстановления (не трогает рабочую базу):

```sh
./scripts/restore_check.sh
# restore-ok nodes=… subscriptions=… source=/var/backups/poolnet/…
```
