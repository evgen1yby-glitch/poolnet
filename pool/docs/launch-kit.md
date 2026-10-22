# Launch kit

Everything needed to ship the project publicly, assembled from the launch
research (AFFiNE playbook, HN/Reddit practice, and an independent benchmark of
the free-proxy genre). Work top to bottom.

## The story (why anyone should care)

The genre's repos sell volume: "PROXY List that gets updated everyday". The
independent measurements say the opposite is the problem: ~8% of listed
proxies answer at all, and a source that returns 200 while its file has not
been touched in years passes every naive health check. This project's pitch
is the honest one:

> **3.58M lines read this cycle → 731k unique candidates → ~1.2k alive.**
> Every survivor carried a full request through a real connection, checked
> continuously from disposable runners — never the operator's address.

Three hooks, in order of strength:

1. **"Verified, not scanned"** — the funnel numbers are published per cycle.
2. **"Zero-infrastructure pipeline"** — the whole thing runs on GitHub
   Actions; state lives in a cache. No server, no keys (one optional).
3. **"Not just files"** — website with search and a playground, JSON API,
   country shards.

## T-7 … T-1: assets

- [ ] Repo public, `scripts/init-repo.sh <owner>/<repo>` run (badges, links)
- [ ] Platform site (`web/site`) deployed with `hub`; the live URL in the
      About field
- [ ] Topics: `proxy-list`, `proxy`, `proxies`, `socks5`, `socks4`,
      `http-proxy`, `web-scraping`, `github-actions`, `typescript`,
      `data-pipeline`, `privacy`, `networking`, `automation`, `self-hosted`
- [ ] Social preview image 1280×640 uploaded
      (Settings → Social preview). The one image that ships in every DM.
- [ ] `data/meta.json` alive count in the About line: `1,215 verified public
proxies, republished every 15 minutes` — update it after each refresh
- [ ] 3 screenshots cropped to 16:9 for HN/Reddit/Twitter:
      the pool table, the playground, the dark hero
- [ ] One 30s screen capture: filter → search → copy → playground check

## T-0: launch day (US morning, ~09:00 ET)

| Time (ET) | Channel         | Action                                                  |
| --------- | --------------- | ------------------------------------------------------- |
| 09:00     | GitHub          | Public, platform site live, About + topics set          |
| 09:15     | Hacker News     | Show HN (title below)                                   |
| 09:30     | Twitter/X       | Thread: hook 1 + screenshot of the funnel               |
| 12:00     | Reddit          | r/webscraping, then r/programming (13:00), r/selfhosted |
| 15:00     | V2EX / linux.do | Creative-share nodes (both large dev communities)       |
| 16:00     | DevHunt         | Submit                                                  |
| evening   | Telegram        | The bot link in scraping/automation channels            |

**Show HN title** (formula: what it is + the surprising fact):
`Show HN: A verified public-proxy pool rebuilt every 15 min in GitHub Actions`
First comment: the funnel, why verification claims lie, what the pool is for.

**Reddit r/webscraping title:**
`I measured the free-proxy genre: 8% alive, abandoned sources that still
return 200 – so I rebuilt a pool that only publishes what carries a full
request` — lead with the measurement, the repo is the evidence.

**r/programming** is title-strict: keep it factual, no superlatives:
`A proxy pool pipeline that runs entirely on GitHub Actions`

### Rules that keep the launch alive

- Answer every comment within the hour, all day. The second-day wave is real
  (day 1 is quiet, days 2–3 compound — do not panic on day 1).
- Never delete a critical comment; answer it with a measurement.
- Record stars every few hours; the number that matters is day 7, not day 1.

## T+1 … T+30: the compounding layer

- [ ] dev.to / Hashnode article: "What 3.58M proxy lines taught me about free
      proxy lists" — the measurement story, repo at the end
- [ ] PRs to awesome lists: awesome-proxies, awesome-webscraping,
      awesome-github-actions, awesome-selfhosted (one-line entries, real
      description — they are reviewed)
- [ ] KOL outreach to scraping/proxy maintainers with the warm template:
      `loved [their tool]. We rebuilt a verified pool in Actions; the JSON
API with anonymity + uptime might fit your README?`
- [ ] Answer existing "free proxy list" threads on SO/Reddit with the
      measured link (this is evergreen traffic, not launch spam)
- [ ] telegram bot: the subscriber magnet — see `bot/`, link it from the
      README's first screen. `/get socks5 US` in a chat is the demo.

## Telegram: what actually grows it here

The audience of this project (scrapers, automation, growth) is Telegram-heavy.
The bot is the acquisition surface; the channel is the retention surface.

- **Bot first** — `/get` is a utility people keep. Every response carries a
  `/help` and a repo link; that is the subscriber funnel.
- **Channel posts, 3×/week**: the funnel numbers of the day, one honest
  finding (a stale source caught, a MITM cluster, a ASN appearing), monthly
  "state of the free proxy pool" summary. Numbers travel in Telegram.
- **Seed**: scraping/OSINT/automation channels that allow tool posts; the
  bot link is content, not spam.
- **Never** buy subscribers — a dead channel reads worse than no channel.

## What NOT to do

- Do not buy stars or join star-for-star rings; the ratio shows in Insights
  and reviewers check it.
- Do not claim counts the pipeline does not measure (the genre's problem).
- Do not spam the same link across 20 subreddits on day 1; two well-answered
  threads out-teach a hundred dropped ones.
