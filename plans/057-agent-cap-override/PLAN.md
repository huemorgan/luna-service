# 057 — Per-account active-Luna cap override

## Context

Roy (2026-07-23): some free-tier users should be able to create MORE agents
while still burning credits normally. Credits must never be bypassed.

Today the trial tier caps active agents at 1 (`trial.active_luna_cap` in the
commercial pricing config), enforced at agent creation
(`cloud/api/agent_routes.py:257`) — but ONLY for trial accounts
(`is_trial_account` = no paid grant lot). The only existing way to lift the
cap is comping the account onto "paying" (a synthetic paid lot, done for
roniak 2026-07-22), which is too blunt: it also removes the trial per-agent
daily/monthly spend caps and the trial badge.

Metering is unaffected either way: every agent burns hosting (999
credits/month via `AgentHostingPeriod`) plus usage — extra agents naturally
cost the user credits, which is the intended model.

## Change

1. **Schema**: `billing_accounts.active_luna_cap_override INTEGER NULL`
   (NULL = use the pricing-config default). Migration + model field.
2. **Enforcement**: in `create_agent`, resolve
   `cap = override if set else billing_grants.active_luna_cap(config)`;
   override applies whether or not the account is trial (a paying account
   with an override set gets capped too — symmetric, but overrides for
   paying accounts are not the use case).
3. **Admin API** (`/api/admin/pricing`):
   - `POST /accounts/{account_id}/limits` body
     `{active_luna_cap: int|null, reason}` — sets/clears the override,
     writes the standard audit row (financial-adjacent: non-empty reason
     required).
   - Include `active_luna_cap_override` in `GET /accounts/search` rows so
     the enforcement UI can show it.
4. **User-visible**: `/api/billing/summary` trial block reports the
   effective cap (today it reports the config value) so the UI banner says
   "your trial includes N active Luna" truthfully.
5. **Tests**: override honored for trial account (create 2nd/3rd agent),
   NULL falls back to config, audit row written, spend caps still applied
   to new trial agents, metering untouched.

Explicitly NOT in scope: any enforcement/metering bypass — overrides never
touch credit burn.

## Status

- [ ] Schema + migration
- [ ] create_agent override resolution
- [ ] Admin endpoint + audit + search exposure
- [ ] summary effective-cap fix
- [ ] Tests (cloud suite)
- [ ] Deploy + set override for the first user (Roy to name them)
