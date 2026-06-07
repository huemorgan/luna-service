# Cloudflare vs Fly.io — Luna Service Compute Review

**Date:** June 2026
**Context:** Luna Service runs isolated per-user agent instances (Python 3.12, pydantic-ai, FastAPI) on Fly Machines today. Cloudflare Containers went GA in April 2026. This document evaluates whether Cloudflare can replace or complement Fly for the agent fleet.

---

## Executive Summary

- **Fly.io remains the correct choice for Luna's per-agent compute layer.** It delivers every requirement (13/13) today with no workarounds.
- **Cloudflare Containers (GA April 2026) close the gap significantly** — Docker, scale-to-zero, lifecycle hooks. But three critical gaps remain: **no persistent disk across sleep cycles**, **no sub-process survival across sleep** (code sandbox dies mid-task), and **no memory-preserving suspend** (cold boot, not 300ms resume).
- **The sub-agent/code-sandbox gap is the deepest.** Luna agents spawn child processes for code execution that accumulate state across conversation turns. Cloudflare's sleep-on-idle model kills everything between turns — there's no way to keep a code sandbox alive while waiting for the user's next message.
- **Cloudflare already wins on storage (R2), CDN, DNS, and DDoS** — these are in production today and should stay.
- **The trigger to reconsider:** Cloudflare ships persistent disk with fast restore + sleep-aware process preservation. Until then, Fly is the only option for the agent fleet.

---

## What Luna Needs from the Compute Layer

| # | Requirement | Why |
|---|-------------|-----|
| 1 | Docker container execution (Python 3.12+, pydantic-ai, FastAPI) | Luna is a full Python app with native deps |
| 2 | Per-agent physical isolation (separate VMs) | Security: vault keys, credential isolation, code execution |
| 3 | Persistent POSIX filesystem (code execution sandbox) | `pip install`, venvs, user project files must survive restarts |
| 4 | Long-running processes (agents run indefinitely, not request-scoped) | Always-on tier: agents listen for triggers, run crons |
| 5 | Scale-to-zero with fast resume (~300ms) | Free tier: 95%+ idle, can't pay for always-on |
| 6 | SSE streaming for real-time chat | LLM token streaming to the browser |
| 7 | WebSocket support | Future: multi-channel, real-time collaboration |
| 8 | Per-machine env vars (unique secrets per agent) | Vault keys, DB URLs, LLM keys differ per tenant |
| 9 | Machine lifecycle control (start/stop/destroy via API) | Control plane orchestrates the fleet programmatically |
| 10 | Custom Docker images (different versions per agent) | Canary deploys, image version pinning per agent |
| 11 | Regions (deploy agents close to users) | Latency-sensitive chat interaction |
| 12 | Sub-process / sibling container spawning | Code execution sandbox: Luna runs user-written scripts, builds plugins for itself, and executes generated code in isolated child processes or sibling Docker containers. Requires full Linux process model — fork, exec, subprocess, Docker socket access. |
| 13 | Unrestricted CPU-bound execution | Agent loops, code compilation, data processing — not request-scoped, can saturate CPU for seconds to minutes |

---

## What Fly.io Provides Today

| # | Requirement | Fly Status | Notes |
|---|-------------|------------|-------|
| 1 | Docker containers | **Yes** | Firecracker microVMs, any Docker image, full Linux |
| 2 | Per-agent isolation | **Yes** | Each Machine is a separate microVM with hardware-level isolation |
| 3 | Persistent POSIX filesystem | **Yes** | Fly Volumes: real block storage, persists across stop/start/suspend, $0.15/GB-mo |
| 4 | Long-running processes | **Yes** | Machines run indefinitely; no request-scoped timeout |
| 5 | Scale-to-zero + fast resume | **Yes** | `auto_stop_machines = "suspend"` preserves memory; resume in ~300ms. Stop mode: cold boot in 1-3s |
| 6 | SSE streaming | **Yes** | Standard HTTP, no special handling needed |
| 7 | WebSocket support | **Yes** | Native, no limits on duration |
| 8 | Per-machine env vars | **Yes** | Set at creation via Machines API, per-machine config |
| 9 | Lifecycle API | **Yes** | Full REST API: create, start, stop, suspend, destroy, update, wait |
| 10 | Custom images per machine | **Yes** | Each machine can run a different image tag |
| 11 | Regions | **Yes** | 35+ regions, per-machine region selection at creation |
| 12 | Sub-process / sibling containers | **Yes** | Full Linux VM — fork, exec, subprocess, Docker-in-Docker all work. Each Fly Machine is a real microVM with a full process tree. |
| 13 | Unrestricted CPU-bound execution | **Yes** | No per-request or per-cycle CPU limits. The machine is yours for as long as it runs. |

