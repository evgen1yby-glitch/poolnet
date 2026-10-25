# PoolNet Mobile

Нативное приложение PoolNet на Expo/React Native. Текущий этап — **companion
build**: выбор страны, бесплатный ключ на 7 дней, каталог прокси, статус и
профиль. Встроенный VPN-туннель ещё не включён: он требует ADR по
туннельному ядру, iOS Network Extension entitlement и Android VpnService.
Не выдавайте текущую сборку за работающий VPN-клиент.

## Preview APK

Android companion preview: [PoolNet Mobile 0.1.0](https://github.com/evgen1yby-glitch/poolnet/releases/tag/mobile-v0.1.0).
Debug signing, no embedded tunnel; import the subscription into a VPN client.
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

Локальный preview APK (debug signing, не для Google Play):

```sh
export ANDROID_HOME=/path/to/Android/Sdk
npm run build:android
# android/app/build/outputs/apk/release/app-release.apk
```

Production-подпись делается через EAS/собственный keystore; этот APK нельзя
загружать в Play как production.

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

Перед реализацией кнопки «Подключиться»: ADR-002 (Xray-core/MPL или
sing-box/GPL), юридическая проверка, iOS organization account + Network
Extension entitlement, Android `VpnService` declaration. См.
[`../docs/MOBILE-APP-PLAN.md`](../docs/MOBILE-APP-PLAN.md).

## Проверки

```sh
npm run lint
npx tsc --noEmit
npx expo export --platform web
```
