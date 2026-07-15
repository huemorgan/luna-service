"""040/002 — the benchmark playbook catalog.

Fixed, versioned prompts for every action class users actually perform. The
catalog is the single place prompts live: benchmark tables store only item
keys, so a run is reproducible from (playbook_version, item_key) without any
conversation content in the database.

Coverage contract: every plugin in the current default image set and every
in-tree core plugin appears in COVERAGE — either exercised by an item or
explicitly marked a zero-LLM-cost path. `test_playbook_coverage` pins this.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PLAYBOOK_VERSION = "v2"

# Kinds the runner knows how to execute:
#   chat        — one fresh conversation, one message, wait for the reply
#   chat_multi  — one fresh conversation, several messages in order
#   api         — scripted Luna API reads (no agent turn); proves reads are free
#   window      — passive observation window (background burn), no input at all
KINDS = ("chat", "chat_multi", "api", "window")


@dataclass(frozen=True)
class PlaybookItem:
    key: str
    title: str
    category: str
    kind: str
    prompts: tuple[str, ...] = ()
    plugins: tuple[str, ...] = ()          # what this item exercises
    window_seconds: int = 0                # kind == 'window'
    scale_to_hours: float = 0.0            # window result is scaled to this span
    smoke: bool = False                    # part of the cheap default subset
    default_included: bool = True
    notes: str = ""


_LONG_DOC = (
    "Quarterly operations report. Revenue grew 14% quarter over quarter, "
    "driven primarily by the hosted tier. Churn held at 2.1%. Infrastructure "
    "spend rose 9% on GPU inference. Support ticket volume dropped 18% after "
    "the onboarding revamp. Hiring: two backend engineers started, one "
    "designer offer out. Risks: vendor API price changes announced for Q3, "
    "single-region deployment remains a resilience gap. Roadmap: usage-based "
    "billing GA, marketplace curation pass, EU region evaluation. "
) * 40  # ~2.3k words → a meaningfully large context


CATALOG: tuple[PlaybookItem, ...] = (
    # ── Baseline chat ────────────────────────────────────────────────────────
    PlaybookItem(
        key="chat.hello", title="Say hello", category="chat", kind="chat",
        prompts=("Say hello.",), smoke=True,
        plugins=("plugin_api", "plugin_webui", "plugin_brain", "plugin_memory"),
    ),
    PlaybookItem(
        key="chat.qa_short", title="Short factual Q&A", category="chat", kind="chat",
        prompts=("In one paragraph, why is the sky blue?",), smoke=True,
    ),
    PlaybookItem(
        key="chat.generate_long", title="Long-form generation", category="chat", kind="chat",
        prompts=("Write an ~800 word essay on how usage-based pricing changes "
                 "the incentives of software agents. Plain prose, no lists.",),
    ),
    PlaybookItem(
        key="chat.multiturn_5", title="Five-turn conversation", category="chat", kind="chat_multi",
        prompts=(
            "I'm planning a small dinner party for six people on Saturday.",
            "Two guests are vegetarian and one is gluten-free.",
            "Suggest a three-course menu that works for everyone.",
            "Swap the dessert for something chocolate-based.",
            "Great — give me the final menu and a shopping list.",
        ),
        smoke=True,
        notes="Context-growth cost: each turn re-reads the growing history.",
    ),
    PlaybookItem(
        key="chat.big_context", title="Question over a large pasted document",
        category="chat", kind="chat",
        prompts=(f"Here is a report:\n\n{_LONG_DOC}\n\nWhat are the three "
                 "biggest risks it mentions, in one line each?",),
        notes="Measures large-prompt economics incl. cache writes.",
    ),
    # ── Memory / knowledge ───────────────────────────────────────────────────
    PlaybookItem(
        key="memory.store", title="Tell the agent a fact", category="memory", kind="chat",
        prompts=("Remember this: my preferred airline is Windward Air and my "
                 "frequent flyer number is WW-4471.",),
        plugins=("plugin_memory", "plugin_brain"), smoke=True,
        notes="Auto-extraction is a hidden per-message LLM cost — visible in "
              "the trigger log as extra rows beyond the reply call.",
    ),
    PlaybookItem(
        key="memory.recall", title="Recall a stored fact", category="memory", kind="chat",
        prompts=("What's my frequent flyer number?",),
        plugins=("plugin_memory", "plugin-recall"),
    ),
    PlaybookItem(
        key="recall.search", title="Search recall/knowledge", category="memory", kind="chat",
        prompts=("Search your knowledge for anything about airlines and "
                 "summarize what you find in two lines.",),
        plugins=("plugin-recall",),
    ),
    PlaybookItem(
        key="wiki.write", title="Add a wiki note", category="memory", kind="chat",
        prompts=("Add a note to your wiki titled 'Benchmark' saying: cost "
                 "benchmarks run from the admin panel.",),
        plugins=("plugin-wiki",),
    ),
    # ── Tasks / scheduling / approvals ───────────────────────────────────────
    PlaybookItem(
        key="tasks.create_and_run", title="Create and run a task", category="tasks", kind="chat",
        prompts=("Create a task to draft a two-line status update about your "
                 "week, then do it now and show me the result.",),
        plugins=("plugin_tasks",),
    ),
    PlaybookItem(
        key="scheduler.task_fire", title="Schedule a task (creation cost)", category="tasks", kind="chat",
        prompts=("Schedule a daily reminder for 9am to review the inbox. "
                 "Confirm what you scheduled.",),
        plugins=("plugin-scheduler",),
        notes="Measures creation; recurring cost = per-fire × frequency, "
              "sampled by background.idle window when a fire lands in it.",
    ),
    PlaybookItem(
        key="approvals.roundtrip", title="Action requiring approval", category="tasks", kind="chat",
        prompts=("Try to perform an action that needs my approval (for example "
                 "sending an email), and tell me what you're waiting on.",),
        plugins=("plugin_approvals",), default_included=False,
        notes="Reply-side cost only in v1 — the approval click isn't automated.",
    ),
    PlaybookItem(
        key="playbooks.run", title="Store and run a playbook", category="tasks", kind="chat_multi",
        prompts=(
            "Save a playbook called 'greeting': reply with a one-line "
            "friendly greeting mentioning the weekday.",
            "Run the 'greeting' playbook now.",
        ),
        plugins=("plugin-playbooks",),
    ),
    PlaybookItem(
        key="playbooks.create_fib", title="Create a Fibonacci playbook",
        category="tasks", kind="chat",
        prompts=("Create and save a playbook called 'fibonacci': compute the "
                 "first 10 Fibonacci numbers and send each one as its own chat "
                 "message. Just save it — don't run it yet.",),
        plugins=("plugin-playbooks",),
        notes="Authoring cost in isolation. Pair with playbooks.run_fib.",
    ),
    PlaybookItem(
        key="playbooks.run_fib", title="Run the Fibonacci playbook",
        category="tasks", kind="chat",
        prompts=("Run the 'fibonacci' playbook now.",),
        plugins=("plugin-playbooks",),
        notes="Execution cost of a stored multi-message playbook. Needs "
              "playbooks.create_fib earlier in the same run (items run in "
              "the order selected).",
    ),
    # ── Web / browser ────────────────────────────────────────────────────────
    PlaybookItem(
        key="web.search_summarize", title="Web search + summary", category="web", kind="chat",
        prompts=("Look up the current population of Portugal and answer in "
                 "one sentence with the source.",),
        plugins=("plugin-web-access",), smoke=True,
    ),
    PlaybookItem(
        key="browser.session", title="Browser page extraction", category="web", kind="chat",
        prompts=("Open https://example.com and tell me the page's title and "
                 "first paragraph.",),
        plugins=("plugin-browser",),
    ),
    PlaybookItem(
        key="curiosity.tick", title="Curiosity prompt", category="web", kind="chat",
        prompts=("What's something you've been curious about lately? Look it "
                 "up briefly and share one insight.",),
        plugins=("plugin-curiosity",),
        notes="Foreground approximation; the autonomous tick is captured by "
              "background.idle.",
    ),
    # ── Files / artifacts / media ────────────────────────────────────────────
    PlaybookItem(
        key="files.summarize_doc", title="Write + read back a file", category="files", kind="chat",
        prompts=("Create a file called notes.txt containing a 10-line summary "
                 "of what usage-based billing means, then read it back and "
                 "give me the two most important lines.",),
        plugins=("plugin-files",),
    ),
    PlaybookItem(
        key="charts.render", title="Render a chart", category="files", kind="chat",
        prompts=("Chart this: Jan 120, Feb 150, Mar 90, Apr 210, May 260. "
                 "Monthly signups, bar chart.",),
        plugins=("plugin-charts",),
    ),
    PlaybookItem(
        key="htmlpage.generate", title="Generate an HTML page", category="files", kind="chat",
        prompts=("Make me a simple one-page site introducing a lemonade stand "
                 "called Sunny's. Keep it minimal.",),
        plugins=("plugin-html-page",),
    ),
    PlaybookItem(
        key="imagegen.one", title="Generate one image", category="files", kind="chat",
        prompts=("Generate a small image of a crescent moon over calm water.",),
        plugins=("plugin-image-gen",),
        notes="Non-LLM vendor cost (image API) — shows up as its own service "
              "rows in the trigger log.",
    ),
    PlaybookItem(
        key="imagegen.describe", title="Generate an image, then describe it",
        category="files", kind="chat_multi",
        prompts=(
            "Generate a small image of a red bicycle leaning against a brick wall.",
            "Now describe the image you just generated in detail — colors, "
            "composition, mood.",
        ),
        plugins=("plugin-image-gen",),
        notes="Adds vision-input economics on top of generation: the second "
              "turn feeds the image back into the model.",
    ),
    PlaybookItem(
        key="giphy.send", title="Send a gif", category="files", kind="chat",
        prompts=("Send me a gif that says 'well done'.",),
        plugins=("plugin-giphy",),
    ),
    # ── Integrations ─────────────────────────────────────────────────────────
    PlaybookItem(
        key="mcp.tool_call", title="MCP tool invocation", category="integrations", kind="chat",
        prompts=("Using your connected MCP tools, list what tools you have "
                 "available and call the most harmless one once.",),
        plugins=("plugin-mcp",), default_included=False,
        notes="Needs an MCP fixture connected; local bench wires one.",
    ),
    PlaybookItem(
        key="connectors.action", title="Connector (composio) action", category="integrations", kind="chat",
        prompts=("Check my inbox and tell me only how many unread emails I "
                 "have. Do not open or change anything.",),
        plugins=("plugin-connectors",), default_included=False,
        notes="External side effects — off by default; composio requests are "
              "billable non-LLM events.",
    ),
    PlaybookItem(
        key="tool.mock_roundtrip", title="Mock tool round-trip", category="integrations", kind="chat",
        prompts=("Use your mock tool once and report what it returned.",),
        plugins=("plugin_mock_tool",), default_included=False,
        notes="Local bench only: exercises the tool-call loop with zero "
              "external spend.",
    ),
    # ── Meta / API / background ──────────────────────────────────────────────
    PlaybookItem(
        key="meta.introspect", title="List enabled plugins", category="meta", kind="chat",
        prompts=("What plugins do you have enabled? Just list them briefly.",),
        plugins=("plugin_meta",), smoke=True,
    ),
    PlaybookItem(
        key="persona.t800", title="Full personality switch (T-800)",
        category="meta", kind="chat_multi",
        prompts=(
            "Change your personality completely: from now on you are terse, "
            "literal and machine-like — like the T-800. Acknowledge the change.",
            "Give me a plan for my Saturday morning.",
        ),
        plugins=("plugin_brain", "plugin_config"),
        notes="First turn measures the reconfiguration cost (memory/config "
              "writes it triggers), second a normal reply under the new "
              "persona — compare with chat.qa_short to see the persona tax.",
    ),
    PlaybookItem(
        key="onboarding.full", title="Onboarding conversation", category="meta", kind="chat_multi",
        prompts=(
            "Hi! I'm Roy, setting you up for the first time.",
            "Call yourself Scout. Keep replies short and practical.",
            "I mainly need help tracking tasks and summarizing documents.",
            "That's everything — wrap up the setup.",
        ),
        plugins=("plugin_onboarding",), default_included=False,
        notes="One-time cost; only meaningful on a fresh agent.",
    ),
    PlaybookItem(
        key="api.direct", title="Direct API reads", category="meta", kind="api",
        plugins=("plugin_api", "plugin_webui"), smoke=True,
        notes="Lists conversations and fetches messages — asserts reads "
              "produce zero billable events.",
    ),
    PlaybookItem(
        key="background.idle", title="Idle background burn", category="background", kind="window",
        window_seconds=900, scale_to_hours=24.0,
        plugins=("plugin_brain", "plugin_dojo_socialkit", "plugin_upgrade_awareness",
                 "plugin-curiosity", "plugin-scheduler"),
        notes="No input at all for the window; everything that fires lands in "
              "the trigger log and scales to a 24h estimate.",
    ),
)

BY_KEY: dict[str, PlaybookItem] = {i.key: i for i in CATALOG}
SMOKE_KEYS: tuple[str, ...] = tuple(i.key for i in CATALOG if i.smoke)
DEFAULT_KEYS: tuple[str, ...] = tuple(i.key for i in CATALOG if i.default_included)


# ── Plugin coverage contract ──────────────────────────────────────────────────

# In-tree core plugins (luna/plugins/*).
CORE_PLUGINS = (
    "plugin_api", "plugin_approvals", "plugin_brain", "plugin_config",
    "plugin_dojo_bridge", "plugin_dojo_socialkit", "plugin_identity",
    "plugin_marketplace", "plugin_memory", "plugin_meta", "plugin_mock_tool",
    "plugin_onboarding", "plugin_tasks", "plugin_upgrade_awareness",
    "plugin_vault", "plugin_webui",
)

# Current default image plugin set (marketplace).
MARKETPLACE_PLUGINS = (
    "plugin-recall", "plugin-mcp", "plugin-charts", "plugin-web-access",
    "plugin-connectors", "plugin-files", "plugin-browser", "plugin-html-page",
    "plugin-image-gen", "plugin-playbooks", "plugin-giphy", "plugin-curiosity",
    "plugin-wiki", "plugin-scheduler",
)

# Plugins with no per-use LLM/vendor cost of their own: infrastructure paths
# exercised implicitly by every item. Listed so coverage is provable, not
# assumed.
ZERO_COST_PLUGINS = {
    "plugin_config": "config plumbing — no runtime cost",
    "plugin_identity": "identity/auth plumbing — no runtime cost",
    "plugin_vault": "secret storage — no LLM calls",
    "plugin_marketplace": "install-time only",
    "plugin_dojo_bridge": "test harness bridge — dev only",
    "plugin_webui": "UI serving — covered by api.direct",
}


def coverage() -> dict[str, list[str]]:
    """plugin -> item keys exercising it ('(zero-cost path)' when implicit)."""
    cov: dict[str, list[str]] = {p: [] for p in CORE_PLUGINS + MARKETPLACE_PLUGINS}
    for item in CATALOG:
        for p in item.plugins:
            cov.setdefault(p, []).append(item.key)
    for p, why in ZERO_COST_PLUGINS.items():
        if not cov.get(p):
            cov[p] = [f"(zero-cost path: {why})"]
    return cov


def uncovered_plugins() -> list[str]:
    return sorted(p for p, items in coverage().items() if not items)
