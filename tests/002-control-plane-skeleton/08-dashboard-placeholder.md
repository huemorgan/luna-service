# Scenario 08 — Dashboard shows placeholder Luna state

## Preconditions

- Logged in as Alice
- 0 rows in `agents` for Alice's account

## Scenario

1. Land on `/dashboard`
2. Inspect the "Your Luna" card

## Expected Behavior

- Card shows clear status: "Not provisioned yet — coming in phase 003"
  - OR (if implementation has progressed): "Provision your Luna" button (disabled with tooltip "Coming soon")
- No broken images, no console errors
- No half-loaded chat UI

## Fail Conditions

- ❌ Card shows error state ("Failed to load Luna" — Luna isn't supposed to exist yet)
- ❌ Card shows a "running" Luna with fake data
- ❌ Console errors related to missing Luna URL
- ❌ Card is empty / invisible

## Verify

- Screenshot of dashboard card
- Browser console clear of errors

## Notes

This phase deliberately doesn't have Luna provisioning. The UI must communicate that clearly without looking broken.
