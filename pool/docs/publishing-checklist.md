# Publishing checklist

One-time setup after the first push, in order of impact on discoverability.

## Repository settings

- [ ] **Description** (one line, shows in search):
      `Verified public proxy pool, republished every 15 minutes — 173 sources, anonymity grades, latency, geo, and a live website`
- [ ] **Website URL** — the GitHub Pages URL (`https://OWNER.github.io/REPO/`)
      or the demo host; it appears next to the repo name everywhere
- [ ] **Topics** — the strongest discovery channel on GitHub:
      `proxy-list`, `proxy`, `proxies`, `socks5`, `socks4`, `http-proxy`,
      `web-scraping`, `scraping`, `github-actions`, `typescript`,
      `data-pipeline`, `privacy`, `networking`, `automation`
- [ ] **Social preview** — Settings → Social preview → Upload `site/assets/og.svg`
      (convert to PNG 1280×640 first: `rsvg-convert` or any online converter).
      This is the image that shows up in Slack, Twitter, Telegram.
- [ ] **Features** → enable **Issues**, **Discussions** (a Q&A category replaces
      half the issues) and **Projects** (public roadmap board)

## First release

- [ ] Tag `v0.1.0` and write a release note from the highlights in
      [CHANGELOG.md](../CHANGELOG.md) — releases get their own RSS and appear
      in the "Releases" tab that visitors check for maintenance signals
- [ ] Pin the release so the newest pool snapshot is one click away

## Pages

- [ ] Settings → Pages → Deploy from branch `main`, folder `/site`
- [ ] Keep `scripts/init-repo.sh <owner>/<repo>` run **before** enabling Pages:
      it replaces the `OWNER/REPO` placeholders in badges, links and the site
- [ ] The refresh workflow commits fresh `data/` + `site/data/` every cycle,
      so Pages updates itself — mention "updates every 15 minutes" in the
      Pages description

## Launch, in order

1. **Show HN** — title like `A verified public-proxy pool, republished every
15 min from GitHub Actions`; the honest numbers (3.58M lines → ~1.2k
   alive) do the talking
2. **Reddit** — r/programming, r/webscraping, r/selfhosted; the "why
   verified beats alive" framing is the hook. Do not cross-post the same day
3. **Awesome lists** — awesome-proxies, awesome-web-scraping,
   awesome-github-actions; PRs adding a one-line entry are usually accepted
4. **Twitter/X** — screenshot of the pool table + the median latency number
5. **Answer existing threads** — "free proxy list" questions on Stack Overflow
   and Reddit, where a verified pool with a JSON API is a real answer

## Ongoing (what keeps stars coming)

- [ ] Reply to every issue within a day, even if it is "won't do"
- [ ] Keep the badge counts moving visibly — the alive badge is the proof of
      life visitors look at
- [ ] A `good first issue` label on source proposals that need a parser
- [ ] Monthly: run the discover sweep, prune dead sources, note it in the
      release notes
