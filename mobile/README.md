# PoolNet Mobile

Нативное приложение PoolNet на Expo/React Native. Android-сборка содержит
встроенный VPN-туннель (`VpnService` + libXray/Xray-core TUN): бесплатный
ключ, выбор страны, подключение/отключение, каталог прокси, профиль.
iOS-сборка пока не сделана: нужен Apple organization account, Mac и Network
Extension entitlement.

Android APK распространяется с сайта `poolnet.online/download`; это
release-подпись PoolNet, но не сборка для Google Play.

## APK

Android VPN client: [PoolNet Mobile 0.5.7](https://poolnet.online/download).
Release-signed with the PoolNet key; contains the embedded Xray TUN tunnel.
Do not upload this APK to Google Play.

## Запуск

```sh
cd mobile
npm ci
npx expo start
```

Веб-предпросмотр (без CORS к API нужен reverse proxy или native):

```sh
npx expo start --web
```

Сборка production:

```sh
npx eas build --platform ios --profile production
npx eas build --platform android --profile production
```

`eas.json` уже содержит профили `development`, `preview`, `production`.
Bundle ID / package: `online.poolnet.mobile`, scheme: `poolnet://`.

Android-проект лежит в `android/` (bare workflow: у нас есть NetworkExtension
и VpnService, поэтому `expo prebuild` больше не запускать). Перед сборкой
скачайте AAR с checksum:

```sh
./scripts/fetch-libxray.sh
export ANDROID_HOME=/path/to/Android/Sdk
npm run build:android
# android/app/build/outputs/apk/release/app-release.apk
```

APK для сайта подписывается release-ключом из `android/keystore.properties`
(файл и keystore не в git). Храните их в надёжном месте: без того же ключа
обновления поверх установленного приложения невозможны. Для Google Play нужен
подписанный AAB.

## Структура

```text
src/app/                 Expo Router
  (tabs)/                Главная, Сервера, Прокси, Ключ, Профиль
  onboarding.tsx         Знакомство
src/components/          UI и tab bar
src/lib/api.ts           API PoolNet
src/lib/storage.ts       Keychain/Keystore; localStorage только web
src/store/app.ts         Zustand: подписка и выбранная страна
src/theme.ts             светлая/тёмная семантика
```

## Поведение

- Подписка хранится в `expo-secure-store`; на web — только localStorage.
- Ключ выдаётся через `/api/free-challenge` + `/api/free-subscription`,
  серверная пауза и лимит на IP соблюдаются.
- Выбранная страна добавляет `/country/<cc>` к ссылке подписки.
- В логах и аналитике не должно быть URL подписки или токена.
- Прокси загружаются из `/api/proxies`; метрики не фабрикуются.

## Следующий гейт

Android: `VpnService`, `libXray.aar`, Xray TUN fd, foreground notification,
per-app exclusion, IPv4/IPv6 routes. Проверено на Android 16 emulator:
внешний IP меняется на узел выбранной страны, отключение убирает `tun0`.
iOS и App Store не входят в текущую сборку. Подробнее:
[`../docs/MOBILE-APP-PLAN.md`](../docs/MOBILE-APP-PLAN.md).

## Проверки

```sh
npm run lint
npx tsc --noEmit
npx expo export --platform web
```
