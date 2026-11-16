# ADR-0010: Deployment on one server with Compose and images from CI

- Status: Accepted
- Date: 2026-11-16
- Story: CN-04

## Context

SPEC asks for a public deployment under US$10 a month plus the AI, with HTTPS, automatic deployment on merges to `main`, a 6 MB request limit, the client's real IP, a daily `pg_dump` with `concilia_backup`, and `/api/health` watched by an external monitor. The local stack already runs every piece with Docker Compose and Caddy (CN-03). The traffic is a portfolio demo: a handful of visitors at a time.

## Decision

**One Linux server runs the same Compose stack as local development**, with `docker-compose.prod.yml` on top. The override:
- requires every password and secret (`${VAR:?}`), so a forgotten secret stops the deployment instead of falling back to a development default;
- sets the demo's 4-hour lifetime and its limits, and keeps registration closed;
- turns on HSTS and lets Caddy obtain the certificate from Let's Encrypt for `SITE_ADDRESS`;
- adds the `backup` service.

**Images are built once, by CI, and the server only pulls them.** After `CI` succeeds on a push to `main`, the `Deploy` workflow:
1. builds the backend and web images;
2. pushes them to GitHub Container Registry, tagged with the commit;
3. connects to the server over SSH, checks out that commit (for the compose files and the Caddyfile), pulls the images and runs `docker compose up`, which runs migrations first because the API and the worker wait for the migrator;
4. checks the public `/api/health`.

Without the `DEPLOY_*` secrets, it only publishes the images.

**The client's IP.** Caddy has a fixed address on the Compose network (`10.89.47.0/24`, outside Docker's automatic pools) and overwrites `X-Forwarded-For` with the remote address. Uvicorn trusts forwarded addresses only from that address (`--proxy-headers`, `FORWARDED_ALLOW_IPS`). A test runs Uvicorn's middleware with that configuration, and another keeps compose and the Caddyfile consistent.

**Backups.** A `postgres` container runs `pg_dump --format=custom` once a day as `concilia_backup`, a read-only role with `BYPASSRLS`. It keeps 14 days in a volume. Copying them off the server is an operator task described in [DEPLOY.md](../DEPLOY.md).

**Monitoring.** `/api/health` now also queries the database and answers 503 when it cannot. A free external monitor polls it.

The hosting provider and the domain are the owner's choice, since they are a monthly cost. Any provider with a 2 vCPU / 4 GB Ubuntu server fits.

## Consequences

- Production runs the same files as local development and CI, apart from one override, so a working `docker compose up` locally is strong evidence for the deployment.
- The server never builds anything: deployments are a pull and a restart, and a small server never runs out of memory compiling Angular.
- One server is one point of failure. A short outage during deployments and server maintenance is acceptable for a portfolio demo.
- Backups on the same disk do not survive losing the server until they are copied elsewhere.

## Alternatives considered

- **A platform as a service (Render, Fly.io, Railway).** Rejected: a managed PostgreSQL alone exceeds the budget, and two processes plus a database need several paid services.
- **Building on the server with `docker compose up --build`.** Rejected: the Angular build needs more memory than a small server comfortably has, and every deployment would depend on the server's toolchain.
- **Kubernetes or Swarm.** Rejected: far beyond what one portfolio instance needs.
