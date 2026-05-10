# 🚀 Deployment documentation

## 🎯 Overview

This directory contains all files and documentation related to deploying the Bedlam Connect application to the DigitalOcean droplet using automated blue-green deployment.

**Key Features:**

- ✅ **Automated File Sync**: GitHub Actions automatically copies deployment files via SCP
- ✅ **Zero-Downtime Deployment**: Blue-green deployment strategy
- ✅ **Clean Organization**: All deployment files in logical structure
- ✅ **Manual Fallback**: Emergency deployment procedures available

## 📁 File structure

```
deployment/
├── README.md          # This documentation
├── droplet-files/     # Files synced to /opt/bedlam-connect/deployment/ on the droplet
└── scripts/           # Helper scripts run by CI (e.g. deploy-copy-files.sh)
```

The actual contents of each subdirectory are the source of truth — `ls deployment/droplet-files/` and `ls deployment/scripts/` always tell you what's there.

## 🔄 How automated deployment works

### GitHub actions workflow

The deploy pipeline lives in [`.github/workflows/cd.yml`](../.github/workflows/cd.yml). It runs in two jobs:

1. **`build-and-push`** — builds the Docker image from [`deployment/docker/Dockerfile`](docker/Dockerfile) and pushes it to GitHub Container Registry.
2. **`deploy`** — copies deployment files to the droplet by running [`deployment/scripts/deploy-copy-files.sh`](scripts/deploy-copy-files.sh), then SSHes in and executes `deploy.sh` for zero-downtime deployment.

**Where files land:** `deploy-copy-files.sh` SCPs `deployment/droplet-files/*` to **`/opt/bedlam-connect/deployment/`** on the droplet (not `/opt/bedlam-connect/`). The deploy step then `cd`s into that directory before running `./deploy.sh`.

For the exact SCP and SSH steps, read [`cd.yml`](../.github/workflows/cd.yml) and [`scripts/deploy-copy-files.sh`](scripts/deploy-copy-files.sh) — they're the source of truth, not this README.

## 🏗️ Blue-Green deployment process

The `deploy.sh` script implements zero-downtime deployment:

1. **Detect Current State**: Determines if blue or green instance is running
2. **Start New Instance**: Launches the alternate color instance
3. **Health Check**: Verifies new instance is healthy
4. **Switch Traffic**: Updates nginx to point to new instance
5. **Cleanup**: Removes old instance after successful switch

**Ports:**

- Blue instance: `localhost:8001`
- Green instance: `localhost:8002`
- Nginx proxies `aimagain.art` to the active instance

## 🔑 Bootstrapping an admin

The app has no admin user out of the box, and admin actions (delete user, deactivate user) require `is_superuser=True`. Promote an existing registered user to admin via the wrapper script that ships with deployment files:

```bash
ssh user@your-droplet-ip
cd /opt/bedlam-connect/deployment
./promote-admin.sh you@example.com           # grant
./promote-admin.sh you@example.com --revoke  # revoke
```

The wrapper auto-detects the running blue/green container and execs the promotion script inside it — no `docker exec` incantation to remember. It's idempotent (safe to re-run) and refuses on a missing user (won't auto-create from a typo).

**First-run note:** if the wrapper isn't executable after SCP, run `chmod +x promote-admin.sh` once. The script is sourced from [`droplet-files/promote-admin.sh`](droplet-files/promote-admin.sh) and deployed automatically alongside `deploy.sh` and the compose file.

Locally, the equivalent is `dev promote-admin <email>` — see [`../scripts/README.md`](../scripts/README.md).

## 🚨 Manual deployment (emergency)

If GitHub Actions fails, you can deploy manually:

### 1. ssh to droplet

```bash
ssh user@your-droplet-ip
cd /opt/bedlam-connect/deployment
```

### 2. update files (if needed)

```bash
# From your local machine
scp deployment/droplet-files/* user@droplet-ip:/opt/bedlam-connect/deployment/
```

