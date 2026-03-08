# Maestro Launch Roadmap

Maestro is a working Italian learning app (FastAPI + Beanie + HTMX) with a mature learning engine but no production infrastructure. This roadmap covers what's needed to ship it as a monetizable SaaS product.

## Phases

| Phase | Workstreams | Effort | Timeline |
|-------|-------------|--------|----------|
| 1 | [Auth & Users](01-auth.md) + [Deploy](02-deploy.md) | M + M | wk 1-3 |
| 2 | [CI/CD](03-cicd.md) + [Monitoring](04-monitoring.md) | S + S | wk 3-4 |
| 3 | [LLM Cost Management](05-llm-costs.md) | M | wk 4-6 |
| 4 | [Payments](06-payments.md) + [Email](07-email.md) | L + S | wk 6-9 |
| 5 | [Feedback](08-feedback.md) + [Admin](09-admin.md) | S + S | wk 9-10 |

Critical path: Auth -> Deploy -> Cost Tracking -> Payments.

~10 weeks for a solo dev full-time.

## Stack Additions

| Need | Tool | Why |
|------|------|-----|
| Passwords | `passlib[bcrypt]` | Standard, battle-tested |
| Sessions | `itsdangerous` | Signed cookies, no external store |
| CSRF | `starlette-csrf` | Middleware, works with HTMX forms |
| Rate limiting | `slowapi` | Built on `limits`, FastAPI-native |
| Error tracking | Sentry | Free tier, 2-min setup |
| Hosting | Railway | Push-to-deploy, built-in TLS |
| Database | MongoDB Atlas | Free tier, managed, replica set |
| Payments | Stripe Checkout | Redirect-based, minimal PCI scope |
| Email | Resend | Simple API, generous free tier |