**Verdict:** Fly delivers 13/13 requirements with no workarounds.

---

## What Cloudflare Provides Today (June 2026)

### Cloudflare Containers (GA April 13, 2026)

| # | Requirement | CF Containers Status | Detail |
|---|-------------|---------------------|--------|
| 1 | Docker containers | **Yes** | Supports Dockerfile, Docker Hub, custom registries. Docker-in-Docker available (Feb 2026). |
| 2 | Per-agent isolation | **Partial** | Each container runs in its own VM, but backed by Durable Objects — isolation is process-level in a shared compute substrate, not Firecracker-class hardware isolation. |
| 3 | Persistent POSIX filesystem | **No** | **All disk is ephemeral.** Sleep → fresh disk. Only workaround: FUSE-mount R2 (not SSD-speed; ~20-100ms per operation). Snapshots "coming soon" per docs. |
| 4 | Long-running processes | **Partial** | Containers can run indefinitely with `keepAlive: true`. But no uptime guarantee — host restarts are irregular and unannounced. Container reboots elsewhere after SIGTERM + 15min SIGKILL window. |
| 5 | Scale-to-zero + fast resume | **Partial** | `sleepAfter` puts containers to sleep when idle. But waking = fresh boot (no memory preservation, no disk state). Cold start is image-dependent, not ~300ms. |
| 6 | SSE streaming | **Yes** | Workers support unlimited wall-clock time for streaming responses. Container → Worker → client SSE works. |
| 7 | WebSocket support | **Yes** | Via Durable Objects Hibernatable WebSocket API. Proven at scale. |
| 8 | Per-machine env vars | **Yes** | Each container instance is a Durable Object addressed by ID. Env/config can be per-instance. |
| 9 | Lifecycle API | **Yes** | `start()`, `stop()`, `destroy()`, `getState()`, lifecycle hooks (`onStart`, `onStop`, `onError`). Managed via Worker code, not a REST API — but functionally equivalent. |
| 10 | Custom images per instance | **Partial** | Image is set per Container class in wrangler.toml. Running different images per instance requires multiple Container classes or runtime image specification (not documented as straightforward). |
| 11 | Regions | **Partial** | `locationHint` on Durable Object creation. Best-effort, not guaranteed placement. Limited to locations with pre-fetched images. No explicit "deploy in sjc" guarantee. |
| 12 | Sub-process / sibling containers | **Partial** | Docker-in-Docker was added Feb 2026 — so spawning child containers is technically possible. But ephemeral disk means child containers also lose state on sleep. Process forking inside the container works, but the execution model is still tied to the Durable Object lifecycle — if the parent sleeps, everything dies. No persistent process tree across wake cycles. For Luna's code sandbox (run user script → install deps → iterate → deliver results across multiple turns), this breaks whenever the agent sleeps mid-task. |
| 13 | Unrestricted CPU-bound execution | **Partial** | Active CPU is billed per-second, no hard cap per request. But Cloudflare reserves the right to throttle or migrate containers under load. No SLA on sustained CPU saturation. Fly's model is simpler: you have the machine, use it however you want. |

### Instance Limits (as of Feb 2026 update)

| Resource | Max per Instance | Max per Account |
|----------|-----------------|-----------------|
| vCPU | 4 | 1,500 total |
| Memory | 12 GiB | 6 TiB total |
| Disk | 20 GB | 30 TB total |

### Pricing Model

- Memory: $0.0000025/GiB-second (billed every 10ms while running)
- CPU: $0.000020/vCPU-second (active CPU only)
- Disk: $0.00000007/GB-second (while running)
- Included monthly (Workers Paid $5/mo): 25 GiB-hours memory, 375 vCPU-minutes, 200 GB-hours disk
- Egress: $0.025/GB (NA/EU), $0.04-0.05/GB (other regions), 500GB-1TB included

### Other Cloudflare Services

