# Scenario 01 — DNS + TLS correctness

## Preconditions

- Production deployed
- DNS for `luna.com.ai` configured on Cloudflare

## Scenario

```bash
dig luna.com.ai +short
curl -I https://luna.com.ai
curl -I http://luna.com.ai   # should redirect to https
openssl s_client -connect luna.com.ai:443 -servername luna.com.ai </dev/null 2>/dev/null | openssl x509 -noout -dates -issuer -subject
```

In a real browser:
1. Visit `https://luna.com.ai` → check padlock
2. Visit `http://luna.com.ai` → verify auto-redirect to https
3. Visit `https://www.luna.com.ai` → should also work (or redirect to apex)

## Expected Behavior

- DNS resolves to Cloudflare IP
- HTTPS works with valid cert (issued by Let's Encrypt or Cloudflare)
- Cert covers `luna.com.ai` (and ideally `*.luna.com.ai` for future)
- HTTP → HTTPS redirect (308 or 301)
- No mixed content warnings
- HSTS header present

## Fail Conditions

- ❌ Cert mismatch, expired, or self-signed warning
- ❌ HTTP serves content instead of redirecting
- ❌ Mixed content
- ❌ Missing HSTS

## Verify

- Screenshot of padlock in browser
- Output of all curl commands
- ssllabs.com scan result (target: A or A+)
