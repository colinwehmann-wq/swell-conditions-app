import test from "node:test";
import assert from "node:assert/strict";
import worker, { handle } from "../src/index.js";
import { dispatch, dispatchSite, pacificHour, inSurfHours, lastDispatch, META_KEY, SITE_META_KEY } from "../src/dispatch.js";

class FakeKV {
  constructor() {
    this.data = new Map();
  }
  async get(key, type) {
    const v = this.data.get(key);
    if (v === undefined) return null;
    return type === "json" ? JSON.parse(v) : v;
  }
  async put(key, value) {
    this.data.set(key, value);
  }
  async delete(key) {
    this.data.delete(key);
  }
  async list({ prefix = "", limit = 1000 } = {}) {
    const names = [...this.data.keys()].filter((k) => k.startsWith(prefix)).sort().slice(0, limit);
    return { keys: names.map((name) => ({ name })), list_complete: true };
  }
}

const TOKEN = "github_pat_TESTTOKEN";
const makeEnv = (extra = {}) => {
  const env = {
    PROFILES: new FakeKV(), GITHUB_DISPATCH_TOKEN: TOKEN, GITHUB_REPO: "owner/repo", GITHUB_WORKFLOW: "profile-alerts.yml",
    GITHUB_REF: "main", GITHUB_SITE_WORKFLOW: "surf-check.yml", ...extra,
  };
  env.PROFILES.data.set("p:AAAAAAAAAAAAAAAAAAAAAA", JSON.stringify({ topic: "swell-x", breaks: ["swamis"] }));
  return env;
};

// 2026-10-20 at the given Pacific hour (PDT is UTC-7 on that date).
const at = (pacific, minute = 0) => Date.UTC(2026, 9, 20, pacific + 7, minute);

function recorder(status = 204) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    return { status, text: async () => "" };
  };
  fn.calls = calls;
  return fn;
}

test("pacific hour, across the daylight-saving change", () => {
  assert.equal(pacificHour(Date.UTC(2026, 9, 20, 14, 10)), 7);         // PDT
  assert.equal(pacificHour(Date.UTC(2026, 11, 20, 15, 10)), 7);        // PST
  assert.equal(pacificHour(Date.UTC(2026, 9, 20, 7, 0)), 0);           // midnight is 0, not 24
});

test("surf hours are 4 AM up to, not including, 7 PM", () => {
  assert.equal(inSurfHours(3), false);
  assert.equal(inSurfHours(4), true);
  assert.equal(inSurfHours(18), true);
  assert.equal(inSurfHours(19), false);
});

test("it asks GitHub to run the workflow, with the right address, key and inputs", async () => {
  const env = makeEnv();
  const f = recorder(204);
  const r = await dispatch(env, at(6), f);
  assert.equal(r.ok, true);
  assert.equal(r.status, 204);
  assert.equal(f.calls.length, 1);
  const { url, init } = f.calls[0];
  assert.equal(url, "https://api.github.com/repos/owner/repo/actions/workflows/profile-alerts.yml/dispatches");
  assert.equal(init.method, "POST");
  assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.match(init.headers.Accept, /github/);
  assert.ok(init.headers["User-Agent"]);
  assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { dry_run: "false" } });     // a real run, not a dry one
});

test("it does nothing without a token", async () => {
  const f = recorder();
  const r = await dispatch(makeEnv({ GITHUB_DISPATCH_TOKEN: undefined }), at(6), f);
  assert.equal(r.skipped, "no token configured");
  assert.equal(f.calls.length, 0);
});

test("it does nothing at night", async () => {
  const f = recorder();
  for (const hour of [0, 2, 3, 19, 22]) {
    const r = await dispatch(makeEnv(), at(hour), f);
    assert.equal(r.skipped, "outside surf hours", String(hour));
  }
  assert.equal(f.calls.length, 0);
});

test("it does nothing while nobody has a profile", async () => {
  const env = makeEnv();
  env.PROFILES.data.clear();
  const f = recorder();
  const r = await dispatch(env, at(6), f);
  assert.equal(r.skipped, "no profiles");
  assert.equal(f.calls.length, 0);
});

test("rate-limit counters and its own record do not count as profiles", async () => {
  const env = makeEnv();
  env.PROFILES.data.clear();
  env.PROFILES.data.set("rl:abc:1", "3");
  env.PROFILES.data.set(META_KEY, "{}");
  const f = recorder();
  assert.equal((await dispatch(env, at(6), f)).skipped, "no profiles");
});

test("a refusal from GitHub is recorded, not thrown", async () => {
  const env = makeEnv();
  const r = await dispatch(env, at(6), recorder(403));
  assert.equal(r.ok, false);
  assert.equal(r.status, 403);
});

test("an unreachable GitHub is recorded, not thrown", async () => {
  const env = makeEnv();
  const r = await dispatch(env, at(6), async () => { throw new Error("network down"); });
  assert.equal(r.ok, false);
  assert.equal(r.status, 0);
});

test("the latest attempt is kept and shown, without the token", async () => {
  const env = makeEnv();
  await dispatch(env, at(6), recorder(204));
  const seen = await lastDispatch(env);
  assert.deepEqual(seen, { at: new Date(at(6)).toISOString(), ok: true, status: 204, skipped: null });
  assert.equal(JSON.stringify(seen).includes(TOKEN), false);
  assert.equal(env.PROFILES.data.get(META_KEY).includes(TOKEN), false);
});