(or run `deployment/scripts/deploy-copy-files.sh` with the right env vars set — same as CI does.)

### 3. run deployment

```bash
chmod +x deploy.sh cleanup-docker.sh
./deploy.sh
```

### 4. check status

```bash
docker ps
curl -f http://localhost:8001/health  # or 8002
curl -f https://aimagain.art/health
```

## 🛠️ updating deployment scripts

### To modify deployment process:

1. **Edit Files**: Make changes to files in `deployment/droplet-files/`
2. **Test Locally**: Verify scripts work (if possible)
3. **Push to Main**: GitHub Actions will automatically deploy changes
4. **Monitor**: Watch GitHub Actions workflow for any issues

### Common updates:

**Add New Environment Variables:**

- Update `docker-compose.blue-green.yml`
- Ensure secrets are available on droplet

**Modify Health Check:**

- Update `check_health()` function in `deploy.sh`
- Test new endpoint or logic

**Change Deployment Strategy:**

- Modify `deploy.sh` script
- Update this documentation

## 🔍 Troubleshooting

### GitHub actions scp fails

```bash
# Check ssh key and connection
ssh -i ~/.ssh/your-key user@droplet-ip

# Verify target directory exists
ls -la /opt/bedlam-connect/
```

### Deployment script fails

```bash
# Check logs
docker logs bedlam-connect-blue  # or bedlam-connect-green
docker logs bedlam-connect-green

# Check nginx
sudo nginx -t
sudo systemctl status nginx

# Manual rollback
./deploy.sh  # Will detect and switch back
```

### Health check issues

```bash
# Test health endpoint directly
curl -v http://localhost:8001/health
curl -v http://localhost:8002/health

# Check application logs
docker logs bedlam-connect-blue
docker logs bedlam-connect-green
```

### Clean up everything

```bash
# Use cleanup script
./cleanup-docker.sh

# Or manual cleanup
docker stop $(docker ps -q --filter "name=bedlam-connect")
docker rm -f $(docker ps -aq --filter "name=bedlam-connect")
docker system prune -f
```

## 📊 Monitoring deployment

### Check current state

```bash
# See running containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check which instance nginx points to
cat /etc/nginx/sites-available/aimagain.art | grep "server 127.0.0.1"

# Test website
curl -f https://aimagain.art/health
```

### GitHub actions monitoring

- Watch workflow progress in GitHub Actions tab
- Check for SCP and deployment step failures
- Review logs for specific error messages

## 🔄 Rollback procedures

### Automatic rollback

The deployment script includes automatic rollback if:

- New instance fails health checks
- Nginx configuration update fails

### Manual rollback

```bash
# Switch nginx back to previous instance
sudo vim /etc/nginx/sites-available/aimagain.art
# Change upstream port back to working instance
sudo nginx -t && sudo nginx -s reload

# Or use the deployment script (detects current state)
./deploy.sh
```

## 📋 Maintenance tasks

### Regular maintenance

```bash
# Clean up old Docker images (monthly)
./cleanup-docker.sh

# Check disk space
df -h
docker system df

# Update deployment files
# (Automatically handled by GitHub actions)
```

### Emergency contacts

- **GitHub Actions**: Check [`.github/workflows/cd.yml`](../.github/workflows/cd.yml)
- **Droplet Access**: SSH key and connection details in GitHub secrets
- **DNS/SSL**: Managed by Certbot on droplet

---

## 🎯 Success criteria

Deployment is working correctly when:

- ✅ GitHub Actions completes without errors
- ✅ SCP step successfully copies files
- ✅ Website responds at https://aimagain.art
- ✅ Health endpoint returns 200 OK
- ✅ Zero downtime during deployment
- ✅ Old instances are properly cleaned up

CI handles the SCP step for you on every push to `main` — manual SCP from your laptop is the emergency fallback above, not the everyday workflow.
