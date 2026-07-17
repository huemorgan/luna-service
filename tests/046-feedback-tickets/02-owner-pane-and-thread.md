# 02 — Owner writes in the Feedback pane; admin replies; thread updates

**Goal:** the owner-facing pane can create a ticket, the admin can answer it,
and the reply shows threaded in the pane.

## Steps (owner pane)

1. In the Luna sidebar, open the **Feedback** pane.
2. Click "new", pick a category (e.g. Pricing), write a title + body, submit.
3. The pane returns to the list; the new ticket shows status
   "Waiting for the team".

## Steps (admin)

4. In the admin tab, `/admin/feedback` → the ticket is listed, origin = owner.
5. Open it, type a reply in the admin reply box, send.
6. Ticket status flips to **answered**; `last_admin_reply_at` is set.

## Steps (owner pane again)

7. Back in the pane, open the ticket. The admin reply is threaded under the
   owner's message, labelled "Luna team". Status pill = "Team replied".

## Pass / fail

- PASS: ticket created from the pane, admin reply visible in the thread,
  statuses correct on both sides.
- FAIL: pane create fails; admin reply doesn't appear; status stuck on open.
