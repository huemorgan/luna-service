"""040/004 — usage profiles and monthly cost projection.

A profile maps playbook item keys to a monthly frequency. Projection prices
the profile from a completed benchmark run's measured medians:

    monthly = Σ (median item credits × freq)
            + background idle scaled to 24h × days
            + hosting price

Money mapping: 1 credit = $0.01 face value = 10 000 micro-USD. Vendor $ comes
from the measured vendor_cost_micro_usd medians — real spend, not list price.
"""

from __future__ import annotations

from statistics import median

from cloud.billing.benchmark_playbook import BY_KEY

CREDIT_MICRO_USD = 10_000
BACKGROUND_ITEM = "background.idle"
DAYS_PER_MONTH = 30

# freq = actions per month; BACKGROUND_ITEM freq = days per month.
PRESET_PROFILES: dict[str, dict[str, int]] = {
    "light": {
        "chat.hello": 20,
        "chat.qa_short": 10,
        "memory.store": 5,
        BACKGROUND_ITEM: DAYS_PER_MONTH,
    },
    "regular": {
        "chat.hello": 30,
        "chat.qa_short": 30,
        "chat.multiturn_5": 8,
        "chat.generate_long": 4,
        "memory.store": 20,
        "memory.recall": 10,
        "web.search_summarize": 20,
        "files.summarize_doc": 6,
        "charts.render": 2,
        "imagegen.one": 4,
        "tasks.create_and_run": 4,
        "scheduler.task_fire": 1,
        BACKGROUND_ITEM: DAYS_PER_MONTH,
    },
    "heavy": {
        "chat.hello": 60,
        "chat.qa_short": 80,
        "chat.multiturn_5": 30,
        "chat.generate_long": 20,
        "chat.big_context": 10,
        "memory.store": 60,
        "memory.recall": 40,
        "recall.search": 20,
        "web.search_summarize": 60,
        "browser.session": 20,
        "files.summarize_doc": 20,
        "charts.render": 10,
        "htmlpage.generate": 4,
        "imagegen.one": 15,
        "playbooks.run": 10,
        "tasks.create_and_run": 15,
        "scheduler.task_fire": 4,
        "wiki.write": 10,
        BACKGROUND_ITEM: DAYS_PER_MONTH,
    },
}


def item_medians(steps: list) -> dict[str, dict[str, float]]:
    """Per item key: median credits / vendor / margin over succeeded steps."""
    by_key: dict[str, list] = {}
    for s in steps:
        if s.status == "succeeded" and not s.item_key.startswith("__"):
            by_key.setdefault(s.item_key, []).append(s)
    out: dict[str, dict[str, float]] = {}
    for key, group in by_key.items():
        out[key] = {
            "credits": median(s.credits for s in group),
            "vendor_cost_micro_usd": median(s.vendor_cost_micro_usd for s in group),
            "margin_micro_usd": median(s.margin_micro_usd for s in group),
            "samples": len(group),
        }
    return out


def item_stats(steps: list) -> list[dict]:
    """Per-action averages over a run's repetitions, most expensive first.

    Built for performance work as much as pricing: avg LLM requests and token
    volume per action are the levers agent optimization can move, credits are
    what the customer sees. Failed repetitions are excluded from the averages
    but counted, so a flaky action is visible instead of skewing the mean.
    """
    ok: dict[str, list] = {}
    failed: dict[str, int] = {}
    for s in steps:
        if s.item_key.startswith("__"):
            continue
        if s.status == "succeeded":
            ok.setdefault(s.item_key, []).append(s)
        elif s.status == "failed":
            failed[s.item_key] = failed.get(s.item_key, 0) + 1

    def _row(key: str, group: list) -> dict:
        n = len(group)
        avg = lambda vals: round(sum(v or 0 for v in vals) / n, 2) if n else 0.0  # noqa: E731
        return {
            "item_key": key,
            "samples": n,
            "failed": failed.get(key, 0),
            "avg_credits": avg(s.credits for s in group),
            "median_credits": median(s.credits or 0 for s in group) if n else 0,
            "avg_vendor_cost_micro_usd": avg(s.vendor_cost_micro_usd for s in group),
            "avg_llm_requests": avg(s.llm_requests for s in group),
            "avg_input_tokens": avg(s.input_tokens for s in group),
            "avg_output_tokens": avg(s.output_tokens for s in group),
            "avg_cache_read_tokens": avg(s.cache_read_tokens for s in group),
            "avg_cache_write_tokens": avg(s.cache_write_tokens for s in group),
            "avg_latency_ms": avg(s.latency_ms for s in group),
        }

    rows = [_row(key, group) for key, group in ok.items()]
    rows += [_row(key, []) for key in failed if key not in ok]
    rows.sort(key=lambda r: (-r["avg_credits"], r["item_key"]))
    return rows


def background_daily(steps: list) -> dict[str, float]:
    """Scale the idle window sample to a 24h day."""
    item = BY_KEY.get(BACKGROUND_ITEM)
    windows = [s for s in steps if s.item_key == BACKGROUND_ITEM and s.status == "succeeded"]
    # The synthetic __background__ bucket also counts: it is run noise that a
    # real deployment would produce continuously.
    noise = [s for s in steps if s.item_key == "__background__"]
    if not item or not (windows or noise):
        return {"credits": 0.0, "vendor_cost_micro_usd": 0.0}
    sampled_seconds = sum(
        max(1.0, (s.finished_at - s.started_at).total_seconds()) for s in windows + noise
    )
    credits = sum(s.credits for s in windows + noise)
    vendor = sum(s.vendor_cost_micro_usd for s in windows + noise)
    factor = 86_400.0 / sampled_seconds
    return {
        "credits": credits * factor,
        "vendor_cost_micro_usd": vendor * factor,
        "sampled_seconds": sampled_seconds,
    }


def project(
    steps: list,
    profile: dict[str, int],
    *,
    hosting_credits: int = 999,
) -> dict:
    """Monthly projection for a profile priced from a run's steps."""
    medians = item_medians(steps)
    bg_daily = background_daily(steps)

    per_item = []
    credits = 0.0
    vendor = 0.0
    margin = 0.0
    missing = []
    for key, freq in profile.items():
        if freq <= 0:
            continue
        if key == BACKGROUND_ITEM:
            c = bg_daily["credits"] * freq
            v = bg_daily["vendor_cost_micro_usd"] * freq
            per_item.append({"item_key": key, "freq": freq, "unit_credits": bg_daily["credits"],
                             "credits": c, "vendor_cost_micro_usd": v,
                             "note": "per-day idle burn scaled from the sampled window"})
            credits += c
            vendor += v
            continue
        m = medians.get(key)
        if m is None:
            missing.append(key)
            continue
        c = m["credits"] * freq
        v = m["vendor_cost_micro_usd"] * freq
        g = m["margin_micro_usd"] * freq
        per_item.append({"item_key": key, "freq": freq, "unit_credits": m["credits"],
                         "credits": c, "vendor_cost_micro_usd": v})
        credits += c
        vendor += v
        margin += g

    per_item.sort(key=lambda r: -r["credits"])
    metered_credits = credits
    total_credits = credits + hosting_credits
    return {
        "per_item": per_item,
        "missing_items": missing,  # in the profile but absent from this run
        "metered_credits": round(metered_credits, 1),
        "hosting_credits": hosting_credits,
        "monthly_credits": round(total_credits, 1),
        "monthly_revenue_micro_usd": int(total_credits * CREDIT_MICRO_USD),
        "monthly_vendor_micro_usd": int(vendor),
        "monthly_margin_micro_usd": int(margin),
        "background_daily": bg_daily,
    }
