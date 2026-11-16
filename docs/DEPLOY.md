# Deploying Concilia

One small Linux server runs everything with Docker Compose: PostgreSQL, the API, the worker, a daily backup, and Caddy, which gets the HTTPS certificate on its own. Images are built by GitHub Actions and published to GitHub Container Registry; after CI passes on `main`, the `Deploy` workflow rolls the server forward over SSH ([ADR-0010](adr/0010-deployment.md)).

## What you need

- A server with 2 vCPU, 4 GB of RAM and 40 GB of disk, running Ubuntu 24.04 LTS, with a public IPv4 address. At the time of writing, entry-level plans at the usual providers cost about US$5–7 a month, within the project's US$10 target.
- A domain or subdomain pointing to it: an `A` record (and `AAAA` if the server has IPv6).
- Ports 22, 80 and 443 open; nothing else.

## One-time server setup

```sh
# As root on the new server
apt-get update && apt-get install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sh
adduser --disabled-password --gecos "" deploy && usermod -aG docker deploy
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
install -d -o deploy -g deploy /opt/concilia
```

As `deploy`:

```sh
git clone https://github.com/<owner>/concilia.git /opt/concilia
cd /opt/concilia
cp infra/deploy/env.example .env
chmod 600 .env
```

Fill in `.env`:
- generate every password and secret with `openssl rand -hex 32`;
- set `SITE_ADDRESS` to the domain and `ACME_EMAIL` to the address that receives certificate notices;
- set `CONCILIA_IMAGES` to `ghcr.io/<owner>` in lowercase.

**The first deploy.** It needs one published version: merge anything to `main`, or run the `Deploy` workflow by hand. Then:

```sh
cd /opt/concilia
export CONCILIA_VERSION=<commit sha published by the workflow>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --detach --no-build
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm migrator python -m concilia.cli create-org \
  --name "Mi empresa" --email admin@example.com --display-name "Nombre Apellido"
```

The packages that the workflow publishes in GitHub Container Registry start as private. To let the server pull them without credentials, make each one public: Packages → `concilia-backend` / `concilia-web` → Package settings → Change visibility. Otherwise, run `docker login ghcr.io` on the server with a token that has only the `read:packages` scope.

## Automatic deployment

In the repository settings, create the environment `production`, then add:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `DEPLOY_HOST` | The server's address |
| Secret | `DEPLOY_USER` | `deploy` |
| Secret | `DEPLOY_SSH_KEY` | A private key made only for this, whose public half is in `/home/deploy/.ssh/authorized_keys` |
| Secret | `DEPLOY_KNOWN_HOSTS` | The output of `ssh-keyscan <server>`, checked against the server's fingerprint |
| Variable | `SITE_URL` | `https://<domain>` |

From then on, every push to `main` that passes CI publishes both images tagged with the commit and runs on the server:
- `git checkout` of that commit, for the compose files and the Caddyfile;
- `docker compose pull`;
- `docker compose up`, which runs migrations first, because the API and the worker wait for the migrator.

The workflow then checks that `/api/health` answers. Without `DEPLOY_HOST`, the workflow only publishes the images.

## Monitoring

`GET /api/health` answers `200 {"status": "ok"}` when the API is up and the database answers, and `503` otherwise. Point a free external monitor at `https://<domain>/api/health`, for example UptimeRobot or Better Stack every 5 minutes, with alerts to your email.

## Backups

The `backup` service runs `pg_dump` once a day as `concilia_backup`, a read-only role. It writes `concilia-<UTC time>.dump` files to the `backups` volume and keeps them `BACKUP_KEEP_DAYS` days (14 by default). Those copies live on the same server: copy them elsewhere from time to time, for example `docker compose cp backup:/backups ./backups`, then `scp` or object storage.

To restore into an empty database, after stopping the API and the worker:

```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml stop api worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  pg_restore --username postgres --dbname concilia --clean --if-exists --no-owner \
  --role concilia_owner < concilia-<time>.dump
docker compose -f docker-compose.yml -f docker-compose.prod.yml start api worker
```

## The AI assistant

It stays off in production (`CONCILIA_AI_ENABLED=false`) until you decide to turn it on. Demo organizations always replay the recordings in the repository and never call the provider. To enable it for real organizations:
1. Create the OpenAI project, budget and key that [ADR-0006](adr/0006-ai-provider-and-llm-port.md) describes.
2. Add `OPENAI_API_KEY` to `.env` and set `CONCILIA_AI_ENABLED=true`.
3. Run `docker compose ... up --detach`.

## Public demo limits

Production sets demos to expire after 4 hours, and allows 5 demos per IP per day and 300 per day overall. Open registration stays off: real organizations are created with `create-org` as above.
