# WhatsApp Handler

A self-hosted web portal that links a WhatsApp account to your own server, answers
incoming messages with Google Gemini under rules you write, and lets your other
applications send WhatsApp messages through a REST API.

Everything runs on your machine in four Docker containers. There is no SaaS
account, no third-party relay, and no Meta Business API: the connection is the
same "linked device" channel WhatsApp Web uses, driven by the open-source
[neonize](https://github.com/krypton-byte/neonize) / whatsmeow library.

> **Before you start:** this uses an *unofficial* connection to WhatsApp and is
> against WhatsApp's Terms of Service. Read the [disclaimer](#-disclaimer--read-this-before-you-use-it)
> at the bottom of this file.

---

## Table of contents

- [What this project is](#what-this-project-is)
- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Run it on localhost](#run-it-on-localhost)
- [First-time setup in the portal](#first-time-setup-in-the-portal)
- [Configuration reference](#configuration-reference)
- [The portal](#the-portal)
- [Public REST API](#public-rest-api)
- [Where your data lives](#where-your-data-lives)
- [Security](#security)
- [Operations](#operations)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Not implemented yet](#not-implemented-yet)
- [Disclaimer](#-disclaimer--read-this-before-you-use-it)

---

## What this project is

A single-tenant control panel for one WhatsApp number. You sign in to a web
portal, scan a QR code with your phone, and from then on the server holds a live
WhatsApp connection on your behalf. With that connection in place you can:

- **Answer messages automatically with AI.** Paste a Gemini API key, write
  instructions describing what the assistant may and may not talk about, and
  every incoming text message gets a reply that follows those rules. Each chat
  keeps its own conversation memory, so it follows a thread instead of meeting
  every message cold.
- **Send messages from your own software.** Issue API keys from the portal and
  `POST` to a REST endpoint from any language — a website contact form, a CRM,
  a cron job, an order system.
- **Control the pacing.** Choose when the blue ticks appear and when the
  "typing…" indicator starts, so replies do not land the instant a message
  arrives.

**Who it is for:** a developer or small business running their own server who
wants an AI responder or an outbound message API for a number they control.

**Who it is not for:** anything at scale, anything involving numbers you do not
own, marketing blasts, or unsolicited messaging. See the
[disclaimer](#-disclaimer--read-this-before-you-use-it).

---

## Features

| | |
|---|---|
| **QR linking** | Scan once from the portal. The session is stored in PostgreSQL, so rebuilds and restarts never require re-scanning. |
| **Self-healing connection** | If you unlink the device from your phone, the portal notices within seconds, restarts the client and shows a fresh QR. A network blip shows *Reconnecting…* and keeps the session. |
| **AI auto-reply** | Gemini answers incoming messages using your written instructions. Off by default. |
| **Scope control** | Exclude one-to-one chats and/or group chats. Groups are excluded by default. |
| **Conversation memory** | Per-chat history (last 10 turns, 24-hour window) so conversations have continuity. Contacts never share context. |
| **Human-like pacing** | Configurable blue-tick delay and typing-indicator delay, 1–60 seconds each. |
| **Typing indicator** | The other person sees "typing…" while the model works, refreshed until the reply is ready. |
| **REST API** | Hash-stored API keys, a versioned `POST /api/v1/messages/` endpoint, copy-paste examples in the UI. |
| **Test tools** | Send a test WhatsApp message and probe Gemini with your instructions before going live. |
| **Mobile-ready** | The portal works on a phone: bottom tab bar, proper tap targets, no zoom-on-focus. |

---

## How it works

Four containers on one Docker network. Only the frontend publishes a port.

```
                       ┌───────────────────────────────────────────┐
   Your browser ─────► │ frontend (nginx :8080)                    │
                       │  • serves the React app                   │
                       │  • proxies /api/ and /admin/ to Django     │
                       └───────────────┬───────────────────────────┘
                                       │ (internal network only)
                       ┌───────────────▼───────────────┐
                       │ backend (Django + DRF :8000)  │
                       │  • token login, settings, keys │
                       │  • public /api/v1/messages/    │
                       └───────┬───────────────┬────────┘
                               │               │
        ┌──────────────────────▼──┐         ┌──▼──────────────────────────┐
        │ worker (:8100)          │         │ db (PostgreSQL :5432)       │
        │  • holds the WhatsApp   │◄───────►│  • WhatsApp session         │
        │    connection (neonize) │  reads  │  • portal settings          │
        │  • auto-replies via     │ config  │  • API keys (hashed)        │
        │    Gemini               │ directly│  • per-chat memory          │
        └───────────┬─────────────┘         └─────────────────────────────┘
                    │
                    ▼
          WhatsApp servers  ◄──►  Google Gemini API
```

**Outbound message** (from your app): `POST /api/v1/messages/` → nginx → Django
validates the API key → calls the worker's internal `/send` → whatsmeow → WhatsApp.

**Incoming message** (auto-reply): WhatsApp → worker event handler → worker reads
settings straight from PostgreSQL (5-second cache) → optional read-receipt delay →
typing delay → typing indicator on → Gemini call with this chat's recent history →
reply sent → both sides appended to that chat's memory.

The worker reads its configuration directly from the same PostgreSQL database
Django writes to. That avoids exposing another HTTP endpoint that would need its
own secret, and means settings changed in the portal take effect within about
five seconds, with no restart.

---

## Requirements

- **Docker** and **Docker Compose v2** (`docker compose`, not `docker-compose`).
  Docker Desktop on macOS/Windows includes both.
- About **2 GB free RAM** and 2 GB disk.
- A **WhatsApp account on a phone** you can scan a QR code with.
- Optional: a **Google Gemini API key** from [Google AI Studio](https://aistudio.google.com/apikey)
  if you want AI replies.
- Ports: **8080** on the host (configurable). Nothing else is published.

Apple Silicon works — the worker image is pinned to `linux/amd64` and runs under
emulation, which is fine for an I/O-bound service.

---

## Run it on localhost

### 1. Get the code

```bash
git clone https://github.com/<your-username>/whatsapp-handler.git
cd whatsapp-handler
```

### 2. Create your environment file

```bash
cp .env.example .env
```

Open `.env` and set two values. Everything else has a working default:

```bash
# A strong database password
POSTGRES_PASSWORD=<paste a long random string>

# Django's signing key — generate one with the command below
DJANGO_SECRET_KEY=<paste a long random string>
```

Generate both:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

`.env` is listed in `.gitignore` and must never be committed.

### 3. Build and start

```bash
docker compose up -d --build
```

The first build takes a few minutes. Check that all four containers are up:

```bash
docker compose ps
```

You want `db`, `worker`, `backend` and `frontend` all showing `Up`
(`db` should also say `healthy`).

### 4. Create your portal login

```bash
docker compose exec backend python manage.py createsuperuser
```

Enter a username and password. This is the account you sign in to the portal
with — it is not related to WhatsApp.

### 5. Open the portal

<http://localhost:8080>

Sign in with the user you just created. You should land on **Settings** with a
QR code waiting.

### 6. Stop it again

```bash
docker compose down          # stops everything, keeps your data
docker compose down -v       # ALSO deletes the database and the WhatsApp session
```

---

## First-time setup in the portal

### Link your WhatsApp account

On **Settings → Account connection**, a QR code appears. On your phone:

**WhatsApp → Settings → Linked devices → Link a device → scan the code.**

The panel switches to *Connected* within a couple of seconds. The session is
saved in PostgreSQL, so restarting or rebuilding never asks you to scan again.

If the QR does not appear, watch the worker starting up:

```bash
docker compose logs -f worker
```

### Send a test message

**Settings → Send a test message.** Enter a phone number as country code +
number, digits only (`971568854459`, not `+971 56 885 4459`), type something and
press Send.

### Connect Gemini (optional)

**Settings → Gemini AI:**

1. Paste an API key from [Google AI Studio](https://aistudio.google.com/apikey).
2. Pick a model. The default is `gemini-3.6-flash`; `gemini-3.5-flash-lite` is
   cheaper, faster and has a far more generous free-tier allowance.
3. Write your **instructions** — this is the system prompt, and it is what keeps
   the assistant on topic. Be explicit about what it should handle and what it
   should say when a message falls outside that.
4. Press **Test with Gemini** to try it. The test uses whatever is currently in
   the form, including unsaved edits, so you can tune the wording and see the
   reply before saving.
5. Press **Save settings**.

An instruction that works well looks like this:

```
You are the assistant for Acme Bakery. Answer only questions about our opening
hours, menu, prices and order status. If a message is about anything else,
politely say you can only help with bakery questions and offer our phone number.
Never invent prices or availability.
```

### Turn on automatic replies (optional)

**Automation** page. Nothing here works until a Gemini key is saved — the page
tells you so and links back to Settings.

- **Reply to every incoming message** — the master switch.
- **Don't reply in these chats** — tick *One-person chats* and/or *Group chats*
  to exclude them. Group chats are excluded by default.
- **Timing** — *Blue ticks* (optional, with a delay) and *Typing starts after*.
  Both 1–60 seconds. With blue ticks at 5s and typing at 3s, a message is read
  at 5s, shows "typing…" from 8s, and is answered when the model finishes.

Changes save the moment you click, and the worker picks them up within about
five seconds.

**What is never auto-replied to:** your own messages (which would loop), status
updates, and anything that is not text — media, reactions, polls.

### Create an API key (optional)

**API** page → name it, choose the type (*Send a message* is the only one today),
press **Create API key**. The key is shown **once**. Copy it immediately; only a
SHA-256 hash is stored, so nobody — including this portal — can show it to you
later. Lose it and you create a new one.

**Show more details** on the same page gives you the endpoint, the request and
response shapes, and copy-paste Python, JavaScript and curl examples with your
own server's URL already filled in.

---

## Configuration reference

All configuration lives in `.env` at the repository root.

| Variable | Default | What it does |
|---|---|---|
| `POSTGRES_DB` | `whatsapp` | Database name. |
| `POSTGRES_USER` | `whatsapp` | Database user. |
| `POSTGRES_PASSWORD` | — | **Set this.** Database password. |
| `DJANGO_SECRET_KEY` | — | **Set this.** Signs sessions and tokens. |
| `DJANGO_DEBUG` | `false` | Never set `true` on anything reachable from outside. |
| `DJANGO_ALLOWED_HOSTS` | `*` | Comma-separated hostnames. Tighten this in production. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Only needed for the Django admin over a domain. |
| `PORTAL_PORT` | `8080` | Host port for the portal. Use `80` for a port-less URL. |
| `DEVICE_OS` | `Windows` | OS name shown under WhatsApp → Linked devices. |
| `DEVICE_PLATFORM` | `CHROME` | Browser type shown there. `CHROME`, `FIREFOX`, `SAFARI`, `EDGE`. |

`DEVICE_OS` and `DEVICE_PLATFORM` are only sent when the QR code is scanned.
Changing them does not rename a device that is already linked — unlink and
re-scan for that.

Settings that live in the database instead (managed from the portal, not `.env`):
the Gemini API key, model and instructions; the automation switches and delays;
and your API keys.

---

## The portal

Three pages, each with its own URL, so a refresh or a bookmark keeps you where
you were.

| Page | URL | Contains |
|---|---|---|
| **Settings** | `/settings` | Account connection (QR / status), Gemini AI configuration, send a test message |
| **Automation** | `/automation` | Auto-reply switch, chat-type exclusions, timing |
| **API** | `/api-keys` | Create, list and delete API keys; full usage documentation |

The account menu is in the top-right corner: your initial, your username, and
**Log out**.

> The API page lives at `/api-keys`, not `/api`, because nginx proxies everything
> under `/api/` to Django.

---

## Public REST API

One endpoint today: send a WhatsApp message to a number.

### Request

```
POST /api/v1/messages/
X-API-Key: <your key>
Content-Type: application/json

{"phone": "971568854459", "message": "Hello from the API"}
```

`Authorization: Bearer <key>` works as an alternative to `X-API-Key`.

| Field | Type | Notes |
|---|---|---|
| `phone` | string, required | Country code + number, digits only. A leading `+` and spaces are stripped for you. Must be 8–15 digits. |
| `message` | string, required | The text to send. |

### Responses

| Code | Meaning |
|---|---|
| `200` | Sent. `{"ok": true, "phone": "971568854459"}` |
| `400` | Missing or malformed `phone` / `message`. |
| `401` | Missing, unknown or deleted API key. |
| `502` | The message could not be delivered; the reason is in the body. |
| `503` | WhatsApp is not connected — scan the QR under Settings. |

Errors are always `{"ok": false, "error": "..."}`.

### Examples

**curl**

```bash
curl -X POST "http://localhost:8080/api/v1/messages/" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"phone": "971568854459", "message": "Hello from the API"}'
```

**Python**

```python
import requests

response = requests.post(
    "http://localhost:8080/api/v1/messages/",
    headers={"X-API-Key": "YOUR_API_KEY"},
    json={"phone": "971568854459", "message": "Hello from the API"},
    timeout=30,
)
print(response.status_code, response.json())
```

**JavaScript**

```javascript
const response = await fetch("http://localhost:8080/api/v1/messages/", {
  method: "POST",
  headers: {
    "X-API-Key": "YOUR_API_KEY",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    phone: "971568854459",
    message: "Hello from the API",
  }),
});
console.log(response.status, await response.json());
```

### Portal endpoints

These back the web UI and require the session token from `/api/auth/login/`
(header `Authorization: Token <token>`), not an API key.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/auth/login/` | Exchange username + password for a token |
| `GET` | `/api/auth/me/` | Current user; also validates the token |
| `GET` | `/api/whatsapp/status/` | Connection state and the current QR |
| `POST` | `/api/whatsapp/send/` | Send a test message |
| `GET`/`PUT` | `/api/gemini/settings/` | AI key, model, instructions |
| `POST` | `/api/gemini/test/` | Probe Gemini with the current form values |
| `GET`/`PUT` | `/api/automation/settings/` | Auto-reply switches and delays |
| `GET`/`POST` | `/api/keys/` | List / create API keys |
| `DELETE` | `/api/keys/<id>/` | Delete an API key |

---

## Where your data lives

Everything is in the `pgdata` Docker volume — one PostgreSQL database.

| Table | Contents |
|---|---|
| `whatsmeow_*` | The WhatsApp session: device identity, encryption keys, contacts. This is what saves you re-scanning the QR. |
| `auth_user`, `authtoken_token` | Portal logins and session tokens. |
| `whatsapp_geminisettings` | Gemini API key, model, instructions. One row. |
| `whatsapp_automationsettings` | Auto-reply switches and delays. One row. |
| `whatsapp_apikey` | API keys — **SHA-256 hashes only**, plus a display prefix and last-used timestamp. |
| `whatsapp_chatmemory` | Per-chat conversation history: up to 40 lines per chat, each capped at 600 characters. |

Conversation memory limits, all deliberate and set in `worker/memory.py`:
10 turns replayed per request, 600 characters per stored line, a 24-hour recall
window, and 40 lines kept per chat. Requests to Gemini are sent with
`store: false`, so Google is not asked to retain the conversation — the history
stays in your database.

---

## Security

### What is protected

- **Only one port is published.** The database, the Django backend and the
  WhatsApp worker have no host port at all; they are reachable only from inside
  the Docker network. nginx is the single entrance.
- **The portal requires a login.** Every portal endpoint rejects unauthenticated
  requests with `401`. Passwords are hashed by Django (PBKDF2) and validated
  against Django's standard strength rules.
- **API keys are stored as SHA-256 hashes.** The key is displayed once at
  creation and never again. A database dump does not reveal working keys.
- **The Gemini key never reaches the browser.** The settings endpoint returns
  only whether a key exists plus its last four characters.
- **The public API validates input** — digits-only phone numbers of a sane
  length — and returns distinct status codes rather than leaking internals.
- **The AI is constrained by your instructions**, which are sent as a system
  instruction on every request, and conversation memory is strictly per-chat, so
  one contact's messages can never surface in another's conversation.

### What is *not* protected — read before exposing this

1. **Plain HTTP.** As shipped, the portal is served over unencrypted HTTP. On
   localhost that is fine. On a public server it means your portal password, your
   session token and your API keys travel in the clear. **Put it behind HTTPS**
   (Caddy, Traefik or nginx with a certificate) before exposing it.
2. **The Gemini API key is stored in plain text** in the database. Anyone with
   database access, a backup, or shell access to the server can read it.
3. **`DJANGO_ALLOWED_HOSTS=*` by default.** Set it to your actual hostname in
   production.
4. **No rate limiting.** Neither the login endpoint nor the public API limits
   attempts. If you expose this, put a rate limiter in front of it.
5. **API keys do not expire** and have no per-key scope beyond the single type.
   Any valid key can message any number. Delete keys you are not using.
6. **A single portal user is a single point of failure.** Whoever logs in
   controls the WhatsApp account, can read the AI instructions, and can issue
   API keys.
7. **`.env` holds your database password and Django secret key.** It is
   gitignored — keep it that way, and do not paste it into issues or chats.

### Hardening checklist before you put this on the internet

- [ ] Terminate TLS in front of the portal; redirect HTTP to HTTPS.
- [ ] Set `DJANGO_ALLOWED_HOSTS` to your domain and `DJANGO_DEBUG=false`.
- [ ] Use a long, unique `POSTGRES_PASSWORD` and `DJANGO_SECRET_KEY`.
- [ ] Firewall the portal port to trusted IPs, or put it behind a VPN.
- [ ] Give the portal a strong password; do not reuse one.
- [ ] Add rate limiting on `/api/auth/login/` and `/api/v1/messages/`.
- [ ] Back up the `pgdata` volume, and treat the backup as a secret — it
      contains your WhatsApp session and your Gemini key.
- [ ] Rotate API keys periodically and delete unused ones.
- [ ] Keep the images updated: `docker compose pull && docker compose up -d --build`.

---

## Operations

```bash
# Watch the WhatsApp client: QR codes, connections, replies, errors
docker compose logs -f worker

# Django logs
docker compose logs -f backend

# Service status
docker compose ps

# Restart one service
docker compose restart worker

# Update after changing code
docker compose up -d --build

# Stop (keeps all data)
docker compose down
```

**Back up the database**

```bash
docker compose exec -T db pg_dump -U whatsapp whatsapp > backup.sql
```

**Restore**

```bash
cat backup.sql | docker compose exec -T db psql -U whatsapp whatsapp
```

**Start completely fresh** — deletes the WhatsApp session, all settings and all
API keys:

```bash
docker compose down -v
docker compose up -d --build
```

---

## Troubleshooting

**No QR code appears**
Check `docker compose logs -f worker`. The line you want is
`New QR code emitted (waiting for scan)`. If the worker is restarting in a loop,
the database is probably not reachable — check `docker compose ps` for `db`.

**The portal says "Device unlinked" and shows a new QR**
Someone removed this device from the phone (WhatsApp → Linked devices). That is
the designed behaviour: the worker restarts itself and produces a fresh QR within
about five seconds. Scan it again.

**"Connection lost — reconnecting…"**
A temporary network drop. The session is kept and whatsmeow reconnects on its
own. No action needed.

**The AI shows "typing…" and then nothing arrives**
Something failed after the indicator went up. The reason is always in the worker
log:

```bash
docker compose logs worker | grep "Auto-reply skipped"
```

The two common causes are:
- *"You exceeded your current quota"* — your Gemini free-tier allowance is used
  up. Switch to a lighter model such as `gemini-3.5-flash-lite` under Settings →
  Gemini AI, or enable billing on your Google Cloud project.
- *"Gemini did not respond within 60s"* — the model took too long. Use a faster
  model, or shorten a very long instruction.

Failures are deliberately silent in the chat: the portal will not paste an API
error into a conversation with your customer.

**API returns 503**
WhatsApp is not connected. Open Settings and scan the QR.

**A small "AI" label appears on messages sent by the portal**
WhatsApp adds that on its side for accounts it classifies as automated. Nothing
in this project sets it, and no client-side setting removes it.

**Apple Silicon build problems**
The worker is pinned to `linux/amd64` for neonize. If your platform has a native
wheel, remove the `platform:` line from the `worker` service in
`docker-compose.yml`.

---

## Development

```
.
├── backend/            Django + DRF
│   ├── config/         settings, urls, wsgi
│   └── whatsapp/       models, views, gemini client, worker client
├── worker/             the long-lived WhatsApp client
│   ├── main.py         connection, events, auto-reply orchestration
│   ├── gemini.py       Gemini Interactions API client
│   ├── memory.py       per-chat conversation memory
│   └── config_store.py reads portal settings from PostgreSQL
├── frontend/           React (Vite), served by nginx
│   └── src/
│       ├── pages/      Settings, Automation, API
│       └── components/ Connect, GeminiSettings, SendTest, UserMenu, Icons
└── docker-compose.yml
```

Rebuild a single service after editing it:

```bash
docker compose up -d --build worker
```

Database migrations run automatically when the backend container starts. After
changing a model:

```bash
docker compose exec backend python manage.py makemigrations
docker compose up -d --build backend
```

The frontend is a production build inside the image — there is no hot reload.
Rebuild the `frontend` service to see changes.

---

## Not implemented yet

- **Multiple WhatsApp accounts.** The portal handles exactly one number today.
- Media messages (images, documents) — text only, in both directions.
- Webhooks for incoming messages.
- A message log or conversation viewer in the portal.
- Per-key scopes, quotas or expiry for API keys.
- Surfacing auto-reply failures in the UI (they are in the worker log only).

---

## ⚠️ Disclaimer — read this before you use it

**This project connects to WhatsApp in a way that WhatsApp does not permit.**

It uses the unofficial multi-device protocol through
[neonize](https://github.com/krypton-byte/neonize) / whatsmeow — the same channel
WhatsApp Web uses, but driven by a program instead of a person. It is not the
WhatsApp Business API, it is not authorised by Meta, and it is not affiliated
with WhatsApp or Meta in any way.

**Using it violates the WhatsApp Terms of Service.** WhatsApp's terms prohibit
accessing the service with unauthorised or automated means, and their policies
prohibit automated or bulk messaging. Meta actively detects this kind of client.

**What can realistically happen to you:**

- **Your number can be banned**, temporarily or permanently, with no warning, no
  explanation, and often no route of appeal. A ban can take the account's chat
  history and any linked business assets with it.
- Detection does not depend on volume alone. Behaviour, patterns and the client
  fingerprint all contribute, and WhatsApp may label messages sent this way as
  automated on the recipient's screen.
- The protocol is unofficial and can change without notice. An update on Meta's
  side can break this project at any time.

**Reduce the risk, but understand you cannot remove it:**

- Use a number you can afford to lose. Never your personal number, and never a
  number carrying a business you depend on.
- Keep volumes low and behaviour human. Use the timing delays.
- Only message people who have contacted you first and expect a reply.
- Never use this for marketing, bulk sending, cold outreach, or messaging people
  who did not ask to hear from you.
- Respect your local laws on automated messaging, consent and data protection
  (GDPR and equivalents apply to conversations you store).
- Tell people they are talking to an automated assistant.

**Third-party services.** Message content is sent to Google's Gemini API when
auto-reply is enabled. Whatever your contacts write may be transmitted to Google
and is subject to their terms and privacy policy. Say so in your privacy notice.

**No warranty.** This software is provided as-is, without warranty of any kind.
The authors and contributors accept no liability for banned accounts, lost
messages, lost data, lost business, regulatory penalties, or any other damage
arising from its use.

**Use this at your own risk.** By running it you accept full responsibility for
how it is used and for whatever consequences follow, including the permanent
loss of the WhatsApp account you connect to it.
