# Profile service

A small [Cloudflare Worker](https://developers.cloudflare.com/workers/) that stores anonymous surf
profiles for Swell Check: which breaks someone saved and what conditions they call ideal. The website
reads and writes it from the browser, and an hourly job reads it to send each person an alert about
an hour before their kind of conditions arrive.

There are no accounts and no emails. Making a profile returns a long random **id**; whoever holds it
can read, change and delete that profile, so it lives in the browser and can be copied as a private
link. A second random value, the **topic**, is the private [ntfy](https://ntfy.sh) channel that
person's alerts are sent to.

## API

| Request | What it does |
|---|---|
| `POST /api/profile` | Create a profile. Returns `{ id, topic, profile }` (201). |
| `GET /api/profile/:id` | Read it. |
| `PUT /api/profile/:id` | Replace it. The topic never changes. |
| `DELETE /api/profile/:id` | Delete it (204). |
| `GET /api/admin/profiles?cursor=` | Every profile, 100 at a time, for the alert job. Needs `Authorization: Bearer <ADMIN_KEY>`. Never returns ids. |
| `GET /api/health` | `{ "ok": true }` |

The shape of a profile, and every limit on it, is in [`src/validate.js`](src/validate.js).
New profiles are limited to 10 per address per hour, bodies to 8 KB, and writes from other websites
are refused. The address is only ever stored as a one-way hash for that hourly count.

## One-time setup (about 10 minutes, free, no card)

1. **Make a Cloudflare account** at <https://dash.cloudflare.com/sign-up> and confirm the email.
2. In Terminal, from this folder, log in. A browser tab opens; click **Allow**:

   ```bash
   cd "Swell Conditions App/worker" && npx wrangler login
   ```

3. **Deploy.** The first time it asks you to pick a free `workers.dev` name; any name is fine. It prints the
   Worker's address, like `https://swell-profiles.<your-name>.workers.dev`:

   ```bash
   npx wrangler deploy
   ```

4. **Make the alert job's key.** This copies a fresh random key to your clipboard, then stores it in
   Cloudflare (paste when asked):

   ```bash
   openssl rand -hex 32 | pbcopy
   npx wrangler secret put ADMIN_KEY
   ```

5. **Give GitHub the same key.** In the repository: Settings, Secrets and variables, Actions, New repository
   secret. Name it `PROFILES_ADMIN_KEY` and paste (the key is still on your clipboard).
6. Check it is up: open `https://swell-profiles.<your-name>.workers.dev/api/health`. You should see `{"ok":true}`.

## Running the tests

```bash
cd worker && npm test
```

They also run with the rest of the suite (`python3 -m unittest discover -s tests`).

## Limits to know about

Cloudflare's free plan allows 1,000 KV writes and 1,000 list calls a day, and 100,000 Worker requests a day.
Creating or editing a profile is one write (two for a new one, counting the rate limit), and the hourly alert
job is 24 list calls. That comfortably covers hundreds of people; past that, the paid plan is $5 a month.
