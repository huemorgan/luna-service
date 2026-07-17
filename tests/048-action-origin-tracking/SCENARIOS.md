# 048 — Action origin tracking + Usage chart polish (dojo scenarios)

Runner: `dojo_action_origin.py` (headless Playwright + real Postgres). Seeds
28 days of billable_events across five origins, including a **scheduled
playbook** (channel=scheduler, root_action_type=playbook_run) that must land
under Scheduled — not Playbooks — by precedence, and a **user-initiated
playbook** (channel=web, root_action_type=playbook_run) under Playbooks.

## S1 — No day-range filter; fixed 28 days

- `/dashboard/usage`.
- PASS: no Today/7d/Custom range buttons; a "Last 28 days" label is shown;
  the Luna filter select remains.

## S2 — Five sections, shared y-scale

- PASS: headings Chat, Scheduled triggers, Playbooks, WhatsApp, Telegram.
  Chat bars are tall; Telegram bars are short on the same scale.

## S3 — Precedence + per-item expand

- PASS: expanding Scheduled triggers lists the scheduled playbook among the
  triggers (NOT under Playbooks); expanding Playbooks lists the
  user-initiated playbook. API: scheduler total includes the scheduled
  playbook's credits; playbooks total excludes them.

## S4 — Chart polish

- PASS: bars have no rounded corners (no `rounded*` class) and no horizontal
  gridline elements; the plot area is ~half the card width; bar height is
  small (~40px). `y_max = max(peak, 200)`.