| Service | Relevance to Luna | Status |
|---------|-------------------|--------|
| **D1** (serverless SQLite) | Could replace Postgres for simple cases | No pgvector. Max 10GB/database. No roles/schemas. No HNSW indexes. |
| **Vectorize** | Vector search for memory plugin | 5M vectors/index. No SQL JOINs. HTTP API only from Workers. Separate from relational data. |
| **Durable Objects** | Per-agent state coordination | 10GB SQLite storage per object. Single-threaded. JavaScript/TypeScript only — can't run Python. |
| **Workers** | Edge routing, SSE proxy, presigned URLs | 128MB memory, 5min CPU per request. Perfect for control-plane edge logic. |
| **R2** | Object storage for uploads/artifacts | **Already in production** for Luna. Free egress. S3-compatible. |
| **DNS** | `luna.com.ai` zone | **Already in production.** |
| **CDN/DDoS** | Protection + caching | **Already in production.** |

---

## The Gaps — What Cloudflare Would Need to Add

### Gap 1: Persistent Disk (Critical Blocker)

**What's missing:** Disk state resets to the container image on every sleep/wake cycle. There is no equivalent to Fly Volumes.

**Impact on Luna:** Luna's code execution sandbox requires persistent `/workspace` with venvs, user projects, downloaded tools. Without persistent disk:
- Every wake requires rebuilding Python venvs (minutes, not milliseconds)
- User-written code disappears on sleep
- `pip install` results are lost
- Plugin installations vanish

**Workaround available:** FUSE-mount R2 as a filesystem. But R2 operations are 20-100ms each. Running `pip install` against FUSE-R2 would be 100x slower than local disk. Not viable for interactive development or package management.

**What Cloudflare needs to ship:** Persistent disk snapshots with fast restore (< 500ms). Docs say "coming soon" with no timeline.

### Gap 2: Resume Latency

**What's missing:** Cloudflare Container sleep = full shutdown + fresh boot. No memory snapshot. Resume is a cold start — download image layers, boot process, initialize app.

**Impact on Luna:** Vision doc targets 300ms wake time for suspended-to-running. Fly's suspend mode preserves memory state. Cloudflare's sleep mode is equivalent to Fly's "stop" (cold boot), which takes 1-5+ seconds depending on image size.

**What Cloudflare needs to ship:** Memory-preserving suspend/resume (equivalent to Firecracker snapshots).

### Gap 3: Uptime Guarantees for Long-Running Instances

**What's missing:** Cloudflare explicitly states: "Cloudflare does not guarantee that any instance will run for any set period of time." Host restarts happen on an "irregular cadence." Container gets SIGTERM → 15min → SIGKILL, then reboots elsewhere.

**Impact on Luna:** Always-on tier agents (Pro/Power) need reliable uptime. Unannounced restarts with fresh disk mean:
- Cron jobs get interrupted without warning
- MCP server processes die
- Recovery requires full re-initialization from DB + re-install deps

**Fly comparison:** Fly Machines persist state across host migrations (Volume reattaches). Restarts are rare and the Machine + Volume come back together.

### Gap 4: Sub-Agent / Code Sandbox Lifecycle

**What's missing:** Luna agents spawn sub-processes for code execution — running user scripts, building plugins, iterating on errors. This requires a persistent process tree and disk across multiple conversation turns. On Cloudflare Containers, Docker-in-Docker exists (Feb 2026), but the parent container can sleep at any idle moment, killing all child processes and wiping their disk state. There's no way to say "keep this container alive while a sub-task is running in a child process" — the sleep policy is based on network inactivity, not process activity.

**Impact on Luna:**
- User says "build me a script that does X" → Luna writes code, runs it, gets an error, iterates → 3-4 turns of code execution with accumulated state (installed packages, intermediate files, debug output)
- If the agent sleeps between turns (user takes 30 seconds to respond), all child processes die, venvs are gone, intermediate files vanish
- Luna's self-plugin-building (Pillar 6: "writes its own plugins") requires running `luna plugin init`, writing code, testing it, installing it — a multi-step process that assumes persistent disk and process continuity

**What Cloudflare needs to ship:** Either (a) sleep-aware child process preservation, or (b) persistent disk (Gap 1) which would at least allow rebuilding process state on wake. Today neither exists.

### Gap 5: Per-Instance Image Control

**What's missing:** Cloudflare Container images are defined per-class in `wrangler.toml`. Running different image versions per instance (Luna's canary deploy model where agent X runs image v2.1 while agent Y stays on v2.0) requires managing multiple Container classes or complex routing logic.

**Fly comparison:** Each Machine can be individually updated to a new image via a single API call: `POST /machines/{id}` with a new `config.image`.

### Gap 5: No Postgres Equivalent

**What's missing:** D1 is SQLite-based. No pgvector extension. No schema-per-tenant with DB roles. No `REVOKE DELETE ON approval_decisions` capability. Max 10GB per database.

