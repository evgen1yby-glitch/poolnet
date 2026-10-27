# PoolNet: ad monetization research

Date: 2026-10-26  
Scope: free Android VPN client, sideloaded APK, no account.  
This is research, not legal or financial advice. Verify current publisher terms before signing.

## Recommendation

Do **not** put ads on the connect screen, during an active tunnel, in onboarding, or in system notifications. Start with a **directly sold “Sponsored” native card** in a dedicated “Support PoolNet” / partners area, plus optionally a privacy-tool affiliate link. Add an ad SDK only after the direct option is tested.

If a network test is needed, the first candidate is **Digital Turbine DT Exchange**, with **InMobi** as backup. Both publicly support unpublished-app registration. Neither has a public VPN-specific ban in the reviewed documents. Get written confirmation for an off-store VPN app before integrating.

Avoid AppLovin/MAX (explicit VPN ban), Pangle (explicit VPN ban), Chartboost/Start.io (store listing and/or DAU requirements), and Unity/Tapjoy without written approval. AdMob is technically possible only if PoolNet is also listed in a supported third-party store; unsupported-store apps get limited serving.

## Best-practice UX

| Placement | Decision |
|---|---|
| Connect/disconnect, server picker, VPN status | Never |
| Onboarding, permission prompts, security warnings | Never |
| During an active VPN session | Avoid; ad SDK traffic can expose the real IP and VPN IPs may trigger anti-fraud suppression |
| App launch/exit, app-open ads | Never |
| Settings/help/about | Allowed, clearly separated |
| Dedicated “Support PoolNet” screen | Recommended for a native sponsor card |
| After disconnect/session summary | Optional, low-risk |
| Rewarded video | Allowed only as explicit opt-in; reward 24h ad-free or a non-cash feature |

Recommended caps: zero interstitials, one sponsor card per session, one rewarded opt-in per session and no more than three per day, and no ads during the first 24 hours after install. Keep a remote kill switch for ads during incidents.

Native ads must be labelled “Ad”, “Sponsored” or “Advertisement”. Do not disguise ads as VPN features or system messages. Do not place banners next to interactive controls.

## Privacy and consent

- IP addresses and advertising identifiers are personal data under GDPR (Recital 30, Article 4).
- EEA/UK/Switzerland personalized advertising requires a Google-certified CMP and valid consent. Do not initialize an ad SDK before consent.
- Non-personalized ads still use limited identifiers for frequency capping/reporting; do not describe them as “no data”.
- Provide a privacy-options/withdrawal link, a “How PoolNet makes money” page, and a CCPA “Do Not Sell/Share” path if applicable.
- Do not send names, email, precise location, contacts, installed-app lists, or other PII to ad networks.
- Ads fetched outside the tunnel can reveal the real IP. Ads fetched inside the tunnel see the VPN egress IP but can still fingerprint the device.
- A free VPN that contacts advertising/tracking SDKs undermines a “no logs / privacy-first” promise. Scope any privacy claim carefully and disclose every SDK.

## Platform eligibility and payment facts

| Network | Off-store APK | VPN policy | Formats | Payout facts |
|---|---|---|---|---|
| Google AdMob | Supported-store listing needed for full review; off-store = limited serving | No VPN-specific ban found in public publisher policies | Banner, native, interstitial, rewarded, app open | $100 threshold; monthly around the 21st |
| AppLovin / MAX | No; official store required | VPN/proxy apps explicitly prohibited | Rewarded, interstitial, native, banner, app open | $100, Net 15 |
| Unity LevelPlay / ironSource | Practically no; live store status tied to monetization | VPN apps are restricted content requiring prior written approval | Rewarded, interstitial, native, banner | $100, Net 60 |
| Pangle | No; Google Play/App Store listing required | VPN services not supported | Splash, native, interstitial, rewarded, banner | $100; wire |
| Mintegral | Uncertain; valid download link required | No public VPN ban found | Splash, native, interstitial, rewarded, banner, app open | $1,000 default; ~45 days |
| Start.io | No; store publication required | No public VPN ban found | Video, interstitial, rewarded, native, banner | $50, Net 45 |
| InMobi | Unpublished-app registration documented | No public VPN ban found; approval not guaranteed | Banner, interstitial, rewarded, native, video | $300 wire / $50 PayPal, Net 60 |
| Digital Turbine / DT Exchange | App can be added whether or not published | No VPN prohibition found in supply guidelines; approval required | Display, native, video | $250, Net 60; 65% revenue share |
| Chartboost | No; live store + 250 DAU for 7–14 days | No public VPN ban found, but gates exclude PoolNet | Interstitial, rewarded, banner | $75; ~2 months |
| Tapjoy / Unity Offerwall | Dashboard allows not-live, but product is offerwall | VPN restricted under Unity policy | Offerwall/CPA | Contract-specific |
| Direct sponsor / affiliate | Yes | PoolNet controls | Native card/link | Contract-specific |

