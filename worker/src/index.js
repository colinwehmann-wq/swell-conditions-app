// Swell Check profile service: a Cloudflare Worker that keeps anonymous surf profiles in KV.
//
// There are no accounts. Creating a profile returns a long random `id`; whoever holds it can read,
// change and delete that profile, so the site keeps it in the browser and offers it as a private
// link. A second random value, the `topic`, is the private ntfy channel the person's alerts go to.
//
//   GET    /api/health                  -> { ok: true, dispatch: last wake-up of the alert job, site: of the site rebuild }
//   POST   /api/profile                 -> 201 { id, topic, profile }
//   GET    /api/profile/:id             -> { id, topic, profile }
//   PUT    /api/profile/:id             -> { id, topic, profile }     (replaces the profile)
//   DELETE /api/profile/:id             -> 204
//   GET    /api/admin/profiles?cursor=  -> { profiles: [...], cursor }  (Bearer ADMIN_KEY: the alert job)
//
// Bindings: PROFILES (KV), ADMIN_KEY (secret), ALLOWED_ORIGINS (comma-separated, set in wrangler.toml),
// optional CREATE_LIMIT_PER_HOUR (default 10 new profiles per address per hour), and for the cron wake-up
// GITHUB_DISPATCH_TOKEN (secret), GITHUB_REPO, GITHUB_WORKFLOW and GITHUB_SITE_WORKFLOW (see dispatch.js).
//
// Cloudflare's free plan allows 1,000 KV writes and 1,000 list calls a day; a create or an edit is
// one write (two with the rate limit), and the hourly alert job is 24 list calls a day.

import { dispatch, dispatchSite, lastDispatch, SITE_META_KEY } from "./dispatch.js";
import { cleanFeedback, KEEP_SECONDS, PREFIX as FEEDBACK_PREFIX } from "./feedback.js";
import { clean } from "./validate.js";

const MAX_BODY_BYTES = 8192;
const MAX_FEEDBACK_BYTES = 4096;
const PAGE = 100;
const ID_RE = /^[A-Za-z0-9_-]{22}$/;

const b64url = (bytes) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const hex = (bytes) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
const randomBytes = (n) => crypto.getRandomValues(new Uint8Array(n));

export const newId = () => b64url(randomBytes(16));                 // 128 bits -> 22 characters
export const newTopic = () => `swell-${hex(randomBytes(12))}`;       // 96 bits, hard to guess

async function digest(text) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)));
}

async function safeEqual(a, b) {
  const [x, y] = await Promise.all([digest(a), digest(b)]);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

function allowedOrigins(env) {
  return (env.ALLOWED_ORIGINS || "").split(",").map((s) => s.trim()).filter(Boolean);
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin");
  if (!origin || !allowedOrigins(env).includes(origin)) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

function reply(request, env, status, body, extra = {}) {
  const headers = { "Cache-Control": "no-store", ...corsHeaders(request, env), ...extra };
  if (body === null) return new Response(null, { status, headers });
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > MAX_BODY_BYTES) return { error: "That is too large for a profile.", status: 413 };
  try {
    return { value: JSON.parse(text) };
  } catch {
    return { error: "The request body must be JSON.", status: 400 };
  }
}

// True when this address has used up its allowance for `kind` this hour (and counts this attempt if not). Only a
// one-way hash of the address is ever kept, for the hour.
async function overLimit(request, env, now, kind, limit) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const hour = Math.floor(now / 3600000);
  const key = `rl:${kind}:${hex((await digest(ip)).slice(0, 8))}:${hour}`;
  const used = Number(await env.PROFILES.get(key)) || 0;
  if (used >= limit) return true;
  await env.PROFILES.put(key, String(used + 1), { expirationTtl: 3700 });
  return false;
}

const tooManyCreates = (request, env, now) => overLimit(request, env, now, "create", Number(env.CREATE_LIMIT_PER_HOUR) || 10);

const view = (id, stored) => {
  const { topic, created, updated, ...profile } = stored;
  return { id, topic, created, updated, profile };
};

// null when the caller holds the admin key, otherwise the response to send back.
async function adminDenied(request, env) {
  if (!env.ADMIN_KEY) return reply(request, env, 503, { error: "Admin access is not configured." });
  const auth = request.headers.get("Authorization") || "";
  if (!auth.startsWith("Bearer ") || !(await safeEqual(auth.slice(7), env.ADMIN_KEY))) {
    return reply(request, env, 401, { error: "Unauthorized." });
  }
  return null;
}

// Feedback newer than ?after=<ISO time>, oldest first, for the job that forwards it to the owner's phone.
async function adminFeedback(request, env, url) {
  const denied = await adminDenied(request, env);
  if (denied) return denied;
  const after = url.searchParams.get("after") || "";
  const limit = Math.min(Number(url.searchParams.get("limit")) || 50, 100);
  const items = [];
  let cursor;
  do {
    const page = await env.PROFILES.list({ prefix: FEEDBACK_PREFIX, limit: 1000, cursor });
    for (const k of page.keys) {
      if (items.length >= limit) break;
      const when = k.name.slice(FEEDBACK_PREFIX.length, FEEDBACK_PREFIX.length + 24);     // the ISO time; the key goes on with ":<random>"
      if (after && when <= after) continue;
      const value = await env.PROFILES.get(k.name, "json");
      if (value) items.push(value);
    }
    cursor = page.list_complete || items.length >= limit ? undefined : page.cursor;
  } while (cursor);
  return reply(request, env, 200, { items, last: items.length ? items[items.length - 1].t : after || null });
}

