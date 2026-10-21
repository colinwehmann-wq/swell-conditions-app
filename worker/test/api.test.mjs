import test from "node:test";
import assert from "node:assert/strict";
import worker, { handle } from "../src/index.js";

const SITE = "https://colinwehmann-wq.github.io";

// The slice of Cloudflare KV the service uses, held in memory.
class FakeKV {
  constructor() {
    this.data = new Map();
    this.writes = 0;
  }
  async get(key, type) {
    const v = this.data.get(key);
    if (v === undefined) return null;
    return type === "json" ? JSON.parse(v) : v;
  }
  async put(key, value) {
    this.writes++;
    this.data.set(key, value);
  }
  async delete(key) {
    this.data.delete(key);
  }
  async list({ prefix = "", limit = 1000, cursor } = {}) {
    const names = [...this.data.keys()].filter((k) => k.startsWith(prefix)).sort();
    const start = cursor ? Number(cursor) : 0;
    const slice = names.slice(start, start + limit);
    const end = start + slice.length;
    return { keys: slice.map((name) => ({ name })), list_complete: end >= names.length, cursor: String(end) };
  }
}

const makeEnv = (extra = {}) => ({ PROFILES: new FakeKV(), ADMIN_KEY: "k".repeat(40), ALLOWED_ORIGINS: SITE + ",http://localhost:8000", ...extra });

const call = (env, method, path, { body, headers = {}, ip = "203.0.113.7", now } = {}) =>
  handle(
    new Request("https://api.example.test" + path, {
      method,
      headers: { "CF-Connecting-IP": ip, ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...headers },
      body: body === undefined ? undefined : typeof body === "string" ? body : JSON.stringify(body),
    }),
    env,
    now,
  );

const json = async (res) => JSON.parse(await res.text());

const PROFILE = { name: "Test", breaks: ["swamis", "windansea"], prefs: { height_ft: [3, 6], wind: "offshore" } };

async function create(env, body = PROFILE, opts = {}) {
  const res = await call(env, "POST", "/api/profile", { body, ...opts });
  assert.equal(res.status, 201);
  return json(res);
}

test("health", async () => {
  const res = await call(makeEnv(), "GET", "/api/health");
  assert.equal(res.status, 200);
  assert.deepEqual(await json(res), { ok: true, dispatch: null, site: null });
});

test("create returns a secret id and a private topic", async () => {
  const env = makeEnv();
  const made = await create(env);
  assert.match(made.id, /^[A-Za-z0-9_-]{22}$/);
  assert.match(made.topic, /^swell-[0-9a-f]{24}$/);
  assert.deepEqual(made.profile.breaks, ["swamis", "windansea"]);
  assert.equal(made.profile.prefs.wind, "offshore");
  assert.equal(made.profile.prefs.period_min_s, 8);          // defaults filled in
  assert.ok(env.PROFILES.data.has(`p:${made.id}`));
});

test("ids and topics are different every time", async () => {
  const env = makeEnv();
  const a = await create(env, PROFILE, { ip: "198.51.100.1" });
  const b = await create(env, PROFILE, { ip: "198.51.100.2" });
  assert.notEqual(a.id, b.id);
  assert.notEqual(a.topic, b.topic);
});

test("read it back with the id", async () => {
  const env = makeEnv();
  const made = await create(env);
  const res = await call(env, "GET", `/api/profile/${made.id}`);
  assert.equal(res.status, 200);
  const got = await json(res);
  assert.equal(got.id, made.id);
  assert.equal(got.topic, made.topic);
  assert.deepEqual(got.profile, made.profile);
});

test("an unknown or malformed id is a 404, never a listing", async () => {
  const env = makeEnv();
  await create(env);
  assert.equal((await call(env, "GET", "/api/profile/AAAAAAAAAAAAAAAAAAAAAA")).status, 404);
  assert.equal((await call(env, "GET", "/api/profile/short")).status, 404);
  assert.equal((await call(env, "GET", "/api/profile/..%2Fadmin")).status, 404);
  assert.equal((await call(env, "GET", "/api/profile")).status, 404);
});