No audited VPN-specific eCPM benchmark was found. Any public gaming eCPM should not be used as a PoolNet forecast.

## Payment and fraud

Payouts generally require tax/KYC and bank verification. Invalid traffic can lead to withheld earnings, clawbacks, or account closure. Common thresholds are $50–$300 (AdMob $100, Start.io $50, DT $250, InMobi $300); Mintegral’s default is $1,000. Net terms are commonly 45–60 days. Direct sponsorship can be invoiced, but requires sales and a contract.

## PoolNet rollout

**Phase 0 — no SDK (recommended first).**
- Add a “Support PoolNet” screen.
- Sell a clearly labelled native sponsor card to a privacy-aligned company.
- Use no user ID, no ad ID, and no tracking pixel.
- Keep it off Home and out of the tunnel flow.
- Add a simple “Hide sponsor” control and a plain-language monetization page.

**Phase 1 — opt-in rewarded test.**
- One entry point, only while disconnected.
- Initialize the SDK only after the user taps.
- Use non-personalized/limited ads.
- Reward: 24h ad-free or an in-app feature, never cash.
- Cap: one per session, three per day.
- Measure fill, completion, opt-in, retention, uninstalls, support tickets, and crash/ANR.

**Phase 2 — consent and instrumentation.**
- Add a certified CMP before personalized ads.
- Add a privacy-options link and aggregate-only reporting.
- Run an A/B holdout: sponsor card vs no card, rewarded vs no rewarded.
- Stop if D30 retention falls more than revenue per user rises.

## Sources

- AdMob app setup / supported stores: https://support.google.com/admob/answer/9989980
- AdMob app readiness review: https://support.google.com/admob/answer/10564477
- AdMob payments: https://support.google.com/admob/answer/3001017 · https://support.google.com/admob/answer/2772208
- AdMob interstitial policy: https://support.google.com/admob/answer/6201362
- AdMob banner guidance: https://support.google.com/admob/answer/6128877
- AdMob rewarded policy: https://support.google.com/admob/answer/7313578
- AdMob native policy: https://support.google.com/admob/answer/6329638
- Google Publisher Policies: https://support.google.com/publisherpolicies/answer/10502938
- Google EU consent policy: https://www.google.com/about/company/user-consent-policy/
- Google UMP: https://developers.google.com/admob/android/privacy/gdpr
- AppLovin publisher policies: https://legal.applovin.com/policies-publishers/
- AppLovin content policies: https://legal.applovin.com/introduction-to-applovins-publisher-content-policies/
- Unity advertising content policy: https://unity.com/legal/content-policy
- Unity payment timing: https://support.unity.com/hc/en-us/articles/6192555249940
- Pangle supply policy: https://www.pangleglobal.com/knowledge/pangle-supply-policy
- Pangle monetization / payment: https://www.pangleglobal.com/knowledge/monetize-on-pangle · https://www.pangleglobal.com/knowledge/payment-faq
- Mintegral publisher policy: https://cdn-adn.rayjump.com/cdn-adn/doc/mintegral-dev/mintegral_developer_policy_en.pdf
- Mintegral terms: https://dev.mintegral.com/document/term-en.pdf
- Start.io publisher terms: https://www.start.io/policy/publisher-terms
- Start.io payments: https://support.start.io/hc/en-us/articles/224850088
- InMobi getting started: https://support.inmobi.com/monetize/getting-started
- InMobi app approval: https://support.inmobi.com/monetize/cat-faqs/app-approval-process
- Digital Turbine add app: https://docs.digitalturbine.com/dt-exchange/getting-started-with-dt-exchange/setting-up-your-app-in-the-dt-console
- Digital Turbine publisher terms: https://via.digitalturbine.com/terms.html
- Digital Turbine supply guidelines: https://www.digitalturbine.com/legal/dt-supply-content-guidelines
- Chartboost publisher review: https://docs.chartboost.com/en/monetization/publishing/publisher-app-review
- Chartboost payments: https://docs.chartboost.com/en/monetization/payments/payment-terms-dates
- FTC native advertising guidance: https://www.ftc.gov/business-guidance/resources/native-advertising-guide-businesses
- GDPR Recital 30: https://gdpr-info.eu/recitals/no-30/
- California CCPA: https://oag.ca.gov/privacy/ccpa
- Better Ads mobile app standard: https://www.betterads.org/press-releases/cba-new-standard-mobile-apps
- Google Play VpnService policy (only if listing there later): https://support.google.com/googleplay/android-developer/answer/12564964
- 2026 free-VPN tracker study: https://thehackernews.com/2026/07/study-of-281-free-android-vpn-apps.html
- Proton VPN tracker analysis: https://protonvpn.com/blog/vpn-privacy
