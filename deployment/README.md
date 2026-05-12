# Deployment

Blue-green deploys to a DigitalOcean droplet, driven by [`.github/workflows/cd.yml`](../.github/workflows/cd.yml).

- `droplet-files/` — synced to `/opt/bedlam-connect/deployment/` on the droplet.
- `scripts/` — helper scripts run by CI (e.g. `deploy-copy-files.sh`).

`ls deployment/droplet-files/` and `ls deployment/scripts/` are the source of truth for what's there.

## Pipeline

`.github/workflows/cd.yml` has two jobs:

1. `build-and-push` — builds the image from [`docker/Dockerfile`](docker/Dockerfile) and pushes to GHCR.
2. `deploy` — runs `scripts/deploy-copy-files.sh` to SCP `droplet-files/*` to `/opt/bedlam-connect/deployment/`, then SSHes in and runs `./deploy.sh`.

`deploy.sh` implements the blue-green switch: detect current color, start the alternate (blue on `:8001`, green on `:8002`), health-check it, point nginx at it, drop the old. Read [`cd.yml`](../.github/workflows/cd.yml) and `droplet-files/deploy.sh` for the exact steps.

## Bootstrapping an admin

Admin actions require `is_superuser=True`; no admin exists out of the box. Promote a registered user via the wrapper deployed alongside `deploy.sh`:

```bash
ssh user@your-droplet-ip
cd /opt/bedlam-connect/deployment
./promote-admin.sh you@example.com           # grant
./promote-admin.sh you@example.com --revoke  # revoke
```

The wrapper auto-detects the running blue/green container, is idempotent, and refuses on a missing user. Locally, the equivalent is `dev promote-admin <email>`.

## Manual deploy (emergency)

If CI fails:

```bash
ssh user@your-droplet-ip
cd /opt/bedlam-connect/deployment
# Re-copy files only if needed:
# scp deployment/droplet-files/* user@droplet-ip:/opt/bedlam-connect/deployment/
chmod +x deploy.sh cleanup-docker.sh
./deploy.sh
```

`./deploy.sh` is idempotent — re-running it after a failure rolls back to the working color.
