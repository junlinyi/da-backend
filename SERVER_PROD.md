# Production Server — Railway Deployment Plan

## Overview

The backend runs on [Railway](https://railway.app). There are two environments:

| Environment | Branch | URL | Purpose |
|---|---|---|---|
| **Staging** | `staging` | `https://da-backend-staging.up.railway.app` | Test every change before it reaches real users |
| **Production** | `main` | `https://da-backend-prod.up.railway.app` | Live app |

Code flows one direction: `feature branch → staging → main (prod)`. Nothing goes straight to production.

---

## One-Time Setup

### 1. Create the Railway project

1. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**
2. Select the `da-backend` directory (or the monorepo root and set the root directory to `da-backend/`)
3. Railway detects the `Dockerfile` automatically

### 2. Create two environments

In the Railway dashboard: **Environments → New Environment**
- Name one `staging`, one `production`
- Each gets its own PostgreSQL database and its own set of env vars

### 3. Connect branches to environments

In each environment's service settings → **Source → Branch**:
- `staging` environment → track branch `staging`
- `production` environment → track branch `main`

Now every push to `staging` deploys to staging, every merge to `main` deploys to prod.

### 4. Add PostgreSQL

In each environment: **New → Database → PostgreSQL**
Railway injects `DATABASE_URL` automatically — no manual configuration needed.

### 5. Set environment variables

Set these in **both** environments (staging and production) via the Railway dashboard.  
Never commit secrets to Git.

```
# App
ENVIRONMENT=production          # or: staging
ALLOWED_ORIGINS=https://your-domain.com   # comma-separated

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_API_KEY_SID=SKxxxxxxxx
TWILIO_API_KEY_SECRET=xxxxxxxx

# Firebase (see section below — stored as base64, not a file)
FIREBASE_CREDENTIALS_B64=<base64-encoded JSON>

# Sentry (optional but recommended)
SENTRY_DSN=https://xxxxx@sentry.io/xxxxx

# Railway injects automatically:
# DATABASE_URL=postgresql+asyncpg://...
```

### 6. Handle the Firebase credentials file

Railway can't read files from disk, so the service account JSON is stored as a base64 env var and decoded at startup.

**Encode the JSON locally (run once):**
```bash
base64 -i facedate-6616e-ebf102022977.json | tr -d '\n'
```
Paste the output as the value of `FIREBASE_CREDENTIALS_B64` in Railway.

**Update `app/firebase.py` to decode it at startup:**
```python
import base64, json, tempfile, os

b64 = os.getenv("FIREBASE_CREDENTIALS_B64")
if b64:
    cred_json = json.loads(base64.b64decode(b64))
    cred = credentials.Certificate(cred_json)
else:
    # Local dev fallback: read from file path
    cred_path = os.getenv("FIREBASE_CREDENTIAL_PATH", "facedate-6616e-ebf102022977.json")
    cred = credentials.Certificate(cred_path)
```

### 7. Run Alembic migrations on first deploy

In Railway dashboard → **Settings → Deploy → Pre-deploy Command**:
```
alembic upgrade head
```
This runs migrations automatically before each new deployment.

---

## Daily Development Workflow

### Making a change

```bash
# 1. Create a feature branch from staging
git checkout staging
git pull
git checkout -b fix/age-preference-crash

# 2. Make your changes and commit
git add .
git commit -m "fix: handle None age preferences in firebase matchmaking"

# 3. Push the feature branch
git push origin fix/age-preference-crash
```

### Deploying to staging

```bash
# Merge into staging — triggers automatic Railway deployment
git checkout staging
git merge fix/age-preference-crash
git push origin staging

# Railway builds and deploys in ~2-4 minutes
# Watch progress at: railway.app dashboard → staging environment
```

### Verifying on staging

1. Open Railway dashboard → staging → **Logs** tab — confirm no startup errors
2. Hit the health check: `curl https://da-backend-staging.up.railway.app/health`
3. Test the specific endpoint you changed
4. If something is broken: fix on the feature branch, merge to staging again
5. If staging looks good: proceed to production

### Promoting to production

```bash
# Merge staging into main — triggers Railway prod deployment
git checkout main
git merge staging
git push origin main
```

Railway deploys with zero downtime — the old container stays up until the new one is healthy.

### Rolling back

If prod breaks after a deploy:
- Railway dashboard → **production** environment → **Deployments** tab
- Click the previous deployment → **Redeploy**
- Takes ~30 seconds

---

## Connecting the iOS App

Update `APIConfig.swift` to point at Railway instead of the local IP:

```swift
#if DEBUG
static let defaultBaseURL = "http://localhost:8000"  // local dev
#else
static let defaultBaseURL = "https://da-backend-prod.up.railway.app"
#endif
```

For TestFlight / beta builds, you can add a third case pointing at staging.

---

## Monitoring

| What | Where |
|---|---|
| Runtime logs | Railway dashboard → environment → Logs |
| Errors + stack traces | Sentry (once `SENTRY_DSN` is set) |
| Health check | `GET /health` → `{"status":"ok","db":"connected"}` |
| Roll back a deploy | Railway dashboard → Deployments → Redeploy |

---

## Cost Estimate

Railway's Hobby plan ($5/mo) covers both environments comfortably for early beta:

| Resource | Usage | Est. Cost |
|---|---|---|
| Backend service (2 envs) | ~0.5 vCPU, 512MB RAM | ~$3–5/mo |
| PostgreSQL (2 envs) | < 1GB each | ~$1–2/mo |
| **Total** | | **~$5–8/mo** |

Upgrade to Pro when you have paying users or need more than 8GB RAM.

---

## What's Already Done

- `da-backend/Dockerfile` — production-ready (no `--reload`, port 8000)
- `ENVIRONMENT` / `ALLOWED_ORIGINS` checks in `app/main.py`
- `SENTRY_DSN` support in `app/main.py`
- `GET /health` endpoint with DB probe
- Alembic migrations ready (`alembic upgrade head`)

## Still To Do Before First Deploy

- [ ] Update `app/firebase.py` to support `FIREBASE_CREDENTIALS_B64` env var
- [ ] Create `staging` branch in git: `git checkout -b staging && git push origin staging`
- [ ] Create Railway project and connect GitHub repo
- [ ] Create staging and production environments in Railway
- [ ] Add PostgreSQL to each environment
- [ ] Set all env vars in both environments
- [ ] Set pre-deploy command to `alembic upgrade head`
- [ ] Rotate Twilio credentials before going live (they've been on disk)
- [ ] Update `APIConfig.swift` production URL
