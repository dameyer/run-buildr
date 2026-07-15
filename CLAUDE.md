# Run Builder — CLAUDE.md

FastAPI web app that builds structured running workouts and pushes them to Wahoo KICKR Run (treadmill) and Garmin Connect (outdoor). Deployed behind a Cloudflare tunnel.

## Stack

- FastAPI + SQLAlchemy (mapped columns) + SQLite + Pydantic v2 + Jinja2 + Chart.js v4
- Python managed with `uv` (`pyproject.toml`)
- Developed on macOS, deployed on Windows (same codebase, two machines)
- Start: `uv run uvicorn app.main:app --reload --port 9000`

## Key files

```
app/
  main.py          — app init, middleware, migrations, top-level routes (/, /analysis)
  config.py        — Settings (pydantic-settings); reads .env
  models.py        — SQLAlchemy ORM: User, WahooToken, GarminToken, SavedWorkout
  schemas.py       — Pydantic models: Plan, Interval, TriggerType, IntensityType
  auth.py          — bcrypt helpers, password hashing
  dependencies.py  — get_db
  routers/
    login.py       — /login, /logout; current_user_id / require_auth / require_admin helpers
    users.py       — /register, /admin, /calendar (page), /change-password
    workouts.py    — /workouts/* API (save, push-wahoo, push-garmin, load, archive, calendar-data)
    auth.py        — /auth/wahoo/* OAuth flow
    garmin_auth.py — /auth/garmin/* (login modal, MFA nonce store)
    analysis.py    — /api/analysis/* (list wahoo/garmin activities, download FIT)
  services/
    plan.py        — Plan → Wahoo base64 JSON; Plan → Garmin workout JSON
    wahoo.py       — Wahoo API calls (push plan+workout, list summaries, download FIT)
    garmin.py      — garminconnect wrapper (push workout, schedule, list activities, download FIT)
  static/js/
    editor.js      — workout editor UI
    analysis.js    — analysis tab UI
  templates/       — Jinja2 HTML (base.html, editor.html, analysis.html, calendar.html, admin.html, …)
```

## Env vars (`.env`)

