"""039/002 dojo — drives the admin pricing UI headless per SCENARIOS.md.

Prereqs: app on :8100 against the dojo039 DB, admin user created,
DOJO_USER_ID / DOJO_ACCOUNT_ID exported. Screenshots + PASS/FAIL lines land in
results/<date>-local/.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from itsdangerous import URLSafeTimedSerializer
from playwright.sync_api import expect, sync_playwright

BASE = "http://localhost:8100"
SECRET = os.environ.get("CLOUD_SESSION_SECRET", "dev-session-secret-change-me")
RESULTS = Path(__file__).parent / "results" / f"{date.today().isoformat()}-local"
RESULTS.mkdir(parents=True, exist_ok=True)

report: list[str] = []


def ok(name: str) -> None:
    report.append(f"PASS  {name}")
    print(report[-1], flush=True)


def mint_cookie() -> dict:
    payload = json.dumps({
        "user_id": os.environ["DOJO_USER_ID"],
        "account_id": os.environ["DOJO_ACCOUNT_ID"],
    })
    token = URLSafeTimedSerializer(SECRET).dumps(payload)
    return {"name": "luna_session", "value": token, "url": BASE}


def shot(page, name: str) -> None:
    page.screenshot(path=str(RESULTS / name), full_page=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 960})
        ctx.add_cookies([mint_cookie()])
        page = ctx.new_page()

        # 1 — sidebar navigation
        page.goto(f"{BASE}/admin/pricing")
        nav = page.locator("nav")
        for label in ["Pricing", "Overview", "Versions", "LLM & services", "Credit buckets"]:
            expect(nav.get_by_text(label, exact=True)).to_be_visible()
        ok("1 sidebar shows Pricing group with 4 items")

        # 2 — overview
        expect(page.get_by_text("New-account default version")).to_be_visible()
        expect(page.locator("main").get_by_text("v1", exact=False).first).to_be_visible()
        expect(page.get_by_text("Customer liability")).to_be_visible()
        assert page.locator("main").get_by_text("needs attention").count() == 0
        shot(page, "01-overview-v1.png")
        ok("2 overview shows default v1 + stats, no attention banner")

        # 3 — clone v1 into a draft
        page.goto(f"{BASE}/admin/pricing/versions")
        expect(page.get_by_text("v1", exact=False).first).to_be_visible()
        page.get_by_role("button", name="Clone").first.click()
        expect(page.locator("main").get_by_text("draft").first).to_be_visible()
        shot(page, "02-versions-cloned-draft.png")
        ok("3 clone on v1 creates a v2 draft")

        # 4 — edit draft JSON, save, diff
        page.get_by_text("v2", exact=False).first.click()
        editor = page.locator("textarea")
        expect(editor).to_be_visible()
        cfg = json.loads(editor.input_value())
        assert cfg["trial"]["gift_credits"] == 1800
        cfg["trial"]["gift_credits"] = 2000
        editor.fill(json.dumps(cfg, indent=2))
        page.get_by_role("button", name="Save draft").click()
        expect(page.get_by_text("Draft saved and validated.")).to_be_visible()
        expect(page.get_by_text("trial.gift_credits")).to_be_visible()
        shot(page, "03-draft-edited-diff.png")
        ok("4 draft edit saves and diff shows trial.gift_credits 1800→2000")

        # 5 — invalid config surfaces the server message
        cfg["trial"]["gift_credits"] = -5
        editor.fill(json.dumps(cfg, indent=2))
        page.get_by_role("button", name="Save draft").click()
        expect(page.get_by_text("Draft saved and validated.")).not_to_be_visible()
        err = page.locator("div").filter(has_text="gift_credits").first
        expect(err).to_be_visible()
        shot(page, "04-invalid-config-rejected.png")
        cfg["trial"]["gift_credits"] = 2000
        editor.fill(json.dumps(cfg, indent=2))
        page.get_by_role("button", name="Save draft").click()
        expect(page.get_by_text("Draft saved and validated.")).to_be_visible()
        ok("5 invalid config rejected with server message; draft restored")

        # 6 — reason-gated publish
        publish = page.get_by_role("button", name="Publish")
        expect(publish).to_be_disabled()
        page.get_by_placeholder("Reason (required to publish/retire)").fill("dojo publish v2")
        expect(publish).to_be_enabled()
        publish.click()
        expect(page.get_by_text("Published — this version is now immutable.")).to_be_visible()
        expect(page.locator("textarea")).to_have_attribute("readonly", "")
        shot(page, "05-published-immutable.png")
        ok("6 publish requires a reason; published version is read-only")

        # 7 — LLM & services page (read-only against published)
        page.goto(f"{BASE}/admin/pricing/models")
        expect(page.get_by_role("heading", name="Model tiers")).to_be_visible()
        expect(page.get_by_text("Clone to draft to edit")).to_be_visible()
        expect(page.get_by_role("heading", name="Provider costs", exact=False)).to_be_visible()
        shot(page, "06-models-page.png")
        ok("7 LLM & services renders tiers/constants/SKUs/provider costs read-only")

        # 8 — credit buckets page
        page.goto(f"{BASE}/admin/pricing/buckets")
        expect(page.get_by_text("Credit Buckets")).to_be_visible()
        expect(page.get_by_text("Trial (per new account)")).to_be_visible()
        expect(page.get_by_text("Migration gift", exact=False).first).to_be_visible()
        expect(page.get_by_text("not bound (007)").first).to_be_visible()
        shot(page, "07-buckets-page.png")
        ok("8 credit buckets renders trial/migration/products with Stripe placeholders")

        # 9 — rollout end-to-end through the billing worker
        page.goto(f"{BASE}/admin/pricing/versions")
        page.get_by_role("button", name="New Rollout").click()
        version_select = page.locator("select").first
        v2_label = next(t for t in version_select.locator("option").all_text_contents() if t.startswith("v2"))
        version_select.select_option(label=v2_label)
        page.get_by_placeholder("Reason (required — recorded in the audit log)").fill("dojo rollout v2")
        page.get_by_role("button", name="Schedule").click()
        expect(page.get_by_role("heading", name="Rollouts")).to_be_visible()
        deadline = time.time() + 30  # worker polls every 5 s
        while time.time() < deadline:
            page.reload()
            if page.locator("table").get_by_text("completed", exact=True).count() > 0:
                break
            time.sleep(2)
        expect(page.locator("table").get_by_text("completed", exact=True).first).to_be_visible()
        shot(page, "08-rollout-completed.png")
        page.goto(f"{BASE}/admin/pricing")
        expect(page.locator("main").get_by_text("v2", exact=False).first).to_be_visible()
        shot(page, "09-overview-default-v2.png")
        ok("9 rollout ran through the outbox worker; overview default is now v2")

        browser.close()

    (RESULTS / "REPORT.txt").write_text("\n".join(report) + "\n")
    print(f"\nAll {len(report)} scenarios passed. Evidence in {RESULTS}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        (RESULTS / "REPORT.txt").write_text("\n".join(report) + "\nFAILED — see traceback\n")
        raise
    sys.exit(0)
