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

Still open from the 006 checklist: portal config (plan switching disabled),
Stripe Tax + origin address, branding/statement descriptor, restricted API
key, webhook endpoint + secret (deferred until the 007 route is deployed),
and the same setup in live mode before rollout.