test("update replaces the profile but keeps the topic", async () => {
  const env = makeEnv();
  const made = await create(env);
  const res = await call(env, "PUT", `/api/profile/${made.id}`, { body: { breaks: ["d-street"], prefs: { height_ft: [2, 4] } }, now: Date.now() + 5000 });
  assert.equal(res.status, 200);
  const got = await json(res);
  assert.equal(got.topic, made.topic);
  assert.equal(got.created, made.created);
  assert.notEqual(got.updated, made.updated);
  assert.deepEqual(got.profile.breaks, ["d-street"]);
  assert.deepEqual(got.profile.prefs.height_ft, [2, 4]);
});

test("update refuses invalid input and leaves the profile alone", async () => {
  const env = makeEnv();
  const made = await create(env);
  const res = await call(env, "PUT", `/api/profile/${made.id}`, { body: { breaks: ["Bad Name"] } });
  assert.equal(res.status, 400);
  assert.ok((await json(res)).errors.length);
  const still = await json(await call(env, "GET", `/api/profile/${made.id}`));
  assert.deepEqual(still.profile.breaks, ["swamis", "windansea"]);
});

test("update and delete need an existing id", async () => {
  const env = makeEnv();
  assert.equal((await call(env, "PUT", "/api/profile/AAAAAAAAAAAAAAAAAAAAAA", { body: PROFILE })).status, 404);
  assert.equal((await call(env, "DELETE", "/api/profile/AAAAAAAAAAAAAAAAAAAAAA")).status, 404);
});

test("delete removes it", async () => {
  const env = makeEnv();
  const made = await create(env);
  assert.equal((await call(env, "DELETE", `/api/profile/${made.id}`)).status, 204);
  assert.equal((await call(env, "GET", `/api/profile/${made.id}`)).status, 404);
  assert.equal(env.PROFILES.data.has(`p:${made.id}`), false);
});

test("bad bodies: invalid JSON, wrong shape, too large", async () => {
  const env = makeEnv();
  assert.equal((await call(env, "POST", "/api/profile", { body: "{nope" })).status, 400);
  assert.equal((await call(env, "POST", "/api/profile", { body: { breaks: "swamis" } })).status, 400);
  assert.equal((await call(env, "POST", "/api/profile", { body: "x".repeat(9000) })).status, 413);
  assert.equal(env.PROFILES.writes, 0);                          // nothing was stored
});

test("creating is rate limited per address, per hour", async () => {
  const env = makeEnv({ CREATE_LIMIT_PER_HOUR: "3" });
  const now = Date.UTC(2026, 9, 20, 12, 0, 0);
  for (let i = 0; i < 3; i++) assert.equal((await call(env, "POST", "/api/profile", { body: PROFILE, now })).status, 201);
  const blocked = await call(env, "POST", "/api/profile", { body: PROFILE, now });
  assert.equal(blocked.status, 429);
  assert.equal(blocked.headers.get("Retry-After"), "3600");
  // another address is unaffected, and so is the next hour
  assert.equal((await call(env, "POST", "/api/profile", { body: PROFILE, now, ip: "198.51.100.9" })).status, 201);
  assert.equal((await call(env, "POST", "/api/profile", { body: PROFILE, now: now + 3600000 })).status, 201);
});

test("the stored address is hashed, never kept", async () => {
  const env = makeEnv();
  await create(env, PROFILE, { ip: "203.0.113.77" });
  for (const key of env.PROFILES.data.keys()) assert.equal(key.includes("203.0.113.77"), false);
});

test("admin listing needs the key", async () => {
  const env = makeEnv();
  await create(env);
  assert.equal((await call(env, "GET", "/api/admin/profiles")).status, 401);
  assert.equal((await call(env, "GET", "/api/admin/profiles", { headers: { Authorization: "Bearer wrong" } })).status, 401);
  assert.equal((await call(env, "GET", "/api/admin/profiles", { headers: { Authorization: env.ADMIN_KEY } })).status, 401);
  const noKey = makeEnv({ ADMIN_KEY: undefined });
  assert.equal((await call(noKey, "GET", "/api/admin/profiles", { headers: { Authorization: "Bearer undefined" } })).status, 503);
});

