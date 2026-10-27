# Support PoolNet: monetization best practices

Updated: 2026-10-26. Scope: Android APK distributed from the project site. No account, free VPN.

## Product rule

Monetization must not interfere with privacy or the core VPN flow. Ads belong on a separate **Support PoolNet** screen, never on the connect screen, country picker, permission dialog, or during an active session. The user must choose to open a partner offer; no surprise popups.

## Recommended order

1. **Direct sponsor card** (no SDK): a privacy-aligned company pays a fixed monthly fee or CPM. This is the only option that preserves full control and works with an off-store APK.
2. **User-initiated rewarded ad** (DT Exchange or InMobi after written approval): user gets a small benefit, e.g. a supporter badge or a temporary cosmetic theme. Keep the reward non-monetary and clearly explained.
3. **CPI/offerwall** (MobItEasy, CIPIAI, etc.): higher revenue potential, but the user installs another app. Requires a clear “Sponsored” label, offer terms review, no forced redirect, no fake close buttons, and no incentivized installs where the offer forbids them.
4. **Direct link / smartlink from Adsterra or Monetag**: only after approval; place on the website or a clearly separated Support screen. Popunders inside the app are not recommended.
5. **Donations**: optional secondary path, not a business plan.

## UX rules

- One dedicated entry: Profile → Support PoolNet.
- Show why it exists: “The app is free; partner offers fund development.”
- Label every item: **Advertisement**, **Partner**, or **Offer**.
- Prefer native sponsor cards over interstitials. No app-open ads, no exit ads, no ads on app load.
- Never place an ad next to Connect, Disconnect, server selection, or a security warning.
- Do not show ads during the first session or during an active VPN connection.
- Frequency cap: one support prompt per session; never re-open automatically.
- Do not hide the close control, fake a system warning, or auto-redirect.
- Do not promise “no tracking” when an external partner receives an IP and its own cookies.

## Privacy and consent

- Opening a partner link sends the user to a third party which may see IP, user agent, and its own cookie/device data. Disclose this before the tap.
- Do not pass VPN traffic, account data, precise location, contacts, or installed-app lists to an ad SDK.
- Use a certified CMP/UMP if personalized ads are ever enabled in the EEA/UK/Switzerland.
- Ad SDKs must not initialize before consent and must not be bundled solely to “test” them.
- Keep a plain-language “How PoolNet makes money” page and a privacy-options link.
- Do not use VPN traffic to manipulate ad geo or fraud detection.

## Network notes

| Network | Fit for Support screen | Notes |
|---|---|---|
| Direct sponsor | Best | No SDK; you control creative and data. |
| DT Exchange / InMobi | Possible | Off-store registration documented; get written VPN + off-store approval. |
| Adsterra / Monetag | Website/direct link | APK traffic and direct links supported; not a substitute for an in-app native SDK. Confirm app placement with the manager. |
| MobItEasy / CIPIAI | CPI/offerwall test | Utility/VPN offers exist; app-store and incent restrictions vary per offer. |
| AdMob | Later | Requires a supported store listing; off-store serving is limited. |
| AppLovin / Pangle | No | VPN/proxy apps are explicitly restricted. |
| Unity / Chartboost / Start.io | Conditional | Store/approval/DAU gates or VPN restrictions. |

## Metrics

Track aggregate counts only:
- support screen opens;
- offer impressions and clicks;
- installs/actions confirmed by postback;
- revenue and eCPM by network/geo;
- retention of users who saw an offer vs holdout;
- support tickets and uninstall reasons.

Kill a placement if retention or trust drops more than its revenue contribution. A/B test a no-offer holdout from day one.

## Implementation

The app reads `https://poolnet.online/app/support.json`. It validates HTTPS URLs and shows:
- native sponsor/partner/offer cards;
- an optional donation URL;
- an optional contact URL;
- a privacy disclosure.

To enable a test, add one or two approved offers to `support.json`; do not commit ad-network secrets. The screen is deliberately empty until a real, approved offer exists.

## Sources

- Google Ad Manager rewarded ads guidance: https://admanager.google.com/home/resources/feature-brief-rewarded-ads/
- AdMob rewarded ads playbook: https://admob.google.com/home/resources/rewarded-ads-playbook/
- Google EU consent policy: https://www.google.com/about/company/user-consent-policy/
- Google UMP / GDPR: https://developers.google.com/admob/android/privacy/gdpr
- Google Publisher Policies: https://support.google.com/publisherpolicies/answer/10502938
- FTC native advertising disclosure: https://www.ftc.gov/business-guidance/resources/native-advertising-guide-businesses
- Adsterra direct links: https://adsterra.com/blog/guide-for-working-with-direct-links
- Adsterra APK monetization: https://adsterra.com/blog/app-monetization
- Monetag APK traffic: https://monetag.com/
- MobItEasy: https://mobiteasy.com/
- CIPIAI offerwall: https://cipiai.com/offerwall
- Offerwall guidance: https://docs.unity.com/en-us/grow/offerwall/monetization/getting-started/get-started-with-offerwall
- Promoted offerwall UX: https://pubscale.com/blog/offerwall-ads-guide
- AffLIFT CPA forum: https://afflift.com/f/forums/affiliate-networks/
- BlackHatWorld Pay Per Install forum (grey/black-hat material; use with caution): https://www.blackhatworld.com/forums/pay-per-install.205/

## Deferred support/donation plan (2026-10-27)

Status: parked. Revisit after the TVHub HLS work. The public free-key page is retired; the Android app remains the only VPN client. The site does not offer keys.

Target support tab:
- Donations first: one-time amounts, optional monthly support, hosted checkout only.
- Primary methods: DonationAlerts (cards/SBP), Boosty (monthly), Ko-fi (international cards/PayPal), TON/USDT; Telegram Stars later.
- Keep the primary screen to four methods and put the rest behind “All methods”. Do not integrate twelve separate providers at once.
- Ads second: opt-in rewarded video only; non-monetary supporter badge, 2–3 views/day, 15–30 minute cooldown, never on connect/VPN screens. AdMob first; mediation only after measured demand. Do not use direct cash rewards.
- No card data in the app; no secrets in `web/site/app/support.json`; no forced ads; no donation = VPN purchase framing.
- Current blocker: provider account creation, payout/KYC approval, VPN-category acceptance, and AdMob/off-store eligibility. Do not ship the support UI until these are confirmed.
