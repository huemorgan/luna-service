# Scenario 15 — Full MVP walkthrough (end-of-phase smoke)

The agent-live-walkthrough scenario. End-of-phase qualitative judgment.

## Preconditions

- Phase 003 fully implemented
- Stack running locally
- Fresh DB

## Scenario

Pretend you are a non-technical first-time user. Don't cheat by knowing the implementation. Just use it.

1. Open `http://localhost:8000/` in incognito
2. **Judge:** Does the landing page tell me what this is? Is the CTA obvious?
3. Click "Sign in with Google" (stub: pick a fresh test user, e.g., "Charlie")
4. **Judge:** Is the wait time tolerable? Does the system tell me what's happening?
5. Land on chat. **Judge:** Does it feel like *my* Luna? Or like a generic chat?
6. Have a real 10-turn conversation. Topics:
   - Introduce yourself
   - Ask Luna what it can do
   - Ask Luna to remember something specific
   - Ask Luna about that specific thing
   - Ask Luna for an opinion on something subjective
   - Ask Luna for help with a small task (e.g., "Help me draft an email to my dentist")
   - Test a plugin if any are exposed in MVP build (e.g., web search if Tavily is configured)
   - Try to confuse Luna deliberately
   - Sign out mid-thought
   - Sign back in, continue the conversation
7. **Judge the entire experience as a whole.** Write 1-2 paragraphs of your honest reaction.

## What Counts as Pass

- Landing → first message: < 60 seconds, felt deliberate (not buggy)
- Luna's replies feel coherent and reasonably helpful
- Memory works (Luna recalls what you told it)
- Sign out / sign back in seamless
- You finished the walkthrough thinking: "This is rough but real. People could use it."

## What Counts as Fail

- You finished thinking: "I would never recommend this."
- Anything errored out and you didn't know how to recover
- A response was so bad it felt like the product was broken
- The wait time felt wrong (way too long, or weirdly long for nothing happening)
- You forgot you were testing and just... left

## Verify

- Write your reaction in `dojo-results/000X-003-.../scenario-15-walkthrough.md`
- Include screenshots of the most representative moments (best and worst)
- List 3 things you'd improve before showing this to a real user

## Notes

The previous 14 scenarios verify that the pieces work. This scenario verifies that the **whole** works. They're not the same thing. A product can pass all tests and still feel terrible.

This is the bar: would a real human, with no investment in the project, recommend it to a friend after this walkthrough? If yes, phase 003 is done. If no, find what's wrong and fix it.
