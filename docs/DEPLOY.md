# Переключение продакшена на evilgate

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
# pool.env — по необходимости (OPP_* из `npm run cycle --help`)
```

## 3. systemd

Шаблоны содержат плейсхолдеры `@DIR@`, `@USER@`, `@GROUP@`, `@NODE@`.

```sh
sed -e 's|@DIR@|/opt/evilgate|g' -e 's|@USER@|evilgate|g' \
    -e 's|@GROUP@|evilgate|g' deploy/evilgate.service.in \
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
`pool.available: false` означает, что первый цикл ещё не опубликовал файлы.

## 4. nginx и TLS

```sh
certbot certonly --nginx -d evilgate.online -d www.evilgate.online
install -m 0644 deploy/nginx-evilgate.conf.in /etc/nginx/conf.d/evilgate.conf
nginx -t && systemctl reload nginx
```

Сертификат обновляется существующим таймером certbot; `ssl_certificate`
указывает на стандартный путь `/etc/letsencrypt/live/evilgate.online/`.

Проверка: `curl -sS https://evilgate.online/api/status.json`,
`https://evilgate.online/`, `/pool/http.txt`, `/status`.

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
