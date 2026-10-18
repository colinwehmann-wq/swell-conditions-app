// Wakes the hourly alert job on GitHub on a schedule that holds.
//
// GitHub's own cron is best effort: a quiet repository's hourly job can run only every few hours,
// which is too late for "an hour before the peak". Cloudflare's cron triggers are punctual, so the
// Worker wakes up every 30 minutes (wrangler.toml) and asks GitHub to run the workflow right now.
//
// It does nothing, and says why, when
//   - no GITHUB_DISPATCH_TOKEN secret is set (a fine-grained token that can only run Actions on this repo),
//   - it is outside surf hours (4 AM to 7 PM Pacific: alerts for peaks need daylight), or
//   - nobody has made a profile yet, so there is nothing to alert about.
// The outcome of the latest attempt is kept in KV (`meta:dispatch`) and shown by /api/health.

export const FIRST_HOUR = 4;       // Pacific, inclusive
export const LAST_HOUR = 19;       // Pacific, exclusive
export const META_KEY = "meta:dispatch";

export function pacificHour(now) {
  const text = new Intl.DateTimeFormat("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", hourCycle: "h23" }).format(new Date(now));
  return Number(text) % 24;
}

export function inSurfHours(hour) {
  return hour >= FIRST_HOUR && hour < LAST_HOUR;
}

export async function dispatch(env, now = Date.now(), fetchImpl = fetch) {
  const result = { at: new Date(now).toISOString(), ok: false, status: null, skipped: null };

  if (!env.GITHUB_DISPATCH_TOKEN) result.skipped = "no token configured";
  else if (!inSurfHours(pacificHour(now))) result.skipped = "outside surf hours";
  else if (!(await env.PROFILES.list({ prefix: "p:", limit: 1 })).keys.length) result.skipped = "no profiles";

  if (!result.skipped) {
    const repo = env.GITHUB_REPO;
    const workflow = env.GITHUB_WORKFLOW || "profile-alerts.yml";
    try {
      const res = await fetchImpl(`https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "swell-profiles-worker",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: env.GITHUB_REF || "main", inputs: { dry_run: "false" } }),
      });
      result.status = res.status;
      result.ok = res.status === 204;
    } catch {
      result.status = 0;                                   // could not reach GitHub; the next wake-up tries again
    }
  }

  await env.PROFILES.put(META_KEY, JSON.stringify(result));
  return result;
}

export async function lastDispatch(env) {
  const stored = await env.PROFILES.get(META_KEY, "json");
  return stored ? { at: stored.at, ok: stored.ok, status: stored.status, skipped: stored.skipped } : null;
}
