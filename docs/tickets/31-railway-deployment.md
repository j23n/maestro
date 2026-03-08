# Railway deployment

**Area:** Railway dashboard, `Dockerfile`
**Roadmap:** [02-deploy](../roadmap/02-deploy.md)
**Depends on:** #27 (production Dockerfile), #28 (static assets), #29 (MongoDB Atlas), #30 (data seeding)

## Goal

Deploy the app to Railway with push-to-deploy from main, HTTPS, and all secrets configured.

## Work

### Railway project setup

- Create a Railway project linked to the GitHub repo
- Configure push-to-deploy from `main` branch
- Railway auto-detects the Dockerfile

### Environment variables

- Set via Railway dashboard (not .env files):
  - `MONGODB_URI` — Atlas connection string
  - `SECRET_KEY` — for cookie signing (generate a strong random value)
  - `ANTHROPIC_API_KEY` — for LLM calls
  - `ENVIRONMENT=production`
  - `ANALYSIS_ENABLED` — set as needed (False if no Apple Silicon)

### TLS/HTTPS

- Railway provides automatic TLS termination — no configuration needed
- Verify cookies have `Secure` flag in production

### Custom domain (optional)

- Configure custom domain in Railway if desired, otherwise use the provided `*.up.railway.app` domain

## Verification

- App accessible via HTTPS on Railway
- `GET /health` returns 200
- Lessons generate successfully against Atlas DB
- Ingest data present after first deploy
- Login/signup flow works with secure cookies

## Notes

- Railway is the simplest hosting option for a solo dev — built-in TLS, secrets management, push-to-deploy.
- `ANALYSIS_ENABLED=False` in production since Railway runs on Linux (no Apple Silicon for mlx-lm).
