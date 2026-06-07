# Page Story Guidelines

> How every page on luna.com.ai must be structured. These rules are non-negotiable.

---

## The Core Principle

**Every page tells one story. That story is told many times within the page — once in full at the top, and again from a different angle in every section.**

Why: users have no patience. They drop off at any point. If the story only lands at the bottom, most users never get it. So:

- The **upper fold** tells the complete story in its most compressed form.
- Each **section** retells the story from a different angle.
- If a user reads only one section and leaves, they still got the story.

---

## The Reading Layers

A well-built page works at four levels of depth. Each level is self-sufficient — a user who stops at any layer has received the full essence:

### Layer 1: Titles only
Read just the section titles top to bottom. You get the complete story.

### Layer 2: Titles + subtitles
Read titles and subtitles. You get a deeper version of the same story with more texture.

### Layer 3: One section in full
Read any single section — title, subtitle, body, visual. You get the whole story told through that section's lens.

### Layer 4: Full page
Read everything. You get the detailed, comprehensive version with evidence, specifics, and proof.

**If your page doesn't work at all four layers, rewrite it.**

---

## Section Anatomy

Every section has exactly four elements:

| Element | Purpose | Rule |
|---------|---------|------|
| **Title** | The story from this angle, in one line | Must be meaningful standalone. Not clever, not vague. If someone reads only titles, the story is clear. |
| **Subtitle** | The value proposition or "so what" of this section | Deepens the title. Adds the dimension the title compressed away. |
| **Content** | The evidence, details, specifics | 1–3 short paragraphs max. Concrete, not abstract. Numbers, comparisons, specifics — not adjectives. |
| **Visual** | The proof or emotional anchor | Screenshot, diagram, illustration, or comparison. Must carry meaning — not decoration. If you removed the text, the visual alone should hint at the story. |

No section is allowed to have content without a visual. No section is allowed to have a visual without content. They work as a pair.

---

## The Apple Test

Consider how Apple structures a product page. The MacBook page:

**Hero (upper fold):**
> "Your personal computer. Reimagined."

That's the whole story in six words. It's something familiar made new. You don't know the details yet, but you know the essence: this is not what you knew before.

**Section: Retina Display**
- **Title:** "Retina display" — names the thing
- **Subtitle:** "A revolutionary display with resolution that matches your eyes" — tells you it's new, better, and why it matters to you
- **Content:** Specifics on resolution, pixel density, color accuracy — evidence
- **Visual:** A macro shot showing impossible detail — proof

This section alone tells the whole MacBook story: *this is something new and better than what existed before*. The Retina display is the lens; the story is the same.

**Section: Battery**
- **Title:** "All-day battery life"
- **Subtitle:** "A battery that lasts longer than you do"
- **Content:** Hours, comparison to previous generation, real-world usage scenarios
- **Visual:** A timeline or clock visualization showing the long duration

Again — same story (*reimagined, better than before*), different angle (battery instead of display). A user who reads only this section still gets it: this machine is a leap forward.

---

## Applying This to Luna

### The Luna story in one sentence:
**"Your own AI agent — persistent, private, open source, ready in 60 seconds."**

Every section on every page must retell this story from its angle.

### Example: Landing page sections through this lens

**Hero:**
- **Title:** "Your own AI agent."
- **Subtitle:** "In the cloud. In under a minute."
- This is the complete story compressed. You know: it's yours (private), it's an agent (not a chatbot), it's cloud-hosted, it's instant.

**Section: Memory**
- **Title:** "Remembers everything."
- **Subtitle:** "Cross-session memory that actually works — ask about last month and Luna knows."
- **Content:** How Postgres-backed memory differs from ChatGPT's amnesia. Search across conversations. Semantic recall.
- **Visual:** A conversation screenshot where Luna recalls something from weeks ago.
- **Story retold:** This is YOUR agent (it remembers YOU). It's persistent (not disposable). It's better than what exists (ChatGPT forgets).

