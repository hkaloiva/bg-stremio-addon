# Koyeb Deployment Guide

## Prerequisites

1. **Koyeb CLI** installed:
   ```bash
   npm install -g @koyeb/koyeb-cli
   ```

2. **Login to Koyeb**:
   ```bash
   koyeb login
   ```

3. **Git repository** set up and connected to GitHub

---

## Quick Deploy

```bash
./deploy-koyeb.sh <SERVICE_ID>
```

Example:
```bash
./deploy-koyeb.sh toast-translator-kaloyan8907-8d1fe372
```

---

## What the Script Does

1. ✅ Checks for uncommitted changes and commits them
2. ⬆️ Pushes to GitHub
3. 📦 Creates a Koyeb archive (ignores node_modules, cache, etc.)
4. 🐳 Deploys using `Dockerfile.koyeb`
5. 📊 Shows deployment ID

---

## Manual Deployment

If you prefer manual control:

### 1. Commit and Push
```bash
git add -A
git commit -m "Deploy: latest changes"
git push origin main
```

### 2. Create Archive
```bash
koyeb archives create . \
  --ignore-dir .git \
  --ignore-dir .venv \
  --ignore-dir cache \
  -o json
```

### 3. Deploy
```bash
koyeb services update <SERVICE_ID> \
  --archive <ARCHIVE_ID> \
  --archive-builder docker \
  --docker Dockerfile.koyeb
```

---

## Monitor Deployment

### Build Logs
```bash
koyeb service logs <SERVICE_ID> --type build --tail
```

### Runtime Logs
```bash
koyeb service logs <SERVICE_ID> --type runtime --tail
```

### Service Status
```bash
koyeb service get <SERVICE_ID>
```

---

## Environment Variables

Set these in the Koyeb dashboard or via CLI:

```bash
koyeb services update <SERVICE_ID> \
  --env TMDB_KEY=your_key \
  --env ADMIN_PASSWORD=your_password \
  --env DEFAULT_STREAM_ENRICH_LEVEL=1
```

Required:
- `TMDB_KEY` - TMDB API key for translations

Optional:
- `ADMIN_PASSWORD` - Dashboard access
- `DEFAULT_STREAM_ENRICH_LEVEL` - Stream enrichment (0/1/2)
- `RD_TOKEN` - RealDebrid token
- `OPENSUBTITLES_API_KEY` - OpenSubtitles API key
- `BG_SUBS_*` - BG subtitle scraper settings

---

## Troubleshooting

### Registry 500 Errors
If deployment fails with registry errors, retry:
```bash
koyeb services redeploy <SERVICE_ID> --use-cache --wait
```

### Build Failures
Check build logs:
```bash
koyeb service logs <SERVICE_ID> --type build
```

### Runtime Errors
Check application logs:
```bash
koyeb service logs <SERVICE_ID> --type runtime --tail
```

### Health Check
Test the deployment:
```bash
curl https://<your-app>.koyeb.app/healthz
```

---

## Rollback

To rollback to a previous deployment:

```bash
# List deployments
koyeb deployments list --service <SERVICE_ID>

# Redeploy a specific one
koyeb services redeploy <SERVICE_ID> --deployment <DEPLOYMENT_ID>
```

---

## Performance Tips

1. **Set enrichment level** to 1 for fast stream loading:
   ```bash
   --env DEFAULT_STREAM_ENRICH_LEVEL=1
   ```

2. **Increase worker count** if needed (update entrypoint.sh):
   ```bash
   gunicorn -w 4 ...  # Instead of -w 2
   ```

3. **Monitor memory** usage in Koyeb dashboard

---

## Service Info

Your current deployment URL:
```
https://toast-translator-kaloyan8907-8d1fe372.koyeb.app
```

Endpoints:
- Health: `/healthz`
- Manifest: `/manifest.json`
- BG Subtitles: `/bg/manifest.json`
- Dashboard: `/dashboard`