| Var | Notes |
|-----|-------|
| `SESSION_SECRET` | Required; validated at startup (min 32 chars, placeholder rejected). Generate: `uv run python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `INVITE_CODE` | Required; validated non-placeholder |
| `WAHOO_CLIENT_ID` / `WAHOO_CLIENT_SECRET` | Wahoo OAuth app creds |
| `REDIRECT_URI` | Wahoo OAuth callback URL |
| `HTTPS_ONLY` | `true` in prod (Cloudflare), `false` for local dev |
| `DATABASE_URL` | Defaults to `sqlite:///./kickr.db` |
| `FERNET_KEY` | Required; validated at startup. Encrypts Wahoo/Garmin tokens at rest. Generate: `uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |

## DB schema

Additive SQLite migrations run at startup in `main.py` (ALTER TABLE IF column missing).

- `users`: id, username, hashed_password, is_admin, session_version, created_at
- `wahoo_tokens`: id, user_id, access_token, refresh_token, expires_at, token_type, created_at
- `garmin_tokens`: id, user_id, tokens_json (full session JSON), created_at, updated_at
- `saved_workouts`: id, user_id, name, plan_json, wahoo_plan_id, wahoo_workout_id, garmin_workout_id, scheduled_at, pushed_at, is_archived, created_at

Tokens are **always encrypted at rest** via `app/services/crypto.py` (Fernet; `FERNET_KEY` required). A row that can't be decrypted with the current key (legacy plaintext or rotated key) is treated as "not connected" so the account reconnects — no plaintext fallback.

## Non-obvious gotchas

### Cloudflare + error responses
Use **422** (not 502) for any endpoint that wraps an external API and might fail. Cloudflare intercepts 502 and returns its own HTML error page, which breaks `resp.json()` in the browser. `WahooAPIError.http_status` handles this for Wahoo wrappers (collapses upstream 5xx → 422; 4xx passes through).

### JS cache busting
`main.py` sets `cache_buster = str(int(time.time()))` and injects it into Jinja2 globals. Templates reference it as `?v={{ cache_buster }}`. It resets on process restart — no manual version bumping needed.

### Auth — is_admin
`is_admin` is written to the session as a UI hint but `require_admin()` (in `login.py`) always queries the DB. Never rely on the session value for access control.

### Auth — session revocation
`users.session_version` is copied into the session cookie at login and checked against the DB on every authenticated request (`session_user()` in `login.py` — the single validation path; all auth helpers go through it). Bumping the version revokes every outstanding cookie for the account: logout bumps it (signing out = signing out everywhere — signed cookies can't be revoked per-device), and password change/admin reset bump it (password change refreshes the current session so that device stays signed in). Never read `session["user_id"]` directly for auth — go through `session_user()` / `current_user_id()`.

### Auth — Garmin MFA
Multi-step Garmin login uses an in-process nonce dict (5-min TTL) keyed by a random token stored in the session. Credentials never touch the session cookie (Starlette sessions are signed, not encrypted).

### Wahoo workout format
- Repeat `exit_trigger_value` is **0-indexed**: value=N means N additional repeats (total = N+1). `plan.py` subtracts 1 before encoding.
- Only `grade` is a valid control type (no terrain/lateral simulation via API).
- Push order: plan first → get `plan_id` → push workout referencing `plan_id`.
- Grade values in JSON are decimal (1% = 0.01).

### Garmin workout format
- Each step needs a `"type"` discriminator: `"ExecutableStepDTO"` or `"RepeatGroupDTO"` (Jackson polymorphism).
- Duration is `endCondition` + `endConditionValue`, not a `duration` object.
- Step type IDs: warmup=1, cooldown=2, interval=3, recovery=4, rest=5, repeat=6.
- Pace target: `targetType.workoutTargetTypeId=6`, values `targetValueOne`/`targetValueTwo` in m/s.
- `numberOfIterations` for repeat blocks (1-indexed, no adjustment).
- After push: call `schedule_workout(workout_id, date_str)` to sync to watch.
- Token persistence: `client.client.dumps()` to save, `client.client.loads(json)` to restore (skip `login()` to avoid network calls).

### Garmin FIT download
`ActivityDownloadFormat.ORIGINAL` returns a **ZIP**. `analysis.py` extracts the `.fit` from the zip; falls back to treating as raw FIT if `BadZipFile`.

### FIT analysis — active time axis
Pace/elevation charts use **distance** as x-axis. All other charts (cadence, HR, etc.) use active time: consecutive record gaps are capped at 3 s (`min(dt, 3.0)`) to compress pause time.

## Security notes

- **Token encryption:** `FERNET_KEY` required; all Wahoo/Garmin tokens encrypted at rest (`app/services/crypto.py`). Undecryptable rows → treated as disconnected (reconnect).
- **Session revocation:** `users.session_version` is checked on every authenticated request; logout and password change/reset bump it, killing all outstanding session cookies (see gotcha "Auth — session revocation").
- **Rate limiting:** `app/ratelimit.py` — in-memory fixed-window limiter on `/login` (10/5min), `/register` (5/10min), and the Garmin credential-relay endpoints `/auth/garmin/connect` + `/connect/mfa` (5/10min, keyed per user + IP). `CF-Connecting-IP` is only trusted when the direct peer is loopback/private (i.e. via the local cloudflared tunnel) — otherwise the socket IP is used, so a direct hit can't spoof fresh buckets. `X-Forwarded-For` is deliberately not read; behind a non-Cloudflare proxy all clients would share one bucket (see README → "Deploying without Cloudflare"). Process-local → single-worker only.
- **Edge (Cloudflare):** production layers dashboard-configured protections on top of the app — WAF managed ruleset, edge rate-limiting on `/login` & `/register`, Bot Fight Mode, and SSL/TLS Full (Strict). Exact rate-limit thresholds live in the Cloudflare dashboard, not the repo.
- **CSRF:** `SameSite=lax` blocks the session cookie on cross-site POSTs; all state-changing endpoints are POST (incl. `/logout`, which posts a form from the nav).
- **Stored XSS:** all user/external strings interpolated into `innerHTML` in `editor.js` / `analysis.js` go through `escapeHtml()`. Jinja autoescape covers templates.

## Pending / known issues

- Lap table shows raw FIT elapsed time (includes pauses) — charts use compressed active time but table doesn't.
- Terrain simulation (Lateral/L+V) not supported via Wahoo API (only `grade` control accepted).