**Impact on Luna:** Luna's memory plugin requires pgvector HNSW indexes. The audit security model requires Postgres roles that prevent the app from deleting its own audit records. Schema-per-tenant isolation requires Postgres features.

**Workaround:** Use external Postgres (Neon, Supabase, Render) via Hyperdrive. This works but means Cloudflare doesn't simplify the DB layer at all.

### Gap 6: Hardware-Level Isolation Unclear

**What's missing:** Cloudflare Containers are described as running in "VMs" but the isolation boundary documentation is sparse. It's not clear whether these are Firecracker-class microVMs (like Fly) or lighter-weight container isolation (like gVisor). For an agent platform handling user credentials and executing arbitrary code, the isolation model matters.

---

## What Cloudflare Already Wins On

| Advantage | Detail | Luna Already Using? |
|-----------|--------|---------------------|
| **R2 object storage** | $0.015/GB-mo, free egress, S3-compatible, CDN-integrated | Yes — all user uploads, generated artifacts |
| **Edge network (300+ PoPs)** | Sub-10ms to most users globally | Yes — serving static assets, signed URLs |
| **DNS** | `luna.com.ai` zone management, fast propagation | Yes — zone exists, will point to production |
| **DDoS protection** | Automatic L3/L4/L7 mitigation | Yes — comes free with Cloudflare DNS |
| **Workers for edge logic** | Could run the SSE proxy / router at the edge instead of on Render | Not yet — potential optimization |
| **WebSocket at edge** | Durable Objects can terminate WebSocket connections globally | Not yet — future multi-channel use |
| **Free egress from R2** | Every download from storage is free | Yes — critical cost savings vs S3 |
| **Image/CDN serving** | Cache and serve user-uploaded media from edge | Yes — via R2 public access / signed URLs |

---

## Hybrid Architecture Possibility

Luna already runs a hybrid: Render (control plane) + Fly (agent fleet) + Cloudflare (storage + CDN + DNS). The question is whether Cloudflare can take on more responsibility.

### Current Architecture

```
User → Cloudflare DNS → Render (control plane + router) → Fly Machine (agent)
                                                        ↘ Cloudflare R2 (storage)
```

### Enhanced Hybrid (Viable Today)

```
User → Cloudflare DNS + CDN + DDoS
     → Cloudflare Worker (edge router + SSE proxy)
     → Fly Machine (agent)
     ↘ Cloudflare R2 (storage)
```

**What this adds:**
- Edge-routed requests: Workers at 300+ PoPs route to the correct Fly Machine, reducing first-byte latency
- SSE streaming from edge: Worker holds the client connection, proxies to Fly, streams tokens back from the nearest edge PoP
- Presigned URL generation at edge: No round-trip to Render for file downloads
- Rate limiting at edge: Abuse protection before traffic reaches Fly

**What stays on Fly:**
- Agent compute (the Python process, pydantic-ai runtime, tools, MCP)
- Persistent Volumes (code workspace)
- Lifecycle management (suspend/resume with memory state)

**What stays on Render:**
- Control plane API (user management, billing, provisioning logic)
- Control plane Postgres (accounts, agents registry, billing records)

### Future Hybrid (If Cloudflare Ships Persistent Disk)

If Cloudflare ships fast-restore persistent snapshots:

```
User → Cloudflare Worker (edge router)
     → Cloudflare Container (agent) with persistent snapshot
     → Cloudflare R2 (storage)
     → External Postgres via Hyperdrive (tenant data + pgvector)
```

This would consolidate compute + storage + networking on one platform. Benefits: single vendor, unified billing, potentially lower latency (container runs on same network as R2). Risks: vendor lock-in, less mature platform, unclear isolation guarantees.

---

## Cost Comparison (1,000 agents, 5% active at any time)

### Assumptions
- 1,000 agents total, 50 active at any moment
- Each agent: 1 vCPU, 1GB RAM, 5GB persistent storage
- Active time: ~36 hours/month per agent (5% of 720h)
- Rest of time: suspended/sleeping

### Fly.io

| Item | Calculation | Monthly Cost |
|------|-------------|--------------|
| Compute (active) | 1,000 agents × 36h × $0.0000025/vCPU-s × 3600 | ~$324 |
| RAM (active) | 1,000 agents × 36h × 1GB × $0.000003/GB-s × 3600 | ~$389 |
| Volumes (always) | 1,000 × 5GB × $0.15/GB-mo | $750 |
| Root FS (stopped) | 1,000 × 1GB × $0.15/GB-mo | $150 |
| **Total** | | **~$1,613/mo** |