**Section: Approvals**
- **Title:** "Asks before it acts."
- **Subtitle:** "Architectural approval gates the AI cannot bypass — not a prompt, a hard stop."
- **Content:** How the approval system works. Four options. Standing approvals visible and revocable.
- **Visual:** An approval card screenshot showing the four-button interface.
- **Story retold:** It's YOUR agent (respects your authority). It's private (your approval, your control). It's different from other agents (real safety, not theater).

**Section: Open Source**
- **Title:** "Open source. Not open-washing."
- **Subtitle:** "MIT licensed. 4,600 lines. Run it yourself or let us host it."
- **Content:** What's open, what's proprietary, the promise that binds acquirers.
- **Visual:** GitHub star counter + code architecture diagram.
- **Story retold:** It's YOURS (you can take it and leave). It's real (small enough to read in a day). Ready in 60 seconds (hosted) or self-host (your choice).

Each section is the whole Luna story seen through one capability's lens. A user who reads only the Approvals section and bounces still knows: *Luna is a private, trustworthy AI agent I can control.*

---

## The Drop-Off Rule

Imagine your page as a waterfall. Users pour in at the top and leak out at every section. By the bottom, you have 10–20% of your original visitors.

```
100% ──── Hero
 70% ──── Section 1
 50% ──── Section 2
 35% ──── Section 3
 25% ──── Section 4
 15% ──── Section 5
 10% ──── Final CTA
```

**Implication:** The hero must be complete. Section 1 must be complete. Section 2 must be complete. Every section must be complete. There is no "building up to a point" — every point must land where it lives.

**Anti-pattern:** "Features" at the top, "Why it matters" at the bottom. Most users never see why it matters. Flip it: lead every section with why it matters, follow with the feature that delivers it.

**Anti-pattern:** A pricing page that explains the product first and shows prices at the bottom. Most users came to see prices. Show prices immediately, explain value alongside.

**Anti-pattern:** A "How it works" section that requires reading all three steps to understand the value. Each step must independently convey value.

---

## No Meta-Talk

**Every title and subtitle must carry information. Never describe the section — deliver the value.**

A title that talks about what the section contains instead of giving the reader something is wasted space. It says "I'm about to tell you something" instead of telling them.

**Bad:**
- "Under the hood." — describes the section, says nothing
- "If you're here, you probably want to know how it works." — condescending, meta, zero information
- "Let's dive into the features." — narrating the page, not serving the reader
- "Here's what makes Luna different." — promises value without delivering it
- "In this section we'll cover..." — documentation style, not website copy

**Good:**
- "A scaffold you can build on." — tells you what the architecture is for
- "Small core, plugin-everything. Every component is swappable." — actual information
- "Durable execution with hard interrupt nodes." — specific, technical, useful

**The test:** If you removed the title and subtitle, would the reader lose information? If not, they were meta-talk. Rewrite until removing them would cost the reader something.

---

## Visual Rules

1. **Every visual must carry meaning.** No stock photos. No abstract gradients. No "person smiling at laptop." If the visual doesn't help tell the story, cut it.

2. **Screenshots are better than illustrations** when the product is real. Show the actual UI. Users trust screenshots; they distrust polished illustrations (smells like vaporware).

3. **Diagrams explain architecture.** When the section is about how something works (isolation, approvals, plugin system), a clean diagram is the right visual.

4. **Comparisons use visuals.** "Luna vs ChatGPT" — show them side by side. Not a table buried in text. A visual comparison.

5. **The visual should work without text.** If you showed someone only the visuals from top to bottom, they should get a rough sense of the story.

---

## Checklist Before Shipping a Page

- [ ] Can someone read only the hero and know what this page is about?
- [ ] Can someone read only the section titles (top to bottom) and get the full story?
- [ ] Can someone read titles + subtitles and get a deeper story?
- [ ] Can someone read any ONE section and walk away understanding the core value?
- [ ] Does every section have: title, subtitle, content, visual?
- [ ] Does every visual carry meaning (not decoration)?
- [ ] Is the most important information above the fold?
- [ ] Is there a CTA visible without scrolling?
- [ ] If a user drops off after section 2, did they still get the story?
- [ ] Read the titles aloud — do they sound like a story, not a feature list?
