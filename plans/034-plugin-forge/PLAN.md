# 034 — Plugin Forge

> Luna develops plugins for itself on a dedicated Fly machine, tests them end-to-end
> (including browser + dojo), and **publishes validated versions to the user's private
> marketplace** — where the normal install/upgrade/rollback machinery takes over.

---

## 1. Concept

The user's Luna runs on a constrained machine (1 CPU, low RAM). It cannot run a coding
agent, a test Luna instance, and a headless browser simultaneously. The Plugin Forge is a
**separate, beefy Fly machine** purpose-built for plugin development:

```
User's Luna                          Plugin Forge (Fly)                Private Marketplace
───────────                          ──────────────────                ───────────────────
"Build me a plugin                   ┌────────────────────────────┐
 that shows weather"  ──HTTP POST──► │  Coding Agent (Claude Code) │
                                     │  Luna test instance          │──publish──► weather 0.1.0
                                     │  Headless Playwright         │             (immutable,
                                     │  Plugin dev kit (docs/tmpl)  │              sha256, history)
                                     └────────────────────────────┘                    │
◄──────────────── install/upgrade via plugin_marketplace (existing trust gate) ────────┘
```

The LLM cost is the same regardless of where it runs — so running a proper coding agent
(Claude Code / Codex CLI) on a machine with 4 CPU + 4 GB RAM is free extra capability.

### 1.1 Design Principles

1. **Control plane stays thin.** luna-service only queues jobs, provisions/destroys
   machines, stores job records + workspace bundles, and serves status. All heavy state
   (workspace, test Luna, browser) lives on the disposable forge machine. Reuse the
   existing `LunaRuntime` protocol (`cloud/runtime/base.py`) — the forge is just another
   machine spec, not a new provisioning path.
2. **Expertise by context, not code.** The agent becomes a plugin expert purely through
   curated on-disk knowledge (docs, template, examples, AGENTS.md). Improving the forge =
   improving the dev kit, no orchestrator changes.
3. **Closed-loop verification.** The artifact is never delivered on "it compiles" — the
   agent must install it into a *real* Luna, exercise it via chat (and browser for UI),
   and produce an evidence-bearing test report. No evidence, no publish.
4. **Least privilege.** The forge machine gets only job-scoped credentials: a *metered
   gateway token* (per-job budget cap) for LLM calls, and a *publish token* scoped to the
   user's private marketplace. Never the raw Anthropic key, never user vault/DB/proxy
   secrets. Both revoked when the job ends.
5. **Ephemerality is the isolation model.** One machine per job, destroyed after
   delivery. Everything the untrusted LLM output touched dies with the machine.
6. **The marketplace IS the delivery channel.** The forge doesn't invent a delivery path
   — it publishes to the user's private marketplace (luna-marketplaces), and the user's
   Luna installs/upgrades through `plugin_marketplace` like any other plugin. Versioning,
   immutability, sha256 trust gate, history, yank, and rollback come from infra that
   already exists — we don't rebuild any of it.
7. **Honest trust boundaries.** A forge-built plugin is third-party code. Validation on
   publish is hygiene (structure, manifest, lint), not a security boundary — the boundary
   is the user's explicit approval before install, same as any marketplace plugin.
8. **The pod is disposable; the knowledge isn't.** Every job leaves a **workspace
   bundle** behind (full source + decision log + dojo tests). Iteration jobs seed from
   it, so plugin v0.3.0 is written by an agent that knows why v0.2.0 looks the way it
   does — even though the machine that wrote v0.2.0 is long gone.

---

## 2. Architecture

### 2.1 Forge Machine Spec

