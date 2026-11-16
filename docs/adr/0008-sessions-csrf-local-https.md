# ADR-0008: Cookie sessions, signed double-submit CSRF and local HTTPS

- Status: Accepted
- Date: 2026-11-15
- Story: CN-01

## Context

The Angular app and the API are served from the same origin by Caddy. Sessions must be revocable (members are removed, demo roles are switched, users log out), and the login flow must resist credential stuffing. Development should behave like production, including `__Host-` cookies, which browsers accept only over HTTPS.

## Decision

**Opaque server-side sessions, no JWT.**

- On login the API generates a token with `secrets.token_urlsafe(32)`, stores only its SHA-256 in `sessions.token_hash`, and sets it in `__Host-concilia_session` (`HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, no `Domain`).
- A session expires after 12 hours without use or 7 days after creation. `last_seen_at` is written at most once every 5 minutes per session, so reads do not turn into writes.
- A new session (new id and token, old one revoked) is issued on login, on choosing or switching organization, and on the demo role switch. Logout revokes the session and clears both cookies. Removing a member revokes their sessions in that organization.
- Passwords are hashed with argon2-cffi's `PasswordHasher` defaults (Argon2id, RFC 9106 low-memory profile) and rehashed on login when the parameters change. Unknown emails are verified against a dummy hash so response time does not reveal which emails exist. Demo users have no password and can never log in with one.

**Signed double-submit CSRF.**

- Whenever a session is issued, the API also sets `__Host-XSRF-TOKEN` (`Secure`, `SameSite=Lax`, `Path=/`, readable by scripts) to `base64url(HMAC-SHA256(CSRF_SECRET, session id))`. `GET /api/app/session`, which the app calls on startup, reissues it if missing.
- Angular sends it back in `X-XSRF-TOKEN` through `withXsrfConfiguration({ cookieName: '__Host-XSRF-TOKEN', headerName: 'X-XSRF-TOKEN' })`.
- Every unsafe method under `/api/app/*` recomputes the HMAC for the current session and compares it with `hmac.compare_digest`. A mismatch returns 403.
- The HMAC is computed over the session's database id, not its token, so the readable cookie reveals nothing that could authenticate a request, and an attacker without `CSRF_SECRET` cannot forge it.
- `/api/public/*` (login, accept invitation, registration, create demo) has no session to sign. It requires the `Origin` header to equal `PUBLIC_ORIGIN`, and rejects unsafe requests without `Origin`.

**Login and demo-creation limits.** `rate_limits` stores fixed-window counters keyed by an HMAC of the IP or of the normalized email, never the raw values. Exceeding a limit returns 429 with `Retry-After`. Window sizes and thresholds are settings fixed in CN-05 (login) and CN-22 (demos).

**Real client IP.** Uvicorn runs with `--proxy-headers` and `--forwarded-allow-ips` limited to Caddy's network. Caddy overwrites `X-Forwarded-For` with the connecting address instead of appending to it, so clients cannot inject an IP (CN-04).

**Local HTTPS that matches production.**

- Caddy serves `https://localhost` with `tls internal`. Its root CA lives in the `caddy_data` volume.
- `make trust-ca` copies the root certificate out of the container and installs it in the operating system's trust store: `certutil -user -addstore Root` on Windows, `security add-trusted-cert` on macOS, `update-ca-certificates` on Debian-based Linux. It is a one-time step, documented in the README (CN-03). Without it everything runs, but the browser shows a certificate warning.
- Backend tests use httpx with `ASGITransport` and `base_url="https://test"`, so `Secure` and `__Host-` cookies behave as in production without TLS.
- Playwright in CI trusts the CA the same way, or runs with `ignoreHTTPSErrors` (CN-06).

## Consequences

- Sessions can be revoked instantly, and a stolen database row cannot be replayed as a cookie because only hashes are stored.
- One lookup per request (indexed by `token_hash`) is the price of revocability.
- `CSRF_SECRET` and the rate-limit HMAC key are new required settings; rotating `CSRF_SECRET` only forces a reissue of the readable cookie.
- Development needs one manual trust step per machine, in exchange for running exactly the production cookie and CSP setup.

## Alternatives considered

- **JWT in cookies or headers.** Rejected: revocation needs a server-side list anyway, and tokens leak more than an opaque id.
- **Synchronizer tokens stored per session.** Rejected: the signed double-submit gives the same protection without storing tokens.
- **Relying on `SameSite` alone.** Rejected: it is defense in depth, not a complete CSRF defense.
- **mkcert on the host.** Rejected: an extra host tool, while Caddy already provides an internal CA.
