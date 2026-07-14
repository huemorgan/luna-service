# 039/006 — test-mode Stripe bindings (2026-07-14)

Account: `acct_1TJBzVQ1TPVjJHaq` (test mode / sandbox). Created via the
Stripe API from the local `.stripe-dev.env` key; one Product per versioned
product key, one Price each, `lookup_key` = product key,
`metadata.luna_product_key` set on both objects. IDs are identifiers, not
secrets.

| lookup_key | Product | Price | Amount | Interval |
|---|---|---|---:|---|
| `hobby_19_monthly` | `prod_UsqgVjgXnWOXmV` | `price_1Tt4zZQ1TPVjJHaqmcCSJ2DK` | $19.00 | monthly |
| `hobby_19_yearly` | `prod_UsqglF96ERDJMU` | `price_1Tt4zaQ1TPVjJHaqMxS8MD59` | $228.00 | yearly |
| `recurring_99_monthly` | `prod_UsqgvVcDCyJJnX` | `price_1Tt4zbQ1TPVjJHaquAj9WORU` | $99.00 | monthly |
| `recurring_99_yearly` | `prod_UsqgnsTaoASqFX` | `price_1Tt4zcQ1TPVjJHaqEu338V4V` | $1,188.00 | yearly |
| `recurring_199_monthly` | `prod_UsqhNtIc4Y8ouY` | `price_1Tt4zdQ1TPVjJHaqY9r8hO8J` | $199.00 | monthly |
| `recurring_199_yearly` | `prod_UsqhSVuGggQ3js` | `price_1Tt4zeQ1TPVjJHaqwKJoWFJV` | $2,388.00 | yearly |
| `topup_10` | `prod_UsqhJlPzSzHBZe` | `price_1Tt4zfQ1TPVjJHaqtw7Ak3Yu` | $10.00 | one-time |
| `topup_25` | `prod_UsqhwKq42ACZJ7` | `price_1Tt4zgQ1TPVjJHaq7LxyprYm` | $25.00 | one-time |
| `topup_50` | `prod_UsqhnHgFEHCfi8` | `price_1Tt4zhQ1TPVjJHaqULgZKW0A` | $50.00 | one-time |
| `topup_100` | `prod_UsqhnHZny9pCsy` | `price_1Tt4ziQ1TPVjJHaqiwOpYTys` | $100.00 | one-time |

## Portal and tax (2026-07-14, via API)

- Billing Portal default configuration `bpc_1Tt5IrQ1TPVjJHaqfGPAl5g0`:
  payment-method update, invoice history, tax-ID update, cancellation at
  period end; **subscription_update disabled** (plan switching is
  code-owned per the 006 plan).
- Stripe Tax defaults set to `tax_behavior=exclusive` (credits derive from
  the pretax amount). Status stays `pending` on `head_office` — needs the
  business address, dashboard-only.

## Still open (dashboard-only; API refuses own-account updates)

- Business profile: name, support email, statement descriptor, branding
  (Settings → Business / Branding).
- Tax head-office address (Settings → Tax).
- Restricted API key for 007 (Developers → API keys → Create restricted
  key) — write: Customers, Checkout Sessions, Subscriptions, Billing
  Portal, PaymentIntents, SetupIntents, PaymentMethods, Refunds; read:
  Invoices, Charges, Products/Prices, Disputes.
- Webhook endpoint + secret: deferred until the 007 route is deployed.
- Live-mode repeat before rollout (010 gates).