| Aspect | Value |
|--------|-------|
| Provider | Fly.io (same account as luna-agents app) |
| App name | `luna-forge` (separate from `luna-agents`) |
| Machine size | `performance-2x` (2 vCPU, 4 GB) or configurable |
| Lifecycle | Ephemeral per-job. Created on request, destroyed after delivery. |
| Region | Same as the requesting Luna, or `sjc` default |
| Image | Custom `luna-forge:latest` — see §2.3 |
| Volume | None (stateless). Workspace is tmpfs / job-scoped dir, seeded from the previous version's workspace bundle on iteration jobs (§4). |
| Network | Open outbound egress (PyPI/npm/GitHub need it; Fly has no easy egress allowlist — don't pretend otherwise). No inbound services exposed. Isolation comes from ephemerality + credential scoping, not network filtering. |

### 2.2 What Runs On the Forge Machine

1. **Coding Agent** — Claude Code (via `claude` CLI) or Codex CLI. Configured with:
   - The full plugin dev kit (`docs/`, `template/`, example plugins)
   - The `bootstrap-workspace.prompt.md` as system context
   - The `luna_sdk` package pre-installed
   - Access to a local Luna instance for live testing
   - On iteration jobs: the previous workspace bundle (source + `FORGE.md` decision log)

2. **Luna Test Instance** — A real Luna server (`luna serve --port 3000`) running on the
   same machine. The coding agent installs the plugin into this Luna and chats with it to
   verify tool behavior. Note: the test Luna's agent ALSO needs model access — it uses the
   same scoped gateway token as the coding agent, so all LLM spend for a job (coding +
   test chats) is metered under one job budget.

3. **Headless Playwright** — For plugins with UI components. The coding agent opens the
   Luna UI at `localhost:3000`, navigates to settings tabs, takes screenshots, validates
   visual output.

4. **Test Harness** — A thin orchestrator script that:
   - Receives the job spec (what to build, or what to change + the base bundle)
   - Boots the coding agent with the right context
   - Monitors progress, enforces a timeout
   - Collects the artifact + test report + workspace bundle
   - Publishes the version to the user's marketplace, uploads the bundle to the
     control plane

### 2.3 Forge Docker Image

```dockerfile
FROM python:3.12-slim

# Luna + SDK
COPY luna/ /opt/luna/
RUN cd /opt/luna && pip install -e ".[all]"

# Plugin dev kit (docs, template, examples)
COPY luna-plugins/docs/ /opt/dev-kit/docs/
COPY luna-plugins/template/ /opt/dev-kit/template/
COPY luna-plugins/plugins/ /opt/dev-kit/examples/

# Coding agent CLI (Claude Code is an npm package — needs node)
RUN apt-get update && apt-get install -y nodejs npm \
 && npm install -g @anthropic-ai/claude-code

# Playwright + headless Chrome
RUN pip install playwright && playwright install chromium --with-deps

# Marketplace publish CLI (luna-mp) — from the luna-marketplaces repo
RUN pip install /opt/tools/luna-mp

# Orchestrator
COPY forge/ /opt/forge/

ENTRYPOINT ["python", "/opt/forge/entrypoint.py"]
```

### 2.4 Knowledge Injection — Making the Agent Expert at Plugins

The forge coding agent is NOT a general-purpose coder. Its system prompt + workspace are
tailored so it's an expert Luna plugin developer:

**Pre-loaded knowledge (on disk, in its workspace):**

| Path | Content | Purpose |
|------|---------|---------|
| `/opt/dev-kit/docs/PLUGIN-ARCHITECTURE.md` | Full architecture doc | What a plugin IS |
| `/opt/dev-kit/docs/CREATING-A-PLUGIN.md` | Step-by-step creation | How to build one |
| `/opt/dev-kit/docs/UPDATING-A-PLUGIN.md` | Version bump process | How to iterate |
| `/opt/dev-kit/template/` | Starter plugin scaffold | Copy-and-rename base |
| `/opt/dev-kit/examples/plugin-render/` | Complex connector example | Routes, skills, vault |
| `/opt/dev-kit/examples/plugin-files/` | UI + routes example | Standalone file browser |
| `/opt/dev-kit/examples/plugin-giphy/` | Simple leaf example | Minimal tool plugin |
| `/workspace/AGENTS.md` | Forge-specific rules | Constraints, patterns |
| `/workspace/dojo-tests/` | Example dojo test scenarios | How to write + run tests |
| `/workspace/<plugin>/` | (iteration jobs only) previous source | The base to modify |
| `/workspace/<plugin>/FORGE.md` | (iteration jobs only) decision log | Why the code is the way it is |

**System prompt for the coding agent** (injected via `--system-prompt` or AGENTS.md):

```
You are a Luna Plugin Developer Agent. Your ONLY job is to develop, test, and deliver
Luna plugins.

You have:
- The full Luna Plugin Architecture docs in /opt/dev-kit/docs/
- A plugin template in /opt/dev-kit/template/
- Real working plugin examples in /opt/dev-kit/examples/
- A running Luna instance at localhost:3000 for live testing
- Playwright for browser-based UI testing
- On iteration jobs: the plugin's existing source and its FORGE.md decision log.
  READ FORGE.md FIRST — it tells you why past choices were made. Don't undo a
  decision without recording why.

Rules:
- Import luna_sdk ONLY. Never import luna.*.
- Keep luna-plugin.toml and PluginManifest in sync.
- Every tool gets an honest policy + risk_level.
- Test the plugin live: install into the running Luna, chat with the agent, verify
  the tool is called correctly and returns sensible results.
- For UI plugins: open localhost:3000 in the headless browser, navigate to the
  settings tab / UI page, take a screenshot, verify it renders.
- Write dojo-style test scenarios (markdown) documenting what you tested.
- On iteration jobs: RE-RUN the existing dojo scenarios too (regression), not just
  the new ones.
- Bump the version per the semver policy (§4.4) and APPEND an entry to FORGE.md:
  what was asked, what you decided, what you rejected and why, gotchas found.
- Package the plugin (single top-level dir zip) when done.

Your deliverable: the published plugin version + a test report (markdown with
screenshots) + the updated workspace bundle.
```

### 2.5 How the Dev→Test Loop Actually Runs

There is no mid-job prompting: the orchestrator launches Claude Code **once**, headless,
with the entire job as a single task (scaffold → implement → install into test Luna →
chat-test → screenshot → report → package). Install-and-test is part of the agent's
instructions, not a separate phase someone triggers:

1. **Install:** the agent (has bash) symlinks the plugin into the test Luna's plugins
   dir and restarts it (`luna serve` on localhost:3000).
2. **Chat-test:** it calls the test Luna's HTTP chat API directly (curl) — sends the
   trigger messages, then verifies in the response/logs that the tool was invoked with
   the right args and returned sensible output.
3. **UI test:** drives Playwright against localhost:3000, screenshots.

The orchestrator is a dumb supervisor with **acceptance gates**: when the agent reports
done, it verifies the deliverables exist and are non-trivial (zip present, test report
present and shows scenarios that ran, regression scenarios re-run on iterate jobs). If a
gate fails, it re-prompts the agent once with what's missing ("continue — report shows no
negative test"), then fails the job. No evidence, no publish (§1.1 principle 3).

### 2.6 Dojo Testing on the Forge

The forge replicates how Luna plugins are tested in the real dojo:

1. **Install the plugin** into the running Luna (symlink into plugins dir, restart)
2. **Chat with the agent** — send messages that should trigger the tool, verify it works
3. **Screenshot the UI** — if the plugin has a settings tab or standalone UI
4. **Write a test report** — structured markdown:

```markdown
# Plugin Test Report: weather

## Tools Tested
| Tool | Input | Expected | Actual | Pass |
|------|-------|----------|--------|------|
| get_weather | city="London" | temp + conditions | {"temp_c": 15, "conditions": "overcast"} | YES |
| get_weather | city="" | error or default | {"error": "city required"} | YES |

## Agent Behavior
- Asked "what's the weather in Paris?" → agent called get_weather(city="Paris") ✓
- Response was natural language, not raw JSON ✓

## UI (if applicable)
- Settings tab renders at /api/p/weather/ui/settings/ ✓
- Screenshot: [attached]

## Regression (iteration jobs)
- 01-basic-weather-query.md — still passing ✓
- 02-invalid-city-handling.md — still passing ✓

## Dojo Scenarios Written
- 03-wind-speed.md
```

---

## 3. Delivery — Through the Marketplace

The forge does NOT deliver artifacts directly to the user's Luna. It **publishes to the
user's private marketplace** on luna-marketplaces, and the user's Luna consumes it through
the existing `plugin_marketplace` plugin. No bespoke delivery channel exists.

### 3.1 Per-User Private Marketplace — Setup Is a Prerequisite, Not a Side Effect

The forge does NOT lazily provision a marketplace on the first job — that couples a slow,
failure-prone setup step to a user request ("build me X" should never fail because org
creation hiccuped). Instead:

- **Setup happens before the first request**, as an explicit action: the user provisions
  a **private marketplace** on the luna-marketplaces service (org per user maps to the
  existing accounts/orgs model; slug e.g. `{user}-forge`) — via the luna-service
  dashboard, or driven by their Luna as a guided setup step. Pointing the forge at an
  existing marketplace the user already operates is equally valid.
- The marketplace is added to the user's Luna as a source through the existing
  `marketplace_url` gateway-env plumbing (`cloud/api/plugin_catalog_routes.py` /
  `gateway_env_delta`), and access uses the marketplace service's existing token auth.
- **Until then, the forge is "not set up."** `forge_develop`/`forge_iterate` return a
  clear state — *"Plugin Forge isn't set up yet: no target marketplace is configured.
  Set one up in the dashboard (or ask me to walk you through it)."* — and the job API
  rejects creation with `412 Precondition Failed`.

Setup is one-time, verifiable in isolation (marketplace reachable, token valid, source
wired into the Luna), and every subsequent job starts from a known-good state.

### 3.2 What the Marketplace Gives Us For Free

| Concern | Solved by existing luna-marketplaces infra |
|---------|--------------------------------------------|
| Versioning | `PluginVersion` rows; **immutable** — same version can never be overwritten (409 on republish) |
| Version history | Full history per plugin, `published_at`, manifest snapshot per version |
| Rollback | Install an earlier version from history (needs one small Luna CR — §4.5) |
| Bad release | `yanked` flag — hide a version without deleting history |
| Artifact integrity | Content-addressed storage; `sha256` in index MUST match artifact bytes — **Luna's loader refuses to load on mismatch** (the existing trust gate) |
| Install/upgrade UX | `plugin_marketplace` agent tools: search, install (`highest_compatible`), upgrade — all approval-gated by the owner |
| Publish auth | Publisher-role tokens per marketplace |
| Metering | `usage_events` (publishes, downloads) from day one |
| Browsing | Catalog UI — the user can see "my plugins", readme, version history, permissions summary |

### 3.3 Publish Flow

1. Forge finishes testing → packages the zip.
2. Orchestrator publishes via the marketplace API
   (`POST /marketplaces/{user-slug}/publish`) using the job-scoped publish token.
   Server-side validation (manifest, semver, SDK-import lint) runs there — a second,
   independent hygiene gate.
3. Orchestrator uploads the workspace bundle + test report to the control plane.
4. Job status → `done`, with `published_version` on the job record.
5. The user-side `plugin-forge` plugin (§6) sees `done` and nudges the normal
   install/upgrade flow: *"weather 0.2.0 passed its tests [report summary]. Install?"* —
   the user approves through the same consent UX as any marketplace plugin.

The forge never gets a route into a user's Luna, and the user's Luna never trusts a
forge-specific channel — it trusts its marketplace, which it already trusted.

---

## 4. Iteration, Versioning & Memory

The forge machine dies after every job — but plugin development is iterative ("now make
it also show wind speed"). The context that produced version N must survive to inform
version N+1.

### 4.1 The Workspace Bundle

Every successful job uploads a **workspace bundle** to control-plane object storage,
keyed by `forge/bundles/{agent_id}/{plugin_name}/{version}.tar.gz`:

```
weather/
├── weather/                  # full plugin source (not just the zip)
│   ├── luna-plugin.toml
│   └── ...
├── FORGE.md                  # the decision log (see §4.2)
├── dojo-tests/               # all scenarios written so far (accumulates)
│   ├── 01-basic-weather-query.md
│   ├── 02-invalid-city-handling.md
│   └── 03-wind-speed.md
└── test-report.md            # report for THIS version
```

An iteration job seeds its workspace from the bundle of the **version the user currently
has installed** (not blindly the latest — if the user rolled back from 0.3.0 to 0.2.0 and
asks for a change, the base is 0.2.0; the job then bumps PAST the highest published
version, e.g. to 0.4.0, since marketplace versions are immutable).

### 4.2 FORGE.md — The Residual Decision Log

An append-only, per-plugin log the coding agent MUST read before changing anything and
MUST extend before finishing. One entry per iteration:

```markdown
## 0.2.0 — 2026-07-03 — "also show wind speed"
**Request:** add wind speed to get_weather output.
**Decisions:**
- Used OpenWeather's same endpoint (`wind.speed` field) — no second API call needed.
- Convert m/s → km/h at the tool boundary; API is metric-m/s, users expect km/h.
**Rejected:**
- Caching responses (user asked for current weather; staleness > savings at this volume).
**Gotchas:**
- API returns wind in m/s even with units=metric — only temp respects the units param.
**Tests:** added 03-wind-speed.md; re-ran 01, 02 (green).
```

This is the "who wrote this and why" that normally lives in a developer's head. It makes
iteration N+1 coherent with N, prevents decision thrash (agent undoing a prior deliberate
choice), and doubles as human-readable provenance the user can inspect.

### 4.3 Iteration Job Flow

```
1. User: "make the weather plugin also show wind speed"
2. Luna: calls forge_iterate(name="weather", change="also show wind speed")
   → POST /api/forge/jobs  {kind: "iterate", base_plugin: "weather",
                            base_version: "<installed version>"}
3. Control plane: provisions forge machine; job spec includes a download URL for the
   base workspace bundle
4. Forge: seeds /workspace/weather/ from the bundle, agent reads FORGE.md,
   makes the change, RE-RUNS existing dojo scenarios (regression) + writes new ones
5. Forge: bumps version (§4.4), appends FORGE.md entry, publishes 0.2.0 to the
   user's marketplace, uploads the new bundle
6. User's Luna: "weather 0.2.0 is ready (wind speed added, all 3 tests green).
   Upgrade?" → approval → plugin_marketplace upgrade
```

### 4.4 Semver Policy (agent-applied, orchestrator-enforced)

| Change | Bump |
|--------|------|
| Bug fix, no manifest change | patch |
| New capability (tool, field, UI element) | minor |
| Removed/renamed tool, changed tool contract, new required config/vault key | major (pre-1.0: minor, flagged loudly in the report) |

The orchestrator enforces: new version > highest published version for that plugin
(marketplace rejects duplicates anyway — 409, immutable).

### 4.5 Rollback

- **Mechanism:** every published version stays installable (immutable history). Rollback
  = install version N-1 from the private marketplace.
- **Luna CR needed (small):** `plugin_marketplace` currently exposes install
  (highest-compatible) and upgrade. Add **`install specific version` / downgrade**
  (`plugin_marketplace_rollback(name, version?)` — default: previous installed version).
  Owner-approval-gated like upgrade. This is the one missing piece; everything else
  exists.
- **Bad version:** the user (or the forge, on a failed regression discovered later) can
  **yank** a version — it disappears from resolution but stays in history for audit.
- The user-side plugin records `previous_version` at each upgrade so "roll it back" is a
  one-step chat command.

### 4.6 Future (v2): Git Repo Per Plugin

Bundles-in-object-storage is deliberately simple. If plugins grow long histories, promote
each plugin to a real git repo (the marketplace `Plugin.source_url` field already exists
to point at it) — full diff history, and FORGE.md becomes the commit-message discipline.
Not needed for v1.

---

## 5. API Design

### 5.1 Forge Job Endpoint (luna-service control plane)

```
POST /api/forge/jobs
Authorization: Bearer <user-session-token>
```

```json
{
  "kind": "new",                    // "new" | "iterate"
  "description": "A plugin that shows current weather for any city using OpenWeatherMap API",
  "name_hint": "weather",           // iterate: "base_plugin": "weather", "base_version": "0.1.0"
  "requirements": [
    "Tool: get_weather(city) -> {temp_c, conditions, humidity}",
    "Auto-approve, low risk (read-only API call)",
    "Needs an API key stored in vault"
  ],
  "ui_required": false,
  "timeout_minutes": 30
}
```

No `callback_url` in the request — accepting a caller-supplied URL the platform later
POSTs to is an SSRF vector. The requesting agent is identified from the bearer token;
delivery is via the marketplace (§3).

Returns `412 Precondition Failed` if the requester has no target marketplace configured
(§3.1) — the forge must be set up before the first job.

Response:
```json
{
  "job_id": "forge-abc123",
  "status": "provisioning",
  "machine_id": "fly-machine-xyz",
  "estimated_minutes": 10
}
```

### 5.2 Job Status / Report

```
GET /api/forge/jobs/{job_id}
```

```json
{
  "job_id": "forge-abc123",
  "status": "testing",  // provisioning | coding | testing | packaging | publishing | done | failed
  "progress": "Running dojo test 2/3",
  "started_at": "2026-07-01T17:00:00Z",
  "elapsed_minutes": 4,
  "published_version": null   // set on done, e.g. "0.2.0"
}
```

```
GET /api/forge/jobs/{job_id}/report   — test report + screenshots (requester or admin)
```

No artifact endpoints — the artifact lives in the marketplace, fetched through the
existing trust gate.

### 5.3 Forge Machine Internal API

The orchestrator on the forge machine exposes a local-only API for job management:

```
POST /job/start    — receives job spec (+ base bundle URL on iterate), kicks off the agent
GET  /job/status   — returns current phase + progress
POST /job/cancel   — kills the coding agent, cleans up
GET  /job/report   — returns the test report markdown
```

---

## 6. The Luna Plugin (user-side)

A thin plugin installed on the user's Luna that provides the "develop a plugin" capability.

### 6.0 Where It Lives

Source is developed and versioned **in this repo**, under a new top-level `plugins/`
folder for plugins that luna-service itself ships:

```
luna-service/
├── cloud/          # control plane
├── plugins/        # ← plugins WE develop for the platform
│   └── plugin-forge/
└── ...
```

Distribution to user Lunas follows the same channel as everything else — published to a
marketplace (the platform/official one, not the per-user forge marketplaces) and
preinstalled/installed via the existing plugin catalog plumbing. `plugins/` is the source
of truth; the marketplace is the delivery mechanism. Future platform plugins land in the
same folder.

```toml
name = "plugin-forge"
version = "0.1.0"
description = "Develop and iterate on Luna plugins via a dedicated coding machine."
entry = "plugin_forge"
sdk_version = "0"
tags = ["meta", "development"]

[requires]
tools = 4

[[tools]]
name = "forge_develop"
description = "Request development of a new Luna plugin."
policy = "ask"
risk_level = "medium"

[[tools]]
name = "forge_iterate"
description = "Request a change to a forge-built plugin (new version)."
policy = "ask"
risk_level = "medium"

[[tools]]
name = "forge_status"
description = "Check the status of a plugin development job."
policy = "auto_approve"
risk_level = "low"

[[tools]]
name = "forge_history"
description = "Show version history + decision log for a forge-built plugin."
policy = "auto_approve"
risk_level = "low"
```

### 6.2 Tools

All job-creating tools check setup state first (§3.1): if no target marketplace is
configured, they don't attempt the job — they tell the user the forge isn't set up and
offer the setup flow.

**`forge_develop`** — The agent calls this when the user asks for a new capability
that doesn't exist as a plugin yet. Takes the natural-language description, posts to the
forge API, returns a job ID.

**`forge_iterate`** — "Change/improve plugin X." Posts an iterate job with the
currently-installed version as the base (§4.3).

**`forge_status`** — Check progress of an active forge job.

**`forge_history`** — Surfaces the marketplace version history + FORGE.md entries
so the user can ask "what changed in 0.2.0?" or "why does it convert to km/h?".

Install/upgrade/rollback themselves are NOT this plugin's job — they belong to
`plugin_marketplace` (including the rollback CR, §4.5).

### 6.3 Delivery Watch (poll + nudge)

```python
# background task started by forge_develop / forge_iterate
async def watch_job(job_id: str):
    # Poll GET /api/forge/jobs/{job_id} until done/failed (backoff, respect timeout)
    # On done: the new version is already in the user's private marketplace
    # Nudge in chat with the test-report summary:
    #   "weather 0.2.0 passed its tests (3/3 green). Install it?"
    # On approval: hand off to plugin_marketplace install/upgrade —
    #   sha256 trust gate + owner approval, same as any plugin
    # Record previous_version for one-step rollback
```

The user-approval step is the actual trust boundary (§1.1 principle 7) — same consent
model as installing any marketplace plugin.

### 6.4 Keeping the Requesting Luna Alive

The watcher lives inside the user's Luna — if that machine sleeps or restarts mid-job,
the nudge never arrives. Three layers:

1. **Keep-alive pin (primary):** while an agent has an active forge job, the control
   plane pins its machine awake — any stop/suspend path (cost-saving sleep, dashboard
   stop) checks for active `forge_jobs` and defers. Agent machines already run with
   `autostop: "off"`, so Fly itself won't idle-kill them; the pin covers our own
   lifecycle actions.
2. **Wake on completion (fallback):** when a job finishes and the requesting agent's
   machine is `stopped`/`suspended` anyway (crash, manual stop), the control plane
   starts it via the existing runtime `start()` — the watcher resumes and delivers the
   nudge.
3. **Watcher survives restarts:** active job IDs are persisted in the plugin's state, and
   `on_load` re-spawns watchers for any still-active jobs — a Luna reboot mid-job picks
   up where it left off.

---

## 7. Security

### 7.1 Isolation

| Concern | Mitigation |
|---------|-----------|
| Forge code runs untrusted LLM output | Forge machine is ephemeral, destroyed after each job. No persistent state. |
| Network access | No inbound ports. Outbound is open (deps need it) — accept this; the machine holds nothing worth exfiltrating beyond its own job-scoped tokens. |
| Secrets | Exactly two job-scoped credentials: (1) a budget-capped **gateway token** (Claude Code pointed at the gateway via `ANTHROPIC_BASE_URL`) — never the raw Anthropic key; (2) a **marketplace publish token** scoped to the user's private marketplace only. Both revoked when the job ends. Never user vault keys, DB credentials, or proxy secrets. |
| LLM spend | Metered through the existing gateway per job → per user. Hard budget cap kills runaway agents. |
| Publish blast radius | Publish token can only write to the requester's own private marketplace — a hijacked forge job cannot publish to anyone else's marketplace or the official catalog. Versions are immutable, so it also can't overwrite an existing good version. |
| Artifact trust | The marketplace sha256 trust gate: Luna's loader refuses any artifact whose hash doesn't match the signed index. Trust for *content* comes from user approval before install. |
| Delivery auth | No forge→Luna path exists. Luna pulls from its marketplace over the channel it already trusts. |
| Resource limits | Machine has a hard timeout (default 30 min). Job killed + machine destroyed on timeout. A control-plane reaper destroys machines whose `last_heartbeat_at` goes stale (orchestrator crash, control-plane restart). |
| User isolation | Each forge job runs on a SEPARATE machine. No shared state between jobs from different users. Workspace bundles are keyed per agent and served only to their owner. |

### 7.2 What the Forge Machine CANNOT access

- User's Luna database
- User's vault keys
- Other users' forge jobs, bundles, or marketplaces
- The luna-service control plane DB
- Any internal Fly network services

### 7.3 Validation Before Install (on the receiving Luna)

1. The marketplace publish API already validated manifest, semver, and SDK-import lint
   at publish time (server-side, independent of the forge)
2. Luna's loader verifies sha256 against the marketplace index (existing trust gate;
   refuses on mismatch)
3. Lint on the forge + at publish: static scan for `import luna.` / `from luna ` — a
   **quality gate, not a security boundary** (trivially bypassed via `importlib`; an
   installed plugin runs with full Luna-process privileges regardless)
4. Present to the user for approval: name, tools with policy/risk levels, test report
5. Install and load — if `on_load` raises, uninstall and report failure (previous
   version remains one rollback away)

---

## 8. Flow (End to End)

### New plugin

```
0. Prerequisite (one-time): forge is set up — private marketplace provisioned,
   wired into the Luna as a source, publish access verified (§3.1).
   If not: Luna answers "the forge isn't set up yet" and offers the setup flow.
1. User: "I wish I could check the weather in our chat"
2. Luna (agent): "I don't have a weather tool, but I can build one for you.
   Shall I develop a weather plugin?"
3. User: "Yes"
4. Luna: calls forge_develop(description="...", requirements=[...])
   → POST /api/forge/jobs
5. Control plane: verifies the target marketplace is configured (412 otherwise);
   issues job-scoped gateway + publish tokens; provisions a Forge Fly machine
6. Forge machine boots:
   a. Starts Luna test instance (localhost:3000)
   b. Launches Claude Code with the job spec + plugin dev kit context
   c. Claude Code: scaffolds from template, writes code, installs into test Luna
   d. Claude Code: chats with test Luna to verify tool works
   e. Claude Code: takes screenshots if UI is involved
   f. Claude Code: writes dojo test scenarios + FORGE.md + test report
   g. Claude Code: packages the plugin zip
7. Orchestrator: publishes weather 0.1.0 to the user's private marketplace;
   uploads workspace bundle + report to the control plane; job → done
8. Forge machine: destroyed; job tokens revoked
9. User's Luna (watcher): "The weather plugin is built and passed its tests
   [report summary]. Install it?" → user approves → plugin_marketplace install
   (sha256 gate) → reload
10. User's Luna: "Done! Try asking me about the weather."
```

### Iteration

```
1. User: "great — can it also show wind speed?"
2. Luna: forge_iterate("weather", "also show wind speed")
3. Forge job seeds from the 0.1.0 bundle, reads FORGE.md, makes the change,
   re-runs old dojo tests + new ones, publishes 0.2.0, uploads new bundle
4. Luna: "weather 0.2.0 ready (wind speed added, 3/3 tests green). Upgrade?"
5. Later — "actually I liked it better before": plugin_marketplace rollback
   → reinstall 0.1.0 from history. Optionally yank 0.2.0.
```

---

## 9. Cost Model

| Component | Cost |
|-----------|------|
| Fly machine (performance-2x, 10–30 min) | ~$0.01–0.03 per job |
| LLM (Claude Code dev loop + test-Luna chats, metered via gateway) | ~$2–10 per job — a full build/install/chat-test/screenshot/iterate loop burns real tokens; budget-cap at ~$10. Iteration jobs are cheaper (smaller diff, seeded context). |
| Object storage (artifact + workspace bundle, ~1 MB) | Negligible |
| Marketplace hosting | Existing luna-marketplaces service (Render) — marginal cost ~0 |
| **Total per plugin version** | **~$2–10 (new), less for iterations** |

The user's Luna instance pays nothing extra — it's just making one HTTP call and polling.
All compute cost is on the forge machine.

---

## 10. Implementation Phases

### Phase A: Forge Infrastructure
- [ ] Create `luna-forge` Fly app
- [ ] Build forge Docker image (Luna + Playwright + Claude Code CLI + luna-mp)
- [ ] Write the orchestrator script (`forge/entrypoint.py`)
- [ ] Test manually: spin up machine, run a plugin dev job, get a zip + report

### Phase B: Control Plane (minimal)
- [ ] Add `/api/forge/jobs` endpoints to luna-service (create, status, report)
- [ ] Per-job gateway token issue/revoke + budget cap (reuse `gateway/tokens.py` pattern)
- [ ] Machine lifecycle via existing `LunaRuntime`/Fly runtime: provision → monitor →
      destroy on completion/timeout; heartbeat reaper for orphans
- [ ] DB schema: `forge_jobs`, `forge_machines`, `forge_logs` (§12.5)
- [ ] Workspace-bundle + report storage (Tigris or R2), private, served only through the API
- [ ] Minimal dashboard: jobs list (status, requester, duration, version/report links)
      + job detail with logs

### Phase C: Marketplace Delivery
- [ ] Explicit forge-setup flow (pre-first-job): provision a private marketplace per user
      on luna-marketplaces (org mapping, slug scheme, token auth) — dashboard action
      and/or Luna-guided; support linking an existing marketplace instead
- [ ] Setup verification: marketplace reachable, publish token valid, source wired into
      the agent's `marketplace_url`
- [ ] "Not set up" state: 412 from `POST /api/forge/jobs`; plugin-forge surfaces the
      setup path in chat instead of failing mid-request
- [ ] Job-scoped publish tokens (issue at job start, revoke at end; scoped to the one
      marketplace)
- [ ] Forge orchestrator publishes via the marketplace API; handle publish-side
      validation failures as job failures with a useful error
- [ ] Wire the private marketplace into the agent's `marketplace_url` sources
      (existing `plugin_catalog_routes` / gateway env delta plumbing)
- [ ] E2E: forge job → version visible in the user's marketplace → installable from the
      user's Luna through `plugin_marketplace` with the sha256 gate

### Phase D: Luna Plugin (user-side)
- [ ] Create `plugins/` top-level folder in luna-service (home for platform-shipped plugins)
- [ ] Write `plugin-forge` there (develop / iterate / status / history tools + job watcher)
- [ ] Publish/preinstall path for platform plugins (official marketplace + catalog plumbing)
- [ ] Install/upgrade nudge flow handing off to `plugin_marketplace` (approval-gated)
- [ ] Record `previous_version` on upgrade (rollback bookkeeping)
- [ ] Requesting-Luna liveness (§6.4): keep-alive pin during active jobs, wake-on-complete
      fallback, watcher re-spawn in `on_load` from persisted job IDs
- [ ] **Luna CR: `plugin_marketplace` install-specific-version / rollback tool** (§4.5)

### Phase E: Iteration & Memory
- [ ] Workspace bundle format + upload/download endpoints (keyed per agent+plugin+version)
- [ ] `kind: "iterate"` jobs: seed workspace from the installed version's bundle
- [ ] FORGE.md discipline in the forge AGENTS.md (read-first, append-before-finish)
- [ ] Regression policy: iterate jobs must re-run prior dojo scenarios
- [ ] Semver bump enforcement in the orchestrator (> highest published)
- [ ] E2E: build 0.1.0 → iterate to 0.2.0 → rollback to 0.1.0 → iterate again → 0.3.0
      seeded from 0.1.0's bundle

### Phase F: Knowledge & Testing Quality
- [ ] Curate the dev-kit snapshot (which examples to include, how much context)
- [ ] Write the forge AGENTS.md (rules for the coding agent)
- [ ] Build dojo test template library (so the forge knows how to write good tests)
- [ ] Test complex plugins: routes, settings UI, vault dependencies

### Phase G: Production Hardening
- [ ] Rate limiting (max concurrent forge jobs per user)
- [ ] Cost tracking + billing integration (gateway metering already gives per-job spend)
- [ ] Retry logic (if coding agent fails, try once more with a different approach)
- [ ] Monitoring / alerting on stuck jobs
- [ ] User can cancel in-progress jobs

### Phase H (v2): Fleet Platform — see §12
- [ ] Warm pool (only if cold-start latency proves to be a real complaint — a user who
      just agreed to wait ~10 min for a plugin build doesn't feel 60s of boot)
- [ ] Code-Pods left-pane section, pod list/detail pages, pool settings UI
- [ ] Image management UI (versions, set active, trigger build)
- [ ] Git repo per plugin (§4.6); publish-to-official-catalog workflow (curation via the
      marketplace's existing reviewer flow)

---

## 11. Coding Agent Choice

| Agent | Pros | Cons |
|-------|------|------|
| Claude Code CLI | Best at complex code, native tool use, can run bash | Requires Anthropic key, pricier per token |
| Codex CLI (OpenAI) | Fast, good at boilerplate | Less nuanced at architecture decisions |
| Aider | Open source, multi-model | Less polished orchestration |

**Recommendation: Claude Code CLI.** Luna's plugin architecture is nuanced (luna_sdk only,
manifest sync, policy/risk, vault deps). Claude handles these constraints best when given
the full docs as context. The extra cost per token is negligible relative to the value of
a correctly-built plugin.

---

## 12. Luna-Service UI — Forge Management

> **Scope note:** §12.5 (schema) and the jobs list/detail are Phase B. Everything else
> here — warm pool, image-management UI, pod pages — is **v2 (Phase H)**. The MVP is an
> ephemeral per-job runner (§2.1); a managed pod fleet is a different product and
> shouldn't gate delivery. Naming is unified on **forge** (`forge_jobs`, `/api/forge/*`)
> — one name end to end.

The control plane dashboard eventually gets a **Forge** section in the left pane (same
pattern as the existing Agents list): images, lifecycle, pool, active jobs, and history.

### 12.1 Left Pane Entry

```
┌─────────────────┐
│  Dashboard      │
│  Agents         │
│  Forge      ◄── │  new section
│  Settings       │
└─────────────────┘
```

### 12.2 Forge Image Management (Git-Driven) — v2

Same strategy as Luna agent images — the forge image lives in a Git repo, gets built and
pushed to the Fly registry, and is versioned:

| Aspect | Detail |
|--------|--------|
| Repo | `huemorgan/luna-forge` (or a directory in this repo: `forge/`) |
| Dockerfile | Contains Luna + SDK + Playwright + Claude Code CLI + orchestrator |
| Build | GitHub Actions → `registry.fly.io/luna-forge:<tag>` |
| Version tags | Semver (`0.1.0`, `0.2.0`) + `latest` |
| Pull in UI | "Forge Images" sub-tab shows available versions, lets you set the active image |

### 12.3 Warm Pool — v2

To avoid cold-start latency (~30–60s to boot a machine), keep a configurable pool of
**pre-warmed idle machines** ready to accept jobs immediately:

| Setting | Default | Description |
|---------|---------|-------------|
| `pool_size` | 1 | Number of idle warm machines to keep alive |
| `pool_region` | `sjc` | Region for warm machines |
| `pool_max_idle_minutes` | 30 | Destroy idle machines after this (cost cap) |
| `pool_image` | `latest` | Which image tag warm machines run |

### 12.4 Jobs List & History — Phase B (minimal) / v2 (full)

| Column | Content |
|--------|---------|
| Job ID | Link to detail (logs, report) |
| Plugin | Name + version published |
| Kind | new / iterate |
| Requested by | Agent slug |
| Status | `success` / `failed` / `cancelled` / `timeout` |
| Duration | Total time |
| Version | Link to the marketplace plugin page |
| Report | Test report link |
| Date | When it ran |

### 12.5 Database Schema

```sql
CREATE TABLE forge_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL,             -- which user's agent requested this
    kind TEXT NOT NULL DEFAULT 'new',   -- new | iterate
    description TEXT NOT NULL,
    plugin_name TEXT,
    base_version TEXT,                  -- iterate: the bundle we seeded from
    published_version TEXT,             -- set on success
    status TEXT NOT NULL DEFAULT 'queued',
        -- queued | provisioning | coding | testing | packaging | publishing
        -- | done | failed | cancelled | timeout
    progress TEXT,                       -- free-form status line from orchestrator
    bundle_key TEXT,                     -- object-storage key of the workspace bundle
    test_report TEXT,
    gateway_token_id UUID,               -- per-job scoped token, revoked on completion
    publish_token_id UUID,               -- per-job marketplace token, revoked on completion
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    error TEXT                           -- failure reason if failed
);

CREATE TABLE forge_machines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id TEXT UNIQUE,             -- Fly machine ID
    region TEXT NOT NULL DEFAULT 'sjc',
    image_tag TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'provisioning',
        -- provisioning | warm | active | destroying | destroyed
        -- ('warm' unused until Phase H pool)
    job_id UUID REFERENCES forge_jobs(id),  -- one-way FK; no back-ref on the job
                                            -- (avoids a circular FK)
    created_at TIMESTAMPTZ DEFAULT now(),
    last_heartbeat_at TIMESTAMPTZ,      -- reaper destroys machines with stale heartbeats
    destroyed_at TIMESTAMPTZ
);

CREATE TABLE forge_logs (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES forge_jobs(id),
    timestamp TIMESTAMPTZ DEFAULT now(),
    level TEXT DEFAULT 'info',          -- info | warn | error | debug
    phase TEXT,                          -- provisioning | coding | testing | packaging | publishing
    message TEXT NOT NULL
);

-- Phase H only:
CREATE TABLE forge_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tag TEXT NOT NULL UNIQUE,           -- "0.1.0", "latest"
    registry_url TEXT NOT NULL,         -- "registry.fly.io/luna-forge:0.1.0"
    git_sha TEXT,                       -- commit that built it
    created_at TIMESTAMPTZ DEFAULT now(),
    is_active BOOLEAN DEFAULT false     -- the currently deployed version
);
```

### 12.6 API Endpoints (Control Plane)

```
# Phase B
GET    /api/forge/jobs             — list jobs (filterable by status, agent)
GET    /api/forge/jobs/:id         — job detail (status, progress, published_version)
GET    /api/forge/jobs/:id/report  — test report + screenshots
POST   /api/forge/jobs/:id/cancel  — cancel a running job

# Phase E
GET    /api/forge/bundles/:plugin/:version — workspace bundle (forge machines + owner only)

# Phase H
GET    /api/forge/machines         — list machines (state, current job)
GET    /api/forge/machines/:id     — machine detail + logs
DELETE /api/forge/machines/:id     — force-destroy
POST   /api/forge/pool             — update pool settings
GET    /api/forge/images           — list available image tags
POST   /api/forge/images/build     — trigger a new image build
PATCH  /api/forge/images/:tag      — set as active
```

### 12.7 Log Streaming

The orchestrator on each forge machine sends structured log lines back to the control
plane via a persistent SSE connection (or periodic POST batches):

```json
{"timestamp": "...", "level": "info", "phase": "coding", "message": "Scaffolded plugin-weather from template"}
{"timestamp": "...", "level": "info", "phase": "testing", "message": "Luna restarted with plugin loaded"}
{"timestamp": "...", "level": "info", "phase": "publishing", "message": "Published weather 0.2.0 to roy-forge"}
```

These feed both the `forge_logs` table and a live-updating UI panel when viewing a job.

---

## 13. Open Questions

1. ~~Should the user be able to iterate?~~ **Resolved — §4.** Iteration is a first-class
   job kind, with workspace bundles + FORGE.md as the memory that survives pod death.

2. ~~Marketplace publishing?~~ **Resolved — §3.** The marketplace IS the delivery
   channel; there is no local-only path. Publishing to the *official/public* catalog
   (beyond the user's private marketplace) is a separate v2 concern that rides the
   marketplace's existing curation workflow.

3. ~~Plugin updates vs new plugins?~~ **Resolved — §4.4/§4.5.** Semver policy + immutable
   versions + rollback CR.

4. **Which object storage for bundles/reports?** — Tigris (Fly-native) is simplest.
   Could also use R2 since we already have it for luna-service. (Plugin artifacts
   themselves live in the marketplace's content-addressed store — not our problem.)

5. **Org mapping for private marketplaces** — one org per luna-service user on the
   marketplace service, or one umbrella org with per-user marketplaces? Decide in
   Phase C; the umbrella-org shape is simpler until users want to *manage* their
   marketplace directly.

6. **Can the user hand-edit a forge plugin?** — If they download the source, modify it,
   and republish manually, the next forge iteration's bundle is stale. v1 answer: the
   forge only trusts its own bundles; hand-edited plugins fall outside the iterate flow
   (document this). v2: git repo per plugin (§4.6) makes external edits mergeable.
