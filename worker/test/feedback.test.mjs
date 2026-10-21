import test from "node:test";
import assert from "node:assert/strict";
import { handle } from "../src/index.js";
import { cleanFeedback, MAX_NOTE, MAX_CONTACT, KEEP_SECONDS } from "../src/feedback.js";

const SITE = "https://colinwehmann-wq.github.io";

class FakeKV {
  constructor() {
    this.data = new Map();
    this.ttls = new Map();
  }
  async get(key, type) {
    const v = this.data.get(key);
    if (v === undefined) return null;
    return type === "json" ? JSON.parse(v) : v;
  }
  async put(key, value, opts = {}) {
    this.data.set(key, value);
    if (opts.expirationTtl) this.ttls.set(key, opts.expirationTtl);
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

const KEY = "k".repeat(40);
const makeEnv = (extra = {}) => ({ PROFILES: new FakeKV(), ADMIN_KEY: KEY, ALLOWED_ORIGINS: SITE, ...extra });
const ADMIN = { Authorization: `Bearer ${KEY}` };

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

const T0 = Date.UTC(2026, 9, 20, 14, 0, 0);
const BREAK = { kind: "break", slug: "beacons", name: "Beacon's", vote: "better", shown_rating: 8.4, shown_label: "Excellent", note: "perfect at 5:45", contact: "" };

const ok = (input) => {
  const r = cleanFeedback(input);
  assert.equal(r.ok, true, JSON.stringify(r.errors));
  return r.feedback;
};
const bad = (input) => {
  const r = cleanFeedback(input);
  assert.equal(r.ok, false);
  return r.errors.join(" | ");
};

// ---- the shape -----------------------------------------------------------------------------------

test("a break vote with the rating that was showing", () => {
  assert.deepEqual(ok(BREAK), { kind: "break", slug: "beacons", name: "Beacon's", vote: "better", shown_rating: 8.4, shown_label: "Excellent", note: "perfect at 5:45" });
});

test("a vote alone, or a note alone, is enough for a break; neither is not", () => {
  assert.equal(ok({ kind: "break", slug: "swamis", vote: "right" }).vote, "right");
  assert.equal(ok({ kind: "break", slug: "swamis", note: "sets were far apart" }).note, "sets were far apart");
  assert.match(bad({ kind: "break", slug: "swamis" }), /pick how it compared/);
});

test("general feedback needs a note", () => {
  assert.equal(ok({ kind: "general", note: "love the map" }).note, "love the map");
  assert.match(bad({ kind: "general" }), /write a note/);
  assert.match(bad({ kind: "general", note: "   " }), /write a note/);
});

test("the kind is worked out from the slug when it is left out", () => {
  assert.equal(ok({ slug: "swamis", vote: "worse" }).kind, "break");
  assert.equal(ok({ note: "hi" }).kind, "general");
});

test("votes, slugs and ratings are checked", () => {
  assert.match(bad({ kind: "break", slug: "swamis", vote: "amazing" }), /vote must be one of/);
  assert.match(bad({ kind: "break", slug: "../etc", vote: "right" }), /slug must be a break name/);
  assert.match(bad({ kind: "break", vote: "right" }), /slug must be a break name/);
  assert.match(bad({ kind: "break", slug: "swamis", vote: "right", shown_rating: 11 }), /0 to 10/);
  assert.match(bad({ kind: "break", slug: "swamis", vote: "right", shown_rating: "8" }), /0 to 10/);
  assert.match(bad({ kind: "party" }), /kind must be/);
});

test("the rating that was showing is kept to one decimal", () => {
  assert.equal(ok({ kind: "break", slug: "swamis", vote: "right", shown_rating: 7.349 }).shown_rating, 7.3);
});

test("text is cleaned: no angle brackets or control characters, spaces folded, length capped", () => {
  const f = ok({ kind: "general", note: "  <b>hi</b>\u0007   there  ", contact: " a@b.co " });
  assert.equal(f.note, "bhi/b there");
  assert.equal(f.contact, "a@b.co");
  assert.equal(ok({ kind: "general", note: "x".repeat(MAX_NOTE + 50) }).note.length, MAX_NOTE);
  assert.equal(ok({ kind: "general", note: "hi", contact: "y".repeat(200) }).contact.length, MAX_CONTACT);
  assert.match(bad({ kind: "general", note: "x".repeat(MAX_NOTE * 2 + 1) }), /at most/);
});

test("newlines in a note survive, so a longer note stays readable", () => {
  assert.equal(ok({ kind: "general", note: "line one\nline two" }).note, "line one\nline two");
});

test("unknown keys are dropped, and non-objects refused", () => {
  assert.equal(ok({ kind: "general", note: "hi", admin: true, t: "2020" }).admin, undefined);
  assert.equal(ok({ kind: "general", note: "hi", t: "2020-01-01" }).t, undefined);
  assert.match(bad(null), /JSON object/);
  assert.match(bad([]), /JSON object/);
});

// ---- the service ---------------------------------------------------------------------------------

test("posting feedback stores it with the time and a six-month expiry", async () => {
  const env = makeEnv();
  const res = await call(env, "POST", "/api/feedback", { body: BREAK, now: T0 });
  assert.equal(res.status, 201);
  assert.deepEqual(await res.json(), { ok: true });
  const [key] = [...env.PROFILES.data.keys()].filter((k) => k.startsWith("f:"));
  assert.match(key, /^f:2026-10-20T14:00:00\.000Z:[0-9a-f]{6}$/);
  assert.equal(JSON.parse(env.PROFILES.data.get(key)).t, "2026-10-20T14:00:00.000Z");
  assert.equal(env.PROFILES.ttls.get(key), KEEP_SECONDS);
});

test("bad feedback is a 400 and stores nothing", async () => {
  const env = makeEnv();
  assert.equal((await call(env, "POST", "/api/feedback", { body: { kind: "break", slug: "swamis" } })).status, 400);
  assert.equal((await call(env, "POST", "/api/feedback", { body: "{nope" })).status, 400);
  assert.equal((await call(env, "POST", "/api/feedback", { body: "x".repeat(5000) })).status, 413);
  assert.equal([...env.PROFILES.data.keys()].filter((k) => k.startsWith("f:")).length, 0);
});

test("feedback is limited per address per hour", async () => {
  const env = makeEnv({ FEEDBACK_LIMIT_PER_HOUR: "3" });
  for (let i = 0; i < 3; i++) assert.equal((await call(env, "POST", "/api/feedback", { body: BREAK, now: T0 })).status, 201);
  const blocked = await call(env, "POST", "/api/feedback", { body: BREAK, now: T0 });
  assert.equal(blocked.status, 429);
  assert.equal(blocked.headers.get("Retry-After"), "3600");
  assert.equal((await call(env, "POST", "/api/feedback", { body: BREAK, now: T0, ip: "198.51.100.9" })).status, 201);
  assert.equal((await call(env, "POST", "/api/feedback", { body: BREAK, now: T0 + 3600000 })).status, 201);
});

test("the feedback limit and the profile limit are separate", async () => {
  const env = makeEnv({ FEEDBACK_LIMIT_PER_HOUR: "1", CREATE_LIMIT_PER_HOUR: "1" });
  assert.equal((await call(env, "POST", "/api/feedback", { body: BREAK, now: T0 })).status, 201);
  assert.equal((await call(env, "POST", "/api/profile", { body: { breaks: ["swamis"] }, now: T0 })).status, 201);
});

test("other websites cannot post feedback, our site can", async () => {
  const env = makeEnv();
  assert.equal((await call(env, "POST", "/api/feedback", { body: BREAK, headers: { Origin: "https://evil.example" } })).status, 403);
  const ours = await call(env, "POST", "/api/feedback", { body: BREAK, headers: { Origin: SITE } });
  assert.equal(ours.status, 201);
  assert.equal(ours.headers.get("Access-Control-Allow-Origin"), SITE);
});

test("the address is never stored with feedback", async () => {
  const env = makeEnv();
  await call(env, "POST", "/api/feedback", { body: BREAK, ip: "203.0.113.77", now: T0 });
  for (const [k, v] of env.PROFILES.data) assert.equal(k.includes("203.0.113.77") || String(v).includes("203.0.113.77"), false);
});

// ---- reading it back -----------------------------------------------------------------------------

test("only the key holder can read feedback", async () => {
  const env = makeEnv();
  await call(env, "POST", "/api/feedback", { body: BREAK, now: T0 });
  assert.equal((await call(env, "GET", "/api/admin/feedback")).status, 401);
  assert.equal((await call(env, "GET", "/api/admin/feedback", { headers: { Authorization: "Bearer wrong" } })).status, 401);
  assert.equal((await call(makeEnv({ ADMIN_KEY: undefined }), "GET", "/api/admin/feedback", { headers: ADMIN })).status, 503);
  const out = await (await call(env, "GET", "/api/admin/feedback", { headers: ADMIN })).json();
  assert.equal(out.items.length, 1);
  assert.equal(out.items[0].slug, "beacons");
});

test("feedback comes back oldest first, and only what is newer than ?after", async () => {
  const env = makeEnv();
  for (let i = 0; i < 4; i++) await call(env, "POST", "/api/feedback", { body: { kind: "general", note: `n${i}` }, now: T0 + i * 60000, ip: `198.51.100.${i}` });
  const all = await (await call(env, "GET", "/api/admin/feedback", { headers: ADMIN })).json();
  assert.deepEqual(all.items.map((i) => i.note), ["n0", "n1", "n2", "n3"]);
  assert.equal(all.last, all.items[3].t);
  const newer = await (await call(env, "GET", `/api/admin/feedback?after=${encodeURIComponent(all.items[1].t)}`, { headers: ADMIN })).json();
  assert.deepEqual(newer.items.map((i) => i.note), ["n2", "n3"]);
  const none = await (await call(env, "GET", `/api/admin/feedback?after=${encodeURIComponent(all.last)}`, { headers: ADMIN })).json();
  assert.deepEqual(none.items, []);
  assert.equal(none.last, all.last);                                      // nothing new: the marker stays where it was
});

test("the limit caps a batch, and the marker lets the next call carry on", async () => {
  const env = makeEnv();
  for (let i = 0; i < 5; i++) await call(env, "POST", "/api/feedback", { body: { kind: "general", note: `n${i}` }, now: T0 + i * 1000, ip: `198.51.100.${i}` });
  const first = await (await call(env, "GET", "/api/admin/feedback?limit=2", { headers: ADMIN })).json();
  assert.deepEqual(first.items.map((i) => i.note), ["n0", "n1"]);
  const second = await (await call(env, "GET", `/api/admin/feedback?limit=2&after=${encodeURIComponent(first.last)}`, { headers: ADMIN })).json();
  assert.deepEqual(second.items.map((i) => i.note), ["n2", "n3"]);
});

test("feedback does not leak into the profile listing, or the other way round", async () => {
  const env = makeEnv();
  await call(env, "POST", "/api/feedback", { body: BREAK, now: T0 });
  await call(env, "POST", "/api/profile", { body: { breaks: ["swamis"] }, now: T0 });
  const profiles = await (await call(env, "GET", "/api/admin/profiles", { headers: ADMIN })).json();
  assert.equal(profiles.profiles.length, 1);
  assert.equal(profiles.profiles[0].note, undefined);
  const fb = await (await call(env, "GET", "/api/admin/feedback", { headers: ADMIN })).json();
  assert.equal(fb.items.length, 1);
  assert.equal(fb.items[0].topic, undefined);
});

test("health never shows feedback", async () => {
  const env = makeEnv({ ALLOWED_ORIGINS: "" });
  await call(env, "POST", "/api/feedback", { body: { kind: "general", note: "secret thought", contact: "me@example.com" }, now: T0 });
  const text = await (await call(env, "GET", "/api/health")).text();
  assert.equal(text.includes("secret thought") || text.includes("me@example.com"), false);
});