async function adminList(request, env, url) {
  const denied = await adminDenied(request, env);
  if (denied) return denied;
  const page = await env.PROFILES.list({ prefix: "p:", limit: PAGE, cursor: url.searchParams.get("cursor") || undefined });
  const rows = await Promise.all(page.keys.map((k) => env.PROFILES.get(k.name, "json")));
  // The id is the owner's secret, so it is never handed to the alert job: the topic names a profile there.
  const profiles = rows.filter(Boolean).map(({ topic, updated, ...profile }) => ({ topic, updated, ...profile }));
  return reply(request, env, 200, { profiles, cursor: page.list_complete ? null : page.cursor });
}

export async function handle(request, env, now = Date.now()) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "");
  const method = request.method;

  if (method === "OPTIONS") return reply(request, env, 204, null);

  // Browsers always say where a request came from. Refuse writes from sites that aren't ours.
  const origin = request.headers.get("Origin");
  if (origin && method !== "GET" && !allowedOrigins(env).includes(origin)) {
    return reply(request, env, 403, { error: "This origin is not allowed." });
  }

  if (path === "/api/health" && method === "GET") return reply(request, env, 200, { ok: true, dispatch: await lastDispatch(env), site: await lastDispatch(env, SITE_META_KEY) });
  if (path === "/api/admin/profiles" && method === "GET") return adminList(request, env, url);
  if (path === "/api/admin/feedback" && method === "GET") return adminFeedback(request, env, url);

  if (path === "/api/feedback" && method === "POST") {
    const text = await request.text();
    if (text.length > MAX_FEEDBACK_BYTES) return reply(request, env, 413, { error: "That is too long." });
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch {
      return reply(request, env, 400, { error: "The request body must be JSON." });
    }
    const result = cleanFeedback(parsed);
    if (!result.ok) return reply(request, env, 400, { errors: result.errors });
    if (await overLimit(request, env, now, "feedback", Number(env.FEEDBACK_LIMIT_PER_HOUR) || 20)) {
      return reply(request, env, 429, { error: "That is a lot of feedback from one connection. Try again in an hour." }, { "Retry-After": "3600" });
    }
    const t = new Date(now).toISOString();
    // The key sorts by time, so listing the prefix returns feedback oldest first.
    await env.PROFILES.put(`${FEEDBACK_PREFIX}${t}:${hex(randomBytes(3))}`, JSON.stringify({ t, ...result.feedback }), { expirationTtl: KEEP_SECONDS });
    return reply(request, env, 201, { ok: true });
  }

  if (path === "/api/profile" && method === "POST") {
    const body = await readJson(request);
    if (body.error) return reply(request, env, body.status, { error: body.error });
    const result = clean(body.value);
    if (!result.ok) return reply(request, env, 400, { errors: result.errors });
    if (await tooManyCreates(request, env, now)) {
      return reply(request, env, 429, { error: "Too many new profiles from this address. Try again later." }, { "Retry-After": "3600" });
    }
    const id = newId();
    const stored = { ...result.profile, topic: newTopic(), created: new Date(now).toISOString(), updated: new Date(now).toISOString() };
    await env.PROFILES.put(`p:${id}`, JSON.stringify(stored));
    return reply(request, env, 201, view(id, stored));
  }

  const m = path.match(/^\/api\/profile\/([^/]+)$/);
  if (m) {
    const id = m[1];
    if (!ID_RE.test(id)) return reply(request, env, 404, { error: "No such profile." });
    const existing = await env.PROFILES.get(`p:${id}`, "json");
    if (!existing) return reply(request, env, 404, { error: "No such profile." });

    if (method === "GET") return reply(request, env, 200, view(id, existing));

    if (method === "PUT") {
      const body = await readJson(request);
      if (body.error) return reply(request, env, body.status, { error: body.error });
      const result = clean(body.value);
      if (!result.ok) return reply(request, env, 400, { errors: result.errors });
      const stored = { ...result.profile, topic: existing.topic, created: existing.created, updated: new Date(now).toISOString() };
      await env.PROFILES.put(`p:${id}`, JSON.stringify(stored));
      return reply(request, env, 200, view(id, stored));
    }

    if (method === "DELETE") {
      await env.PROFILES.delete(`p:${id}`);
      return reply(request, env, 204, null);
    }
  }

  return reply(request, env, 404, { error: "Not found." });
}

export default {
  fetch(request, env) {
    return handle(request, env);
  },
  // Runs on the cron trigger in wrangler.toml: wake the alert job on GitHub (see dispatch.js).
  scheduled(event, env, ctx) {
    const when = event.scheduledTime || Date.now();
    ctx.waitUntil(Promise.all([dispatch(env, when), dispatchSite(env, when)]));
  },
};