test("health reports the last wake-up and never the token", async () => {
  const env = makeEnv({ ALLOWED_ORIGINS: "" });
  await dispatch(env, at(6), recorder(204));
  const res = await handle(new Request("https://api.example.test/api/health"), env);
  const text = await res.text();
  assert.equal(text.includes(TOKEN), false);
  const body = JSON.parse(text);
  assert.equal(body.ok, true);
  assert.equal(body.dispatch.ok, true);
  assert.equal(body.dispatch.status, 204);
});

test("the admin listing does not mistake the wake-up record for a profile", async () => {
  const env = makeEnv({ ADMIN_KEY: "k".repeat(40), ALLOWED_ORIGINS: "" });
  await dispatch(env, at(6), recorder(204));
  const res = await handle(new Request("https://api.example.test/api/admin/profiles", { headers: { Authorization: `Bearer ${env.ADMIN_KEY}` } }), env);
  const out = await res.json();
  assert.equal(out.profiles.length, 1);
});

test("the cron trigger runs the wake-up through the Worker's scheduled handler", async () => {
  const env = makeEnv();
  const waits = [];
  const realFetch = globalThis.fetch;
  const f = recorder(204);
  globalThis.fetch = f;
  try {
    worker.scheduled({ scheduledTime: at(6) }, env, { waitUntil: (p) => waits.push(p) });
    await Promise.all(waits);
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.equal(waits.length, 1);
  assert.equal(f.calls.length, 2);                       // at the top of the hour: the alerts job and the site rebuild
  assert.deepEqual(f.calls.map((c) => c.url.split("/workflows/")[1]).sort(), ["profile-alerts.yml/dispatches", "surf-check.yml/dispatches"]);
});

test("on the half hour the scheduled handler runs only the alerts job", async () => {
  const env = makeEnv();
  const waits = [];
  const realFetch = globalThis.fetch;
  const f = recorder(204);
  globalThis.fetch = f;
  try {
    worker.scheduled({ scheduledTime: at(7, 30) }, env, { waitUntil: (p) => waits.push(p) });
    await Promise.all(waits);
  } finally {
    globalThis.fetch = realFetch;
  }
  assert.deepEqual(f.calls.map((c) => c.url.split("/workflows/")[1]), ["profile-alerts.yml/dispatches"]);
});

// ---- the site rebuild ---------------------------------------------------------------------------

test("the site rebuild is asked for on the hour, with public channels on and the digest off", async () => {
  const env = makeEnv();
  const f = recorder(204);
  const r = await dispatchSite(env, at(9), f);
  assert.equal(r.ok, true);
  const { url, init } = f.calls[0];
  assert.equal(url, "https://api.github.com/repos/owner/repo/actions/workflows/surf-check.yml/dispatches");
  assert.equal(init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.deepEqual(JSON.parse(init.body), { ref: "main", inputs: { publish_public: "true", digest: "false", force: "false" } });
});

test("the first run of the 5 AM hour also sends the daily digest, no other hour does", async () => {
  for (const hour of [4, 5, 6, 12, 18]) {
    const f = recorder(204);
    await dispatchSite(makeEnv(), at(hour), f);
    assert.equal(JSON.parse(f.calls[0].init.body).inputs.digest, hour === 5 ? "true" : "false", String(hour));
  }
});

test("the site rebuild runs once an hour, not on the half hour", async () => {
  const f = recorder();
  const r = await dispatchSite(makeEnv(), at(9, 30), f);
  assert.equal(r.skipped, "between hourly runs");
  assert.equal((await dispatchSite(makeEnv(), at(9, 29), f)).skipped, null);
  assert.equal((await dispatchSite(makeEnv(), at(9, 31), f)).skipped, "between hourly runs");
});

test("the site rebuild does not wait for anyone to have a profile", async () => {
  const env = makeEnv();
  env.PROFILES.data.clear();
  const f = recorder(204);
  assert.equal((await dispatchSite(env, at(9), f)).ok, true);
  assert.equal(f.calls.length, 1);
});

test("the site rebuild keeps to surf hours and needs a token", async () => {
  const f = recorder();
  assert.equal((await dispatchSite(makeEnv(), at(3), f)).skipped, "outside surf hours");
  assert.equal((await dispatchSite(makeEnv(), at(19), f)).skipped, "outside surf hours");
  assert.equal((await dispatchSite(makeEnv({ GITHUB_DISPATCH_TOKEN: undefined }), at(9), f)).skipped, "no token configured");
  assert.equal(f.calls.length, 0);
});

test("a refusal or an outage on the site rebuild is recorded, not thrown", async () => {
  assert.equal((await dispatchSite(makeEnv(), at(9), recorder(403))).status, 403);
  const r = await dispatchSite(makeEnv(), at(9), async () => { throw new Error("down"); });
  assert.equal(r.ok, false);
  assert.equal(r.status, 0);
});

test("health shows both wake-ups, the alerts job and the site rebuild, and neither holds the token", async () => {
  const env = makeEnv({ ALLOWED_ORIGINS: "" });
  await dispatch(env, at(9), recorder(204));
  await dispatchSite(env, at(9), recorder(204));
  const res = await handle(new Request("https://api.example.test/api/health"), env);
  const text = await res.text();
  assert.equal(text.includes(TOKEN), false);
  const body = JSON.parse(text);
  assert.equal(body.dispatch.ok, true);
  assert.equal(body.site.ok, true);
  assert.equal(body.site.status, 204);
  assert.equal((await lastDispatch(env, SITE_META_KEY)).skipped, null);
});

test("the site's own record is not mistaken for a profile", async () => {
  const env = makeEnv();
  env.PROFILES.data.clear();
  await dispatchSite(env, at(9), recorder(204));
  assert.equal((await dispatch(env, at(9), recorder())).skipped, "no profiles");
});
