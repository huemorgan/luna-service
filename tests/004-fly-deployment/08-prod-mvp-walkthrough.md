# Scenario 08 — Production MVP walkthrough

The final scenario. If this passes, MVP ships.

## Preconditions

- Phase 004 complete
- Production at `https://luna.com.ai`
- A test Google account you've never used here before
- A device you've never used here before (phone or fresh browser profile)

## Scenario

Be a real user. No insider knowledge. No mercy.

1. Receive a (pretend) link from a friend: "check this out, luna.com.ai"
2. Open it. **Judge:** what do I think this product is, just from the landing?
3. Sign up via Google.
4. Wait for provisioning. **Judge:** did the wait feel deliberate or did I think it was broken?
5. Land in chat. **Judge:** does it greet me appropriately? Is it clear what to do?
6. Have a real 15-minute conversation. Cover:
   - Introducing yourself, getting to know Luna
   - Asking for help with a real task you actually have right now
   - Saving something to memory
   - Coming back from memory
   - Trying any plugins that are exposed
   - Trying to do something Luna can't (yet) and seeing how it handles it
   - Asking Luna directly: "what should I tell my friend about you?"
7. Close the tab. Do something else for 30 minutes.
8. Come back. Verify everything's still there.
9. Sign out. Sign back in next day. Verify again.

## What Counts as Pass

- After 15 minutes, you'd genuinely tell a friend "you should try this"
- Nothing was so broken that it stopped you from continuing
- Luna felt like *yours* — not a demo, not a chatbot, but an agent that knows you a little bit
- Returning the next day felt right — same Luna, same memory, same vibe

## What Counts as Fail

- Anything in your 15 minutes made you think "I should report a bug" — anything that visible
- The cold-start felt longer than 60s without explanation
- An error left you stuck and you had to refresh
- Coming back next day broke continuity
- You wouldn't recommend it

## Verify

- Write a 3-paragraph honest review in `dojo-results/0004-004-fly-deployment/scenario-08-walkthrough.md`
- Include screenshots of best + worst moments
- Open a follow-up issue for each "would not recommend" reason

## Notes

This is the moment of truth. Every prior test verifies parts. This verifies the whole. Don't grade on a curve. The user's first impression IS the product.

If this passes, **the MVP is shipped**. Go celebrate. Then start phase 005 (post-MVP polish + the next feature).