test("admin listing returns topics and preferences, never the ids", async () => {
  const env = makeEnv();
  const a = await create(env, PROFILE, { ip: "198.51.100.1" });
  const b = await create(env, { breaks: ["d-street"] }, { ip: "198.51.100.2" });
  const res = await call(env, "GET", "/api/admin/profiles", { headers: { Authorization: `Bearer ${env.ADMIN_KEY}` } });
  assert.equal(res.status, 200);
  const text = await res.text();
  assert.equal(text.includes(a.id) || text.includes(b.id), false);
  const out = JSON.parse(text);
  assert.equal(out.cursor, null);
  assert.deepEqual(out.profiles.map((p) => p.topic).sort(), [a.topic, b.topic].sort());
  assert.ok(out.profiles.every((p) => Array.isArray(p.breaks) && p.prefs && p.alerts));
});

test("admin listing pages through many profiles", async () => {
  const env = makeEnv();
  for (let i = 0; i < 130; i++) {
    env.PROFILES.data.set(`p:${String(i).padStart(22, "x")}`, JSON.stringify({ v: 1, topic: `swell-${i}`, breaks: ["swamis"], prefs: {}, alerts: {}, overrides: {} }));
  }
  const auth = { Authorization: `Bearer ${env.ADMIN_KEY}` };
  const first = await json(await call(env, "GET", "/api/admin/profiles", { headers: auth }));
  assert.equal(first.profiles.length, 100);
  assert.ok(first.cursor);
  const second = await json(await call(env, "GET", `/api/admin/profiles?cursor=${first.cursor}`, { headers: auth }));
  assert.equal(second.profiles.length, 30);
  assert.equal(second.cursor, null);
});

test("rate-limit counters never show up in the admin listing", async () => {
  const env = makeEnv();
  await create(env);
  const out = await json(await call(env, "GET", "/api/admin/profiles", { headers: { Authorization: `Bearer ${env.ADMIN_KEY}` } }));
  assert.equal(out.profiles.length, 1);
});

test("CORS: our site is answered, other sites are not", async () => {
  const env = makeEnv();
  const ours = await call(env, "GET", "/api/health", { headers: { Origin: SITE } });
  assert.equal(ours.headers.get("Access-Control-Allow-Origin"), SITE);
  const theirs = await call(env, "GET", "/api/health", { headers: { Origin: "https://evil.example" } });
  assert.equal(theirs.headers.get("Access-Control-Allow-Origin"), null);
});

test("CORS preflight", async () => {
  const env = makeEnv();
  const res = await call(env, "OPTIONS", "/api/profile", { headers: { Origin: SITE, "Access-Control-Request-Method": "POST" } });
  assert.equal(res.status, 204);
  assert.equal(res.headers.get("Access-Control-Allow-Origin"), SITE);
  assert.match(res.headers.get("Access-Control-Allow-Methods"), /PUT/);
});

test("writes from another site are refused, writes with no Origin (scripts, the alert job) are fine", async () => {
  const env = makeEnv();
  const evil = await call(env, "POST", "/api/profile", { body: PROFILE, headers: { Origin: "https://evil.example" } });
  assert.equal(evil.status, 403);
  assert.equal(env.PROFILES.writes, 0);
  const local = await call(env, "POST", "/api/profile", { body: PROFILE, headers: { Origin: "http://localhost:8000" } });
  assert.equal(local.status, 201);
  assert.equal((await call(env, "POST", "/api/profile", { body: PROFILE, ip: "198.51.100.4" })).status, 201);
});

test("responses are never cached", async () => {
  const env = makeEnv();
  const made = await create(env);
  const res = await call(env, "GET", `/api/profile/${made.id}`);
  assert.equal(res.headers.get("Cache-Control"), "no-store");
});

test("unknown routes and trailing slashes", async () => {
  const env = makeEnv();
  assert.equal((await call(env, "GET", "/")).status, 404);
  assert.equal((await call(env, "GET", "/api/nope")).status, 404);
  assert.equal((await call(env, "GET", "/api/health/")).status, 200);
  const made = await create(env);
  assert.equal((await call(env, "PATCH", `/api/profile/${made.id}`)).status, 404);
});

test("the default export is a Worker fetch handler", async () => {
  const res = await worker.fetch(new Request("https://api.example.test/api/health"), makeEnv());
  assert.equal(res.status, 200);
});
