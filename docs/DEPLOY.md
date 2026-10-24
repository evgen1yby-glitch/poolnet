# Переключение продакшена на poolnet

Документ — для сервера, на котором уже работают прежние `hub` (:8444) и
демо-пул (:8931). Домен, DNS и выпуск сертификата выполняются вне
репозитория; ниже — порядок и шаблоны из `deploy/`.

## 1. Подготовка дерева и зависимостей

```sh
git clone <репозиторий> /opt/evilgate
cd /opt/evilgate

pip install -e "./hub[dev]"        # или requirements в системный python3
cd pool && npm ci --no-audit --no-fund && cd ..
```

Проверки перед установкой (все должны быть зелёными):

```sh
cd hub && ruff check src tests && pytest && cd ..
cd pool && npm run typecheck && npm run lint && npm test && cd ..
python scripts/site_links.py
```

## 2. Окружение

Оба юнита читают `EnvironmentFile`, поэтому значения не попадают в git:

```sh
install -d /etc/evilgate
cat >/etc/evilgate/evilgate.env <<'EOF'
HUB_TOKEN=<токен подписок>
HUB_CHANNEL_ID=<id канала>
EOF
chmod 600 /etc/evilgate/evilgate.env
# pool.env: бюджеты цикла и ключи источников. Без них цикл берёт дефолты
# движка и может уйти на сотни тысяч кандидатов вместо выборки.
cat >/etc/evilgate/pool.env <<'ENVFILE'
OPP_MAX_NEW_PER_CYCLE=3000
OPP_PER_SOURCE_MIN=150
OPP_CONCURRENCY=350
GFP_API_KEY=<ключ источника gfp, если используется>
ENVFILE
chmod 640 /etc/evilgate/pool.env
chown root:evilgate /etc/evilgate/pool.env
```

### Перенос данных со старой установки

Если пул уже публиковался из другого чекаута, скопировать его состояние до
первого запуска таймера — иначе очередь и история начнутся с нуля:

```sh
rsync -a /old/checkout/data/  /opt/evilgate/pool/data/
rsync -a /old/checkout/.state/ /opt/evilgate/pool/.state/
rsync -a /old/checkout/.work/  /opt/evilgate/pool/.work/
cp -p /old/checkout/.env.local /opt/evilgate/pool/.env.local
```

Старый планировщик (cron/systemd) после этого отключается, демо-порты
(:8931 и т. п.) останавливаются: файлы раздаёт `/pool/*` нового hub.

## 3. systemd

Шаблоны содержат плейсхолдеры `@DIR@`, `@USER@`, `@GROUP@`, `@NODE@`,
а юнит хуба ещё `@HUB_ROOT@` (каталог данных VPN-пула) и `@POOL_DIR@`
(каталог публикации прокси-пула).

```sh
sed -e 's|@DIR@|/opt/evilgate|g' -e 's|@USER@|evilgate|g' \
    -e 's|@GROUP@|evilgate|g' -e 's|@HUB_ROOT@|/opt/evilgate/hub|g' \
    -e 's|@POOL_DIR@|/opt/evilgate/pool/data|g' deploy/evilgate.service.in \
    >/etc/systemd/system/evilgate.service

sed -e 's|@DIR@|/opt/evilgate|g' -e 's|@USER@|evilgate|g' \
    -e 's|@GROUP@|evilgate|g' -e 's|@NODE@|/usr/bin/node|g' \
    deploy/evilgate-pool.service.in >/etc/systemd/system/evilgate-pool.service

install -m 0644 deploy/evilgate-pool.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now evilgate.service evilgate-pool.timer
```

Первый цикл пула можно прогнать вручную до включения таймера:

```sh
sudo -u evilgate env OPP_DATA_DIR=/opt/evilgate/pool/data \
  /usr/bin/node /opt/evilgate/pool/node_modules/.bin/tsx src/index.ts cycle
```

Проверка хуба: `curl -s http://127.0.0.1:8090/api/status.json | head -c 200`.
Каталоги `@HUB_ROOT@` и `@POOL_DIR@` можно указать существующие (например,
данные прежнего `hub` и живую публикацию пула), тогда переносить их не нужно.
`pool.available: false` означает, что первый цикл ещё не опубликовал файлы.

## 4. nginx и TLS

```sh
certbot certonly --webroot -w /var/www/certbot -d poolnet.online -d www.poolnet.online
install -m 0644 deploy/nginx-poolnet.conf.in /etc/nginx/conf.d/evilgate.conf
nginx -t && systemctl reload nginx
```

Сертификат обновляется существующим таймером certbot; `ssl_certificate`
указывает на стандартный путь `/etc/letsencrypt/live/poolnet.online/`.

Проверка: `curl -sS https://poolnet.online/api/status.json`,
`https://poolnet.online/`, `/pool/http.txt`, `/status`.

## 5. Старые адреса

Только после того, как новый домен отвечает:

```sh
sed 's|@IP_DASHED@|<IP-через-дефис>|g' deploy/legacy-redirect.conf.in \
    >/etc/nginx/conf.d/evilgate-legacy.conf
nginx -t && systemctl reload nginx
```

`:8444` отдаёт `301` на домен (подписки продолжают работать), `:8931/data/*`
— на `/pool/*`, остальное — на `/proxy`. Старые юниты останавливаются, когда
в логах редиректов не остаётся запросов; тогда же удаляются старые vhost и
`evilgate-legacy.conf`.

## 6. Откат

Остановить `evilgate.service`, вернуть старые юниты (`systemctl enable --now
hub-api …`), убрать `evilgate-legacy.conf` и перезагрузить nginx. Каталоги
данных не пересекаются (`hub/data`, `pool/data`), поэтому откат не теряет
опубликованное.