### Cloudflare Containers (hypothetical — assuming persistent disk existed)

| Item | Calculation | Monthly Cost |
|------|-------------|--------------|
| CPU (active) | 1,000 × 36h × 3600s × $0.000020/vCPU-s | ~$2,592 |
| Memory (active) | 1,000 × 36h × 3600s × 1GiB × $0.0000025/GiB-s | ~$324 |
| Disk (active only) | 1,000 × 36h × 3600s × 5GB × $0.00000007/GB-s | ~$45 |
| **Total** | | **~$2,961/mo** |

**Note:** Cloudflare only bills disk while running (no cost while sleeping), but CPU is ~8x more expensive per second than Fly. At these utilization levels, Fly is ~45% cheaper. The gap narrows at higher utilization because Fly charges for Volumes 24/7.

---

## Recommendation

### Decision: Stay on Fly.io for the agent fleet. Keep Cloudflare for storage, CDN, DNS.

**Reasoning:**

1. **Persistent disk is non-negotiable.** Luna's code execution model requires POSIX filesystem state that survives sleep cycles. Cloudflare doesn't have this today. FUSE-R2 is too slow for package management and code execution.

2. **Resume latency matters.** Fly's suspend mode gives ~300ms resume. Cloudflare's sleep is a cold boot (seconds). The vision doc commits to sub-800ms first-message latency including wake time.

3. **Operational maturity.** Fly's Machines API has been production-grade since 2022. Luna's `FlyMachinesRuntime` class already works. Switching to Cloudflare Containers would require rewriting the runtime adapter around a fundamentally different model (Durable Object classes vs REST API, per-class images vs per-machine images).

4. **Cost.** Fly is cheaper at Luna's expected utilization pattern (many idle agents, few active at once) due to Volume-based billing vs per-second disk billing and lower CPU rates.

5. **Isolation confidence.** Fly's Firecracker microVMs are the same technology AWS Lambda uses. Cloudflare's container isolation model is newer and less documented.

### What Would Change This Recommendation

| Cloudflare Announcement | Impact |
|-------------------------|--------|
| Persistent disk snapshots with < 500ms restore | Removes blocker #1 |
| Memory-preserving suspend (like Firecracker snapshots) | Removes blocker #2 |
| Per-instance image specification (not per-class) | Removes friction for canary deploys |
| Instance sizes > 4 vCPU / 12 GiB RAM | Enables Power tier agents |
| Published isolation model (Firecracker-equivalent) | Gives security confidence |
| Combined: all of the above | Full evaluation warranted; likely switch |

### Near-Term Action (Optional Enhancement)

Consider adding a Cloudflare Worker as an edge proxy in front of Render's router:
- Terminates TLS at Cloudflare edge (already happening via DNS)
- Adds DDoS protection for the control plane
- Could handle presigned URL generation for R2 at the edge
- Could proxy SSE streams for lower latency to distant users

This is additive and doesn't require changing the agent fleet. Evaluate after MVP ships and latency data from real users is available.

---

## References

- Cloudflare Containers GA: [changelog, Apr 13 2026](https://developers.cloudflare.com/changelog/post/2026-04-13-containers-sandbox-ga/)
- Cloudflare Containers limits: [docs](https://developers.cloudflare.com/containers/platform-details/limits/)
- Cloudflare Containers pricing: [docs](https://developers.cloudflare.com/containers/pricing/)
- Cloudflare Containers lifecycle: [docs](https://developers.cloudflare.com/containers/platform-details/architecture/)
- Cloudflare Containers FAQ (disk persistence): [docs](https://developers.cloudflare.com/containers/faq/)
- Cloudflare Workers limits: [docs](https://developers.cloudflare.com/workers/platform/limits/)
- Cloudflare Durable Objects rules: [docs](https://developers.cloudflare.com/durable-objects/best-practices/rules-of-durable-objects/)
- Cloudflare D1 + Vectorize: no native pgvector alternative; Vectorize is a separate service
- Fly.io Machines API: [docs](https://fly.io/docs/machines/guides-examples/managing-machines-with-the-api/)
- Fly.io autostop/autostart: [docs](https://fly.io/docs/launch/autostop-autostart/)
- Docker-in-Docker on Cloudflare: [changelog, Feb 17 2026](https://developers.cloudflare.com/changelog/post/2026-02-17-docker-in-docker/)
- Higher container limits: [changelog, Feb 25 2026](https://developers.cloudflare.com/changelog/post/2026-02-25-higher-container-resource-limits/)
