// Swell Check profile service: a Cloudflare Worker that keeps anonymous surf profiles in KV.
//
// There are no accounts. Creating a profile returns a long random `id`; whoever holds it can read,
// change and delete that profile, so the site keeps it in the browser and offers it as a private
// link. A second random value, the `topic`, is the private ntfy channel the person's alerts go to.
//
//   GET    /api/health                  -> { ok: true }
//   POST   /api/profile                 -> 201 { id, topic, profile }
//   GET    /api/profile/:id             -> { id, topic, profile }
//   PUT    /api/profile/:id             -> { id, topic, profile }     (replaces the profile)
//   DELETE /api/profile/:id             -> 204
//   GET    /api/admin/profiles?cursor=  -> { profiles: [...], cursor }  (Bearer ADMIN_KEY: the alert job)
//
// Bindings: PROFILES (KV), ADMIN_KEY (secret), ALLOWED_ORIGINS (comma-separated, set in wrangler.toml),
// optional CREATE_LIMIT_PER_HOUR (default 10 new profiles per address per hour).
//
// Cloudflare's free plan allows 1,000 KV writes and 1,000 list calls a day; a create or an edit is
// one write (two with the rate limit), and the hourly alert job is 24 list calls a day.

import { clean } from "./validate.js";

const MAX_BODY_BYTES = 8192;
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

async function tooManyCreates(request, env, now) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const hour = Math.floor(now / 3600000);
  const key = `rl:${hex((await digest(ip)).slice(0, 8))}:${hour}`;
  const limit = Number(env.CREATE_LIMIT_PER_HOUR) || 10;
  const used = Number(await env.PROFILES.get(key)) || 0;
  if (used >= limit) return true;
  await env.PROFILES.put(key, String(used + 1), { expirationTtl: 3700 });
  return false;
}

const view = (id, stored) => {
  const { topic, created, updated, ...profile } = stored;
  return { id, topic, created, updated, profile };
};

async function adminList(request, env, url) {
  if (!env.ADMIN_KEY) return reply(request, env, 503, { error: "Admin access is not configured." });
  const auth = request.headers.get("Authorization") || "";
  if (!auth.startsWith("Bearer ") || !(await safeEqual(auth.slice(7), env.ADMIN_KEY))) {
    return reply(request, env, 401, { error: "Unauthorized." });
  }
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

  if (path === "/api/health" && method === "GET") return reply(request, env, 200, { ok: true });
  if (path === "/api/admin/profiles" && method === "GET") return adminList(request, env, url);

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
};
