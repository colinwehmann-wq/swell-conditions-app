/* "How was it?": one-tap feedback on a break, and the general feedback form.
 *
 * It posts to the profile service (worker/, route /api/feedback; the shape it accepts is worker/src/feedback.js).
 * The top half is plain functions so tests/test_feedback_js.py can run them under Node; the bottom half wires the
 * forms on the page. Text only ever goes in with textContent, never as markup.
 *
 * A break's vote says how a session compared with the rating the site showed, so the rating that was showing
 * (data-rating, data-label on the form) is sent along with it. That is what makes a vote usable for tuning the ratings.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SwellFeedback = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var VOTES = ['better', 'right', 'worse'];
  var MAX_NOTE = 500;
  var MAX_CONTACT = 80;

  function clean(text, max) {
    return String(text === undefined || text === null ? '' : text).replace(/[<>]/g, '').trim().slice(0, max);
  }

  /* Form values -> { feedback } to send, or { errors: [...] } in plain words. The service checks it all again. */
  function buildFeedback(v) {
    var errors = [];
    var kind = v.kind === 'break' ? 'break' : 'general';
    var note = clean(v.note, MAX_NOTE);
    var contact = clean(v.contact, MAX_CONTACT);
    var out = { kind: kind };

    if (kind === 'break') {
      if (!v.slug) errors.push('Something went wrong: this form does not know which break it is for.');
      out.slug = v.slug;
      if (v.name) out.name = clean(v.name, 40);
      if (v.vote) {
        if (VOTES.indexOf(v.vote) === -1) errors.push('Pick better, about right or worse.');
        else out.vote = v.vote;
      }
      var shown = Number(v.shown_rating);
      if (v.shown_rating !== undefined && v.shown_rating !== null && v.shown_rating !== '' && isFinite(shown) && shown >= 0 && shown <= 10) {
        out.shown_rating = Math.round(shown * 10) / 10;
        if (v.shown_label) out.shown_label = clean(v.shown_label, 20);
      }
      if (!out.vote && !note && !errors.length) errors.push('Pick how it compared with the rating, or write a note.');
    } else if (!note) {
      errors.push('Write a note first.');
    }

    if (String(v.note || '').length > MAX_NOTE * 2) errors.push('That note is too long: keep it under ' + MAX_NOTE + ' characters.');
    if (note) out.note = note;
    if (contact) out.contact = contact;
    return errors.length ? { errors: errors } : { feedback: out };
  }

  /* Whether the form has enough to send. */
  function canSend(v) { return !buildFeedback(v).errors; }

  /* One "already told us" flag per break per day, so the form can say thanks instead of inviting a second vote. */
  function sentKey(slug, date) {
    var d = date || new Date();
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    return 'swell-fb-' + slug + '-' + d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  var api = { VOTES: VOTES, MAX_NOTE: MAX_NOTE, MAX_CONTACT: MAX_CONTACT, buildFeedback: buildFeedback, canSend: canSend, sentKey: sentKey };

  // ----------------------------------------------------------------------------- the page
  if (typeof document === 'undefined') return api;

  Array.prototype.forEach.call(document.querySelectorAll('[data-feedback]'), function (rootEl) {
    var API = (rootEl.getAttribute('data-api') || '').replace(/\/+$/, '');
    var kind = rootEl.getAttribute('data-kind') === 'break' ? 'break' : 'general';
    var slug = rootEl.getAttribute('data-slug') || '';
    var form = rootEl.querySelector('[data-fb-form]');
    var thanks = rootEl.querySelector('[data-fb-thanks]');
    var send = rootEl.querySelector('[data-fb-send]');
    var status = rootEl.querySelector('[data-fb-status]');
    var note = rootEl.querySelector('[name="note"]');
    var contact = rootEl.querySelector('[name="contact"]');
    var votes = Array.prototype.slice.call(rootEl.querySelectorAll('[data-vote]'));
    var chosen = '';

    function values() {
      return {
        kind: kind, slug: slug, name: rootEl.getAttribute('data-name') || '', vote: chosen,
        shown_rating: rootEl.getAttribute('data-rating'), shown_label: rootEl.getAttribute('data-label') || '',
        note: note ? note.value : '', contact: contact ? contact.value : ''
      };
    }
    function say(text) { if (status) status.textContent = text || ''; }
    function refresh() { send.disabled = !canSend(values()); }
    function done() {
      form.hidden = true;
      thanks.hidden = false;
    }

    var key = kind === 'break' && slug ? sentKey(slug) : null;
    try { if (key && localStorage.getItem(key)) done(); } catch (e) { /* no storage: the form simply stays */ }

    votes.forEach(function (b) {
      b.addEventListener('click', function () {
        chosen = chosen === b.getAttribute('data-vote') ? '' : b.getAttribute('data-vote');
        votes.forEach(function (o) { o.setAttribute('aria-pressed', o.getAttribute('data-vote') === chosen ? 'true' : 'false'); });
        refresh();
      });
    });
    [note, contact].forEach(function (el) { if (el) el.addEventListener('input', refresh); });

    send.addEventListener('click', function () {
      var built = buildFeedback(values());
      if (built.errors) { say(built.errors[0]); return; }
      send.disabled = true;
      say('Sending…');
      fetch(API + '/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(built.feedback) })
        .then(function (res) {
          if (res.status === 201) {
            try { if (key) localStorage.setItem(key, '1'); } catch (e) { /* fine */ }
            say('');
            done();
          } else if (res.status === 429) {
            say('That is a lot of feedback from this connection. Try again in an hour.');
            send.disabled = false;
          } else {
            say('Couldn\'t send that. Try again in a moment.');
            send.disabled = false;
          }
        }, function () {
          say('Couldn\'t reach the site\'s server. Check your connection and try again.');
          send.disabled = false;
        });
    });

    refresh();
    rootEl.setAttribute('data-ready', '1');
  });

  return api;
}));
