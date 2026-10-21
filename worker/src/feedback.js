// What a piece of feedback is, and the only shapes the service will store.
//
//   { kind: "break",   slug: "swamis", name: "Swami's", vote: "better" | "right" | "worse",
//     shown_rating: 6.3, shown_label: "Decent", note: "sets were way bigger", contact: "me@example.com" }
//   { kind: "general", note: "love the map", contact: "" }
//
// A break's feedback says how a session compared with the rating the site showed (`vote`), and is only useful with
// the rating that was showing, so `shown_rating` rides along. A `note` is free text, at most 500 characters. `contact`
// is optional and only ever read by the owner. Everything is plain text: nothing here is ever turned into markup.
//
// `cleanFeedback` returns { ok: true, feedback } with unknown keys dropped, or { ok: false, errors: [...] }.

export const VOTES = ["better", "right", "worse"];
export const MAX_NOTE = 500;
export const MAX_CONTACT = 80;
export const KEEP_SECONDS = 180 * 24 * 3600;      // feedback is kept for six months
export const PREFIX = "f:";

const SLUG = /^[a-z0-9][a-z0-9-]{0,39}$/;

// Control characters and angle brackets out; runs of spaces folded; trimmed.
const text = (s, max) => s.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f<>]/g, "").replace(/[ \t]+/g, " ").trim().slice(0, max);

export function cleanFeedback(input) {
  const errors = [];
  if (typeof input !== "object" || input === null || Array.isArray(input)) {
    return { ok: false, errors: ["feedback must be a JSON object"] };
  }

  const kind = input.kind === undefined ? (input.slug ? "break" : "general") : input.kind;
  if (kind !== "break" && kind !== "general") errors.push('kind must be "break" or "general"');

  const out = { kind };

  if (kind === "break") {
    if (typeof input.slug !== "string" || !SLUG.test(input.slug)) errors.push("slug must be a break name");
    else out.slug = input.slug;
    if (input.name !== undefined) {
      if (typeof input.name !== "string") errors.push("name must be text");
      else out.name = text(input.name, 40);
    }
    if (input.vote !== undefined && input.vote !== null && input.vote !== "") {
      if (!VOTES.includes(input.vote)) errors.push(`vote must be one of ${VOTES.join(", ")}`);
      else out.vote = input.vote;
    }
    if (input.shown_rating !== undefined && input.shown_rating !== null) {
      if (typeof input.shown_rating !== "number" || !Number.isFinite(input.shown_rating) || input.shown_rating < 0 || input.shown_rating > 10) {
        errors.push("shown_rating must be a number from 0 to 10");
      } else out.shown_rating = Math.round(input.shown_rating * 10) / 10;
    }
    if (input.shown_label !== undefined) {
      if (typeof input.shown_label !== "string") errors.push("shown_label must be text");
      else out.shown_label = text(input.shown_label, 20);
    }
  }

  let note = "";
  if (input.note !== undefined && input.note !== null) {
    if (typeof input.note !== "string") errors.push("note must be text");
    else if (input.note.length > MAX_NOTE * 2) errors.push(`note must be at most ${MAX_NOTE} characters`);
    else note = text(input.note, MAX_NOTE);
  }
  if (note) out.note = note;

  let contact = "";
  if (input.contact !== undefined && input.contact !== null) {
    if (typeof input.contact !== "string") errors.push("contact must be text");
    else contact = text(input.contact, MAX_CONTACT);
  }
  if (contact) out.contact = contact;

  if (!errors.length) {
    if (kind === "break" && !out.vote && !out.note) errors.push("pick how it compared, or write a note");
    if (kind === "general" && !out.note) errors.push("write a note");
  }

  return errors.length ? { ok: false, errors } : { ok: true, feedback: out };
}
