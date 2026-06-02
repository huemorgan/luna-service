# Scenario 06 — Cold mobile first-impression test

## Preconditions

- Production deployed
- A phone you've never used to access luna.com.ai

## Scenario

On a real phone (or browser mobile emulation if no phone available — but real phone preferred):

1. Open `https://luna.com.ai` for the very first time
2. Don't sign in yet — just look at the landing
3. **Judge:** Does the layout work on my screen? Is text readable? Is the CTA tappable?
4. Tap "Sign in with Google"
5. Complete Google OAuth on mobile (Google handles its own mobile UX)
6. Land in chat
7. **Judge:** Is the chat usable on mobile? Can I type? Does the keyboard cover the input? Can I scroll?
8. Send 3 messages
9. **Judge:** Does streaming work on mobile? Is the keyboard behavior sane?

## Expected Behavior

- Landing page is mobile-responsive (no horizontal scroll, readable fonts)
- "Sign in with Google" CTA is large enough to tap
- After login, chat UI works on mobile (input not covered by keyboard, messages scroll)
- Streaming responses appear correctly
- No layout breakage in portrait or landscape

## Fail Conditions

- ❌ Horizontal scroll on landing
- ❌ Fonts too small / text overflowing containers
- ❌ Keyboard covers the input field
- ❌ Can't tap small buttons
- ❌ Chat messages overflow the viewport
- ❌ Site is rendered as a "tiny desktop view" (missing viewport meta)

## Verify

- Screenshots from real phone (or DevTools mobile preview if no phone)
- Test in both portrait and landscape
- Tested on at least one iOS (Safari) and one Android (Chrome)

## Notes

MVP is "desktop-first, mobile-functional" — not "mobile-perfect." Bar: a phone user can sign up and have a basic conversation. Not: a phone user has a polished native-app experience. That's post-MVP.
