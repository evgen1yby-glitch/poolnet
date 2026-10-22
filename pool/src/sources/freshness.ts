/**
 * Source freshness via the GitHub API.
 *
 * A source that answers 200 while its file has not been touched in months is
 * the dangerous kind: a naive health check passes, but every entry inside is
 * dead. `raw.githubusercontent.com` does not send Last-Modified, so we ask
 * the API for the last commit that touched the file instead. Needs a token
 * (60 req/h unauthenticated is too little for ~160 sources); the refresh
 * workflow always has one, and locally `gh` users can export GITHUB_TOKEN.
 */
export interface Freshness {
  /** whole days since the last commit touching the file, null when unknown */
  days: number | null;
  /** iso date of that commit */
  iso: string | null;
}

const RAW_RE = /^https:\/\/raw\.githubusercontent\.com\/([^/]+)\/([^/]+)\/(?:refs\/heads\/)?[^/]+\/(.+)$/;

export function parseGitHubRaw(url: string): { owner: string; repo: string; path: string } | null {
  const m = RAW_RE.exec(url);
  if (!m) return null;
  return { owner: m[1]!, repo: m[2]!, path: decodeURIComponent(m[3]!) };
}

export async function githubFileFreshness(
  url: string,
  token: string | undefined,
  fetchImpl: typeof fetch = fetch,
): Promise<Freshness> {
  const parsed = parseGitHubRaw(url);
  if (!parsed) return { days: null, iso: null };
  const api = `https://api.github.com/repos/${parsed.owner}/${parsed.repo}/commits?path=${encodeURIComponent(parsed.path)}&per_page=1`;
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'User-Agent': 'open-proxy-pool',
    'X-GitHub-Api-Version': '2022-11-28',
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    // the same hard deadline source fetches get: a stalled API call must
    // not burn the fetch job's whole time budget
    const res = await fetchImpl(api, { headers, signal: AbortSignal.timeout(15_000) });
    if (res.status === 404) return { days: null, iso: null }; // default-branch path mismatch
    if (!res.ok) return { days: null, iso: null };
    const json = (await res.json()) as Array<{ commit?: { committer?: { date?: string } } }>;
    const iso = json[0]?.commit?.committer?.date ?? null;
    if (!iso) return { days: null, iso: null };
    const days = Math.floor((Date.now() - Date.parse(iso)) / 86400000);
    return { days, iso };
  } catch {
    return { days: null, iso: null };
  }
}

/** Sources older than this are flagged as stale in the fetch report. */
export const STALE_DAYS = 90;
