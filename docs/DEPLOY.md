# Deploying Concilia

One small Linux server runs everything with Docker Compose: PostgreSQL, the API, the worker, a daily backup, and Caddy, which gets the HTTPS certificate on its own. Images are built by GitHub Actions and published to GitHub Container Registry; after CI passes on `main`, the `Deploy` workflow rolls the server forward over SSH ([ADR-0010](adr/0010-deployment.md)).

## What you need

- A server running Ubuntu 24.04 LTS with a public IPv4 address. The stack uses about 310 MB of RAM at rest. The minimum is 1 GB of RAM with 2 GB of swap and 30 GB of disk; the public instance runs on Google Cloud's always-free `e2-micro` ([below](#on-google-clouds-free-tier)). 2 vCPU and 4 GB, about US$5–7 a month at entry-level providers, make demo creation and logins faster.
- A domain or subdomain pointing to it: an `A` record (and `AAAA` if the server has IPv6). A free DuckDNS subdomain works. `duckdns.org` is on the Public Suffix List, so Let's Encrypt counts its rate limits for your subdomain alone.
- Ports 22, 80 and 443 open; nothing else.

## One-time server setup

```sh
# As root on the new server
apt-get update && apt-get install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sh
adduser --disabled-password --gecos "" deploy && usermod -aG docker deploy
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
install -d -o deploy -g deploy /opt/concilia
# Only with less than 4 GB of RAM
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
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
- keep `TLS_MODE=public` (Let's Encrypt, with ZeroSSL as fallback), except on Google Cloud ([below](#on-google-clouds-free-tier));
- set `CONCILIA_IMAGES` to `ghcr.io/<owner>` in lowercase.

**The first deploy.** It needs one published version. The `Deploy` workflow publishes one after every push to `main` that passes CI, and its run shows the commit. Then:

```sh
cd /opt/concilia
export CONCILIA_VERSION=<commit sha published by the workflow>
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --detach --no-build
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm migrator python -m concilia.cli create-org \
  --name "Mi empresa" --email admin@example.com --display-name "Nombre Apellido"
```

The packages that the workflow publishes in GitHub Container Registry start as private. To let the server pull them without credentials, make each one public: Packages → `concilia-backend` / `concilia-web` → Package settings → Change visibility. Otherwise, run `docker login ghcr.io` on the server with a token that has only the `read:packages` scope.

## On Google Cloud's free tier

One `e2-micro` per billing account is free in `us-west1`, `us-central1` and `us-east1`, with 30 GB of standard disk; check the current terms in the [free tier page](https://cloud.google.com/free/docs/free-cloud-features#compute). With the [gcloud CLI](https://cloud.google.com/sdk/docs/install) signed in, and a billing account linked to a new project:

```sh
P=<project-id>
gcloud services enable compute.googleapis.com --project=$P
gcloud compute addresses create concilia-ip --region=us-east1 --project=$P
gcloud compute firewall-rules create allow-web --project=$P --network=default \
  --allow=tcp:80,tcp:443 --source-ranges=0.0.0.0/0 --target-tags=web
gcloud compute instances create concilia --project=$P --zone=us-east1-b \
  --machine-type=e2-micro --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard \
  --address=$(gcloud compute addresses describe concilia-ip --region=us-east1 --project=$P --format='value(address)') \
  --tags=web --metadata=enable-guest-attributes=TRUE,ssh-keys="admin:$(cat ~/.ssh/<admin-key>.pub)"
```

- **Disk:** use `pd-standard`; a balanced or SSD disk is not free.
- **Host keys:** `gcloud compute instances get-guest-attributes concilia --zone=us-east1-b --query-path=hostkeys/` prints the server's SSH host keys over Google's API. Compare them with `ssh-keyscan` before trusting the address, and use them for `DEPLOY_KNOWN_HOSTS`.
- **Budget:** add a small alert with `gcloud billing budgets create`, so any charge outside the free tier is noticed within days.
- **Certificate:** use Google Trust Services, Google's free ACME authority. On 2026-11-16, Let's Encrypt's validation servers (`23.178.112.0/24`) reached a VM in `us-east1`, but the VM's replies never got back to them. Caddy's fallback, ZeroSSL, validated the challenge and then never issued the certificate. To set it up:
  ```sh
  gcloud services enable publicca.googleapis.com --project=$P
  gcloud publicca external-account-keys create --project=$P 2>/dev/null --format='value(keyId,b64MacKey)'
  ```
  Then set `TLS_MODE=gts`, `ACME_EAB_KEY_ID` and `ACME_EAB_MAC_KEY` in `.env`. The key is single-use and expires after 7 days; once Caddy has registered with it, renewals need no new key. gcloud also prints the key on stderr, hence `2>/dev/null`.

Then follow the one-time setup above, with the swap.

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
- `docker compose up`, which runs migrations first, because the API and the worker wait for the migrator;
- `docker image prune --all`, which deletes the images that no container uses anymore, so earlier versions do not fill the disk.

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
