# 4A. Payments & Billing

**Phase 4 | Effort: L | Dependencies: Auth (Phase 1A), Cost Management (Phase 3)**

## Current State

- No payment integration
- No subscription model
- No tier gating
- Application is entirely free

## What to Build

### Stripe Checkout

- Redirect-based payment flow (no raw card handling, minimal PCI scope)
- Perfect for HTMX — user clicks "Upgrade", redirects to Stripe, returns to app
- No custom payment form needed

### Account subscription fields

Add to `Account` document:

- `stripe_customer_id: Optional[str]`
- `subscription_tier: str` (free/pro, default: free)
- `subscription_status: Optional[str]` (active/past_due/canceled)
- `current_period_end: Optional[datetime]`

### Webhook handler

- `POST /webhooks/stripe` — receives Stripe events
- Handle: `checkout.session.completed`, `invoice.paid`, `customer.subscription.deleted`
- Keeps subscription state in sync with Stripe
- Verify webhook signature for security

### Tier gating

- Check subscription in `get_current_student()` or a new FastAPI dependency
- Free tier: unlimited A0 lessons, 10 A1 lessons lifetime (enforced in Phase 3)
- Pro tier: unlimited lessons at all CEFR levels

### Pages

- **Pricing page**: static template with Free vs Pro comparison, CTA buttons
- **Billing page** (`GET /account/billing`): current plan, usage stats, link to Stripe Customer Portal
- Stripe Customer Portal handles: cancel subscription, update payment method, view invoices

### Pricing strategy

- Start simple: **Free** and **Pro** ($X/month)
- Two tiers only — don't overcomplicate
- Price based on actual per-lesson costs from Phase 3

## Key Files

- `src/maestro/models.py` (Account subscription fields)
- `src/maestro/routes/` (new: billing routes, webhook handler)
- `src/maestro/auth.py` (tier check in dependency)
- `src/maestro/settings.py` (STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PRICE_ID)
- `templates/` (new: pricing.html, billing.html)

## Verification

- Can subscribe via Stripe Checkout, return to app with Pro access
- Webhook updates subscription status in DB
- Free tier limits enforced (10 A1 lesson cap, unlimited A0)
- Can cancel via Stripe Customer Portal, status updates in app
- Billing page shows current plan and usage
