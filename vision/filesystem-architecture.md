# Filesystem Architecture

> Luna stores three fundamentally different kinds of data. Each kind belongs in a different tier. Trying to make one tier do all three jobs results in either bad cost economics, broken code execution, or both. This document explains the three-tier model, what lives in each tier, and how they work together.

---

## TL;DR

Luna Service uses three storage tiers, each chosen for what it does best:

| Tier | What | Why It's Here | Per-Tenant Cost |
|------|------|---------------|-----------------|
| **Shared Postgres (Render)** | Conversations, memory, identity, vault, settings | Structured queries, transactions, pgvector semantic search, audit guarantees via DB roles | ~$0.05-0.30/mo per tenant on a shared Standard instance |
| **Object Storage (Cloudflare R2)** | User uploads, generated artifacts, archives, shared assets | Cheap at scale, free egress, CDN-served, durable, accessible by browsers directly | ~$0.05-0.50/mo |
| **Per-Machine Volume (Fly Volume)** | Live code workspace, venvs, executables, working files | Real POSIX filesystem (only thing that makes code execution work) | ~$0.75/mo |

**Don't put everything on one tier.** Each one is the wrong tool for two of the three jobs. The hybrid is what every mature agent platform uses (Replit, Codespaces, Vercel, Render) and what keeps Luna Service economically viable at scale.

---

## Why Three Tiers Instead of One

This is the most-asked architectural question and deserves a direct answer. Reasonable alternatives exist; here's why each one fails:

### Why not "just use a big Volume for everything"?

A Volume is a real filesystem mounted to one VM. It's the right answer for **executable code, venvs, and working files** — but trying to put everything on it breaks at scale:

1. **Cost.** Volume storage is ~$0.15/GB-month. Object storage is ~$0.015/GB-month. Files that are accessed rarely (user uploads, archives) pay 10x more for no benefit.

2. **Durability.** A Volume lives on **one physical disk in one data center**. If that disk fails (it happens), the data is gone unless you have snapshots. Object storage has 11 nines of durability by default — built-in cross-region replication.

3. **Serving files to browsers.** When a user downloads a PDF, a Volume requires Luna's process to be awake, read the file, and stream it through Python — using Luna's bandwidth and event loop. R2 + CDN serves the same file directly from Cloudflare's edge, with zero load on Luna.

4. **Queries.** "Show me all PDFs over 10MB uploaded this week" can be a single SQL query against Postgres metadata. Against files on a Volume, it's a full directory scan.

5. **Sharing across Lunas.** A Volume can only be mounted to one VM at a time. Plugin marketplace assets, shared templates, anything used by multiple Lunas — would have to be copied to every Volume.

6. **Recovery on Machine death.** Machines get destroyed during deploys, scale events, or hardware issues. Recovery from snapshots is slow (minutes). Postgres + R2 are continuously durable and accessible from anywhere.

A Volume is essential for what it's good at. It's a bad choice for everything else.

### Why not "just use Postgres for everything"?

Postgres is the right answer for **structured queryable data with transactions and audit guarantees**. Putting larger data in it breaks:

1. **Cost.** Postgres storage is ~10x more expensive per GB than object storage. A user with 50GB of PDFs pays $10+/mo just for storage on Postgres vs $0.75 on R2.

2. **Performance.** Postgres BLOB columns are slow to read large objects and slow to back up. Pulling a 100MB file from Postgres is dramatically slower than streaming from R2.

3. **Streaming and CDN.** Postgres can't serve files directly to browsers via a CDN. Every download has to go through your app server.

4. **Code execution.** You can't `pip install` to Postgres. You can't `chmod +x` a row. You can't run a Python script that's stored as a BLOB without first extracting it to disk.

Postgres is the brain for structured data; it's the wrong place for blobs and live filesystems.

### Why not "just use object storage for everything"?

Object storage is the right answer for **large, immutable-ish blobs accessed via HTTP**. Trying to make it the only tier breaks:

1. **No POSIX filesystem.** Most code that does anything useful expects a real filesystem. `pip install`, `npm install`, Python venvs, node_modules, file locks, symlinks, executable permissions, atomic writes — all impossible on object storage.

2. **High per-request latency.** Each S3/R2 read is ~20-100ms. Code that does many small reads (compilers, package managers, even text editors) becomes 100x slower.

3. **No transactions.** Object storage is eventually consistent. You can't safely do "read row, modify, write" — you'd race against yourself.

4. **No indexes or queries.** Want to list all files for a user? Has to be a prefix scan, paginated. Want to find by date range? Impossible without a separate index.

5. **Vector search.** Luna's memory plugin needs pgvector semantic search. No object storage offers this.

Object storage is the right answer for cold storage and CDN delivery; it's the wrong primary substrate for anything else.

### Why not "SQLite on a Volume per tenant + R2 backups"?

This is the most-tempting alternative and worth a serious answer because it's genuinely simpler:

- One SQLite file per tenant on their Volume
- [Litestream](https://litestream.io) streams WAL changes to R2 continuously
- Crash recovery: restore from R2 to a fresh Volume

It's a legit architecture used by many indie SaaS. But for Luna Service specifically:

1. **pgvector.** Luna's memory plugin uses pgvector semantic similarity (`embedding <-> $1 LIMIT 5`). SQLite has `sqlite-vec` but it's smaller ecosystem, slower at scale, and would require Luna code changes. Postgres just works with what Luna already has.

2. **Append-only audit at the DB role level.** Luna's approval plugin relies on `REVOKE DELETE, UPDATE ON approval_decisions FROM luna_app` — a Postgres role that *cannot* tamper with audit history even if compromised. SQLite has no roles; whoever opens the file has full access. We lose a security property.

3. **Multi-process concurrency.** SQLite serializes writes through a single writer lock. If we ever add background workers, scheduled task runners, or webhook handlers (we will), the single-writer constraint becomes painful. Postgres handles this with MVCC.

4. **Cross-tenant ops.** "Show me total active users" or "find users hitting their plan limit" is one query against shared Postgres. Against 1,000 SQLite files, it's open-each-file-and-aggregate — slow and operationally fragile.

5. **Migration management.** A schema change against shared Postgres is one Alembic run. Against 1,000 per-tenant SQLite files, it's 1,000 individual migrations to coordinate, monitor, and recover from failures of.

The simplicity is real, but the trade-offs don't fit a multi-tenant SaaS with Luna's specific requirements. **SQLite + Litestream is excellent for single-tenant self-hosters** — which is exactly what OSS Luna will continue to support.

---

## What Lives Where

### Postgres (Shared, Schema-Per-Tenant)

The structured brain of each Luna. Every tenant gets their own Postgres schema; Luna connects via a per-tenant role that can only access that schema.

**Tables (mirroring Luna OSS schema, untouched):**

| Table | Contents | Why Postgres |
|-------|----------|--------------|
| `conversations` | Chat sessions | Query by user, date, title |
| `messages` | Every message in every conversation | Paginated reads, ordered by time |
| `memory_facts` | Long-term memory with pgvector embeddings | **Semantic similarity search** (pgvector) |
| `identity` | Agent name, persona, mission | Single-row, queryable |
| `patterns` | Behavioral rules | Listable, editable |
| `vault_credentials` | Encrypted secrets | Lookup by service name; encrypted at rest |
| `approvals` + `approval_decisions` + `approval_grants` | Audit-grade approval history | **DB role-level append-only** for security |
| `versions` | Self-modification history | Time-ordered, rollback queries |
| `plugin_state` | Per-plugin DB state | Each plugin namespace |
| `mcp_servers` | Configured MCP servers | List, enable/disable |
| `file_metadata` | Index of files in R2 + Volume | Foreign keys, queryable, joined with content |

**Schema isolation pattern:**

```sql
-- For new tenant `user_abc`:
CREATE SCHEMA luna_user_abc;
CREATE ROLE luna_user_abc_role LOGIN PASSWORD '<random>';
GRANT ALL ON SCHEMA luna_user_abc TO luna_user_abc_role;
ALTER ROLE luna_user_abc_role SET search_path = luna_user_abc;

-- Optional: enforce that this role CANNOT see other schemas
REVOKE ALL ON SCHEMA public FROM luna_user_abc_role;
-- (Repeat for any other schemas; only their own remains accessible)
```

Luna's connection string includes `?options=-csearch_path%3Dluna_user_abc` — Postgres transparently scopes everything to that schema. **Luna's code is unchanged**; it still references `identity` and Postgres resolves it as `luna_user_abc.identity`.

**Audit security still works:**
```sql
REVOKE DELETE, UPDATE ON luna_user_abc.approval_decisions FROM luna_user_abc_role;
REVOKE DELETE, UPDATE ON luna_user_abc.approval_grants FROM luna_user_abc_role;
REVOKE DELETE, UPDATE ON luna_user_abc.versions FROM luna_user_abc_role;
```

Each tenant's audit tables are append-only at the database level. A compromised Luna process cannot erase its tracks even within its own tenant.

**Provider:** Render Postgres (managed PG 16, pgvector + HNSW supported, daily snapshots + 7-day point-in-time recovery on Standard plan). We're already on Render for the control plane — using their Postgres keeps the vendor footprint small and co-locates the DB with the control plane (sub-ms latency for schema/role admin).

**Capacity:** One Render Postgres Standard instance (1 GB RAM, 16 GB storage) can serve ~100-500 tenants depending on activity. Conversation + memory data is small per tenant (~50-200 MB after a year of heavy use). When we outgrow vertical scaling, options are: (1) bump to Pro/Custom Render Postgres, or (2) shard across multiple Render Postgres instances by `tenant_id` range — same code, different connection strings per shard.

---

### Object Storage (Cloudflare R2)

Cheap, durable, web-accessible blob storage. Used for anything that's **large**, **served to browsers**, or **shared across Lunas**.

**Bucket structure:**

```
luna-service-prod/                    (one bucket)
├── tenant/
│   ├── user_abc/
│   │   ├── uploads/
│   │   │   ├── 2026-06-02_report.pdf
│   │   │   └── 2026-06-02_image.png
│   │   ├── generated/
│   │   │   └── 2026-06-02_export.csv
│   │   └── archive/
│   │       └── workspace_snapshot.tar.gz
│   ├── user_xyz/
│   │   └── ...
└── shared/
    ├── marketplace/
    │   └── plugins/{plugin_id}/{asset}
    ├── templates/
    │   └── {template_id}/{file}
    └── static/
        └── docs/{slug}.md
```

**What goes here:**

- **User uploads** — PDFs, images, datasets the user shares with Luna
- **Generated outputs** — reports Luna produces, exported data, screenshots
- **Archives** — old workspace contents cold-stored for cost reasons
- **Plugin marketplace assets** — README, screenshots, distributable packages (shared across all tenants)
- **Static templates** — agent templates, knowhow pack contents (shared)
- **Avatars** — user/agent profile pictures

**Per-tenant isolation:**

R2 supports **scoped API tokens** — each Luna gets credentials that can only access `tenant/{their_id}/*`. The control plane generates these at provisioning and passes them as env vars to the Luna Machine.

```
LUNA_R2_ACCESS_KEY=<scoped to tenant/user_abc/*>
LUNA_R2_SECRET_KEY=<scoped>
LUNA_R2_ENDPOINT=https://<account>.r2.cloudflarestorage.com
LUNA_R2_BUCKET=luna-service-prod
LUNA_R2_PREFIX=tenant/user_abc/
```

Luna's file plugin uses these credentials transparently. It cannot read or write outside its prefix even if Luna's code has a bug.

**Why R2 over S3:**

| Property | Cloudflare R2 | AWS S3 |
|----------|---------------|--------|
| Storage cost | $0.015/GB-mo | $0.023/GB-mo |
| Egress (downloads) | **$0 (free)** | $0.09/GB |
| API compatibility | S3-compatible | S3-native |
| CDN integration | Built-in (free) | Requires CloudFront ($) |
| Multi-region | Auto | Region-specific |

For Luna's traffic pattern (users uploading files, downloading generated content, browsers fetching media), R2's free egress is dramatic savings. At 1,000 users averaging 50GB downloads/month, R2 saves $4,500/month vs S3.

**Direct browser access:**

User downloads happen via **signed URLs** generated by the control plane:

```python
url = r2_client.generate_presigned_url(
    "get_object",
    Params={"Bucket": "luna-service-prod", "Key": "tenant/user_abc/uploads/report.pdf"},
    ExpiresIn=3600,
)
# Browser fetches directly from cdn.luna.com/...
# Luna's Machine is never touched
```

This means:
- Downloads don't wake suspended Lunas
- Downloads don't consume Luna's bandwidth
- Downloads are served from Cloudflare's edge (fast worldwide)
- Luna's CPU/event loop stays free for actual work

---

### Per-Machine Volume (Fly Volume)

A real POSIX filesystem mounted to one Luna's VM. Used for **anything that needs to be a real filesystem** — primarily code execution and live working files.

**Mount point:** `/workspace` on every Luna Machine.

**Contents:**

```
/workspace/
├── projects/                    User project work
│   ├── my-website/
│   │   ├── index.html
│   │   └── server.py
│   └── data-analysis/
│       └── notebook.ipynb
├── venvs/                       Python virtual environments
│   └── default/
│       └── lib/python3.12/site-packages/
│           ├── requests/
│           ├── pandas/
│           └── ...
├── plugins-user/                User-installed plugins
│   └── plugin_my_custom/
│       ├── manifest.py
│       └── handlers.py
├── tools/                       Downloaded executables
│   ├── ffmpeg
│   └── pandoc
└── scratch/                     Temp working files (cleaned periodically)
    └── upload_processing/
```

**What goes here:**

- **Code Luna writes for itself** (Phase 011: code engine) — must be on a real FS to execute
- **Python venvs and `node_modules`** — package managers don't work on object storage
- **User-installed plugins** — Python imports them as real modules
- **Cached downloaded binaries** — `chmod +x` requires real filesystem
- **Temporary working files** — analysis tools that seek through files need disk
- **Materialized R2 content during processing** — download → process → upload back

**What does NOT go here:**

- User uploads (they go to R2 first, materialized only during active processing)
- Conversation history (Postgres)
- Configuration (Postgres or env vars)
- Vault contents (Postgres, encrypted)

**Size:** Start at 1-5GB per Luna depending on tier:
- Free: 1GB (sufficient for chat-focused use)
- Pro: 5GB (workspace + venvs + some tools)
- Power: 20GB (heavy code execution, large datasets)

**Cost:** $0.15/GB-month. A 5GB Volume costs $0.75/month per Luna.

**Persistence:**

Volumes survive Machine restarts, suspends, and deploys. They're tied to a Machine's lifecycle — if you `fly machine destroy`, the Volume can be preserved or deleted depending on settings.

**Backup strategy:**

The Volume itself is *not* the source of truth for important data. Treat Volume contents as **regenerable or archivable**:

- **Code/configs** — also versioned in Postgres (the `versions` table tracks self-modifications). Can rebuild from there.
- **Working files** — if cold for 30+ days, archive to R2 with a `file_metadata` entry pointing to the archive location. Restore on-demand.
- **Venvs/node_modules** — regenerable from `requirements.txt` / `package.json` (both tracked in Postgres + Volume).

This means a destroyed Volume is recoverable, just with a brief rebuild. Critical data is never *only* on the Volume.

---

## How the Three Tiers Work Together

### Scenario 1: User uploads a PDF and asks Luna to summarize it

```
1. User selects file in browser
2. Browser → control plane: "POST /uploads/presign"
3. Control plane returns signed R2 upload URL
4. Browser uploads directly to R2 at tenant/user_abc/uploads/report.pdf
   (Bypasses Luna entirely — no wake needed, no bandwidth used)
5. Browser → Luna chat: "summarize report.pdf"
6. Luna wakes (300ms if suspended)
7. Luna queries Postgres: SELECT * FROM file_metadata WHERE name='report.pdf'
   → gets r2_key
8. Luna downloads from R2 to /workspace/scratch/report.pdf
   (only for processing — temporary materialization)
9. Luna extracts text with PyPDF, generates summary via LLM
10. Luna saves summary as new row in Postgres summaries table
11. Luna responds in chat with summary
12. /workspace/scratch/report.pdf cleaned up after timeout
```

**Each tier did what it's good at:**
- R2 stored the PDF cheaply and accepted the upload directly from browser
- Volume gave Python the real file it needed to read for extraction
- Postgres stored the summary as queryable structured data

### Scenario 2: Luna writes and runs a Python script

```
1. User: "Write me a script that scrapes the top 10 HackerNews posts"
2. Luna composes script
3. Luna saves to /workspace/projects/hn_scraper/scrape.py (Volume)
4. Luna inserts metadata row in Postgres:
   INSERT INTO file_metadata (path, type, blob_key) VALUES
   ('/workspace/projects/hn_scraper/scrape.py', 'python', null);
5. Luna runs: pip install requests beautifulsoup4
   → writes to /workspace/venvs/default/ (Volume)
6. Luna runs: python /workspace/projects/hn_scraper/scrape.py
   → executes from Volume, prints output
7. Output saved to /workspace/projects/hn_scraper/results.json (Volume)
8. Luna shows results in chat
```

**Why this only works with a Volume:**
- `pip install` can't write to R2 or Postgres
- `python script.py` needs a real file path
- The venv directory has thousands of small files (Python packages) — Volume handles this; object storage would be 100x slower

### Scenario 3: User downloads the generated report on their phone

```
1. User taps download link
2. Browser → control plane: "GET /api/files/{id}/download"
3. Control plane:
   - Validates user owns this file (Postgres query)
   - Generates signed R2 URL (1 hour expiry)
   - Returns redirect
4. Browser follows redirect to cdn.luna.com/...
5. File served directly from Cloudflare's edge CDN
   - Fast (geographically close)
   - Free (R2 egress is free)
   - Luna's Machine never woken
   - User downloads at full bandwidth
```

**If the file were on a Volume:**
- Luna's Machine has to be awake to serve
- Stream goes through Python (slow)
- Uses Luna's bandwidth (eats into per-tier limits)
- No CDN, so it's slow if the user is geographically far

### Scenario 4: Luna's Machine is destroyed and recreated

```
1. Fly recreates the Machine (deploy, host issue, scale event)
2. New Machine boots with same Volume reattached
3. Luna starts, connects to same Postgres (URL in env)
4. Luna reads identity, conversations, memory from Postgres → instant
5. Workspace files are on the (preserved) Volume → instant
6. Venvs may need rebuilding (if Volume was lost):
   - Luna detects missing venv
   - Reads requirements.txt from Postgres or Volume
   - Runs pip install (1-3 min cold rebuild)
7. R2 contents always accessible — no recreation needed
```

**If the Volume IS lost (rare, but possible):**
- Conversations, memory, vault: safe in Postgres
- User uploads, archives: safe in R2
- Code: tracked in Postgres `versions` table → can restore
- Venvs: regenerable from `requirements.txt`
- Worst case: 5-10 minute rebuild, no data loss

---

## Per-Tenant Vault Encryption Keys

The vault is the most security-sensitive component. Luna stores user credentials encrypted with AES-256-GCM. The encryption key is **per-tenant**, never shared, never logged.

**Today (Luna OSS):** Single `LUNA_VAULT_MASTER_KEY` env var per Luna instance.

**Multi-tenant approach:** Each Luna gets a unique key derived from a control-plane-held root + tenant ID:

```
tenant_key = HKDF(
    secret=KMS_ROOT_KEY,        ← Held by control plane, in AWS KMS or similar
    salt=tenant_id,              ← Unique per Luna
    info="luna-vault-v1",
    length=32,
)
```

The derived `tenant_key` is passed to the Luna Machine as `LUNA_VAULT_MASTER_KEY`. **Luna's code is unchanged**; it just receives a different key per instance.

**Properties this gives us:**

- Each tenant's vault is encrypted with a key only their Luna ever sees
- Control plane operators cannot decrypt user vaults (they have the root but not the live derived keys; deriving requires being the running Luna)
- If a tenant's Machine is compromised, only that tenant's vault is at risk — not the fleet
- Key rotation is possible (rotate root, derive new keys, re-encrypt vaults in place)

**Encrypted vault data itself** lives in the tenant's Postgres schema (cheap, queryable, transactional) — the encryption key is the thing that's per-tenant; the encrypted blobs share infrastructure.

---

## Cost Modeling

Let's run real numbers for different scales.

### Single user (free tier)

| Tier | Usage | Cost |
|------|-------|------|
| Postgres | ~10MB metadata + history | included in shared plan |
| R2 | ~500MB uploads | $0.0075 |
| Volume | 1GB | $0.15 |
| **Total file storage** | | **~$0.16/mo** |

### 100 users

| Tier | Usage | Cost |
|------|-------|------|
| Postgres (shared) | ~10GB total | $20 (Render Standard) |
| R2 | ~50GB total | $0.75 storage + $0 egress |
| Volumes | 100 × 2GB avg = 200GB | $30 |
| **Total file storage** | | **~$50/mo** |
| **Per user** | | **$0.50** |

### 1,000 users

| Tier | Usage | Cost |
|------|-------|------|
| Postgres (shared) | ~100GB total | $95-200 (Render Pro / larger Standard) |
| R2 | ~500GB total | $7.50 storage + $0 egress |
| Volumes | 1,000 × 3GB avg = 3TB | $450 |
| **Total file storage** | | **~$527/mo** |
| **Per user** | | **$0.53** |

### 10,000 users

| Tier | Usage | Cost |
|------|-------|------|
| Postgres (shared) | ~1TB total | $500-1000 (Render Pro/Custom, or sharded across 2-4 instances) |
| R2 | ~5TB total | $75 storage + $0 egress |
| Volumes | 10,000 × 3GB avg = 30TB | $4,500 |
| **Total file storage** | | **~$5,000/mo** |
| **Per user** | | **$0.50** |

**Storage costs stay nearly flat per-user** (~$0.50) regardless of scale — this is the unit economics we need. Compare to alternatives:

- **All-Volume at 10K users:** 30TB × $0.15 = $4,500 (same compute) + 5TB R2-content-on-Volume at $750 + cold archive at $300 = ~$5,550. Marginal savings, much worse durability.
- **All-Postgres at 10K users:** 5TB of BLOBs on Postgres at ~$0.20/GB = $1,000 + impossible to serve files via CDN + slow.
- **All-R2 at 10K users:** Cheap storage but **code execution is broken**, so this isn't actually a Luna at all.

The three-tier hybrid is what makes the unit economics work. At $0.50/user/mo for storage, our pricing tiers ($0 Free / $19 Pro / $79 Power) have room for healthy margins after compute and LLM costs.

---

## Implementation Notes for Luna OSS

The OSS Luna doesn't need significant changes to support this storage model. The minor additions are generally useful even for self-hosters:

### Already supported (no changes needed)

- Postgres connection via `LUNA_DATABASE_URL` — works with our search_path approach unchanged
- Vault encryption — works with any 32-byte key, doesn't care if it's derived per-tenant
- Plugins reading/writing files to a workspace directory — already works

### Small additions for the hosted use case (proposed upstream)

#### 1. Plugin: `plugin-file-storage` (or built-in interface)

A storage abstraction that lets Luna's file operations use:
- Local filesystem (OSS default — current behavior)
- S3-compatible object storage (R2 / S3 / Minio) — what hosted uses

```python
# Configurable via env or settings:
LUNA_STORAGE_PROVIDER=local       # OSS default
LUNA_STORAGE_PROVIDER=s3          # Hosted; uses R2

LUNA_STORAGE_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com
LUNA_STORAGE_S3_BUCKET=luna-service-prod
LUNA_STORAGE_S3_PREFIX=tenant/user_abc/
LUNA_STORAGE_S3_ACCESS_KEY=<scoped>
LUNA_STORAGE_S3_SECRET_KEY=<scoped>
```

Self-hosters get an upgrade: they can now point at any S3-compatible store (S3, Minio, Backblaze) for their files. We get the abstraction we need for hosted.

#### 2. Pluggable vault key source

Today: `LUNA_VAULT_MASTER_KEY` is a literal env var.

Tomorrow: an interface that supports literal env, AWS KMS, GCP KMS, HashiCorp Vault, or a derivation function.

```python
LUNA_VAULT_KEY_SOURCE=env             # OSS default (current behavior)
LUNA_VAULT_KEY_SOURCE=kms             # AWS/GCP KMS reference
LUNA_VAULT_KEY_SOURCE=derived         # Hosted: derive from header + root
```

Self-hosters who want enterprise-grade KMS get it. We get the per-tenant derivation we need.

#### 3. `file_metadata` table in Postgres

A core table that indexes files regardless of where they live (Volume or R2). Already implicit in Luna's design; making it explicit means plugins can query "all my files" without scanning multiple stores.

Schema:
```sql
CREATE TABLE file_metadata (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT,                 -- /workspace/... if on Volume
    blob_key TEXT,             -- R2 key if in object store
    size BIGINT,
    mime_type TEXT,
    created_by TEXT,           -- 'user' | 'agent'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    metadata JSONB             -- arbitrary plugin data
);
```

Luna tools query this for listing/searching; the actual file content lives in the appropriate tier.

### Changes NOT needed in Luna OSS

- No `tenant_id` columns anywhere in Luna's DB tables (search_path handles this transparently)
- No multi-tenant routing logic (control plane handles all routing)
- No knowledge that other tenants exist
- No changes to the chat UI, approval engine, MCP plugin, or any user-facing component

Luna OSS continues to think it's a single-tenant local agent. The deployment layer makes it multi-tenant from outside.

---

## What This Architecture Doesn't Solve (Yet)

Honest about limitations:

| Limitation | When It Matters | Future Solution |
|-----------|----------------|-----------------|
| **Cross-region latency for global users** | User in Singapore, infra in us-east | Multi-region: per-tenant region assignment, Fly Machines + Render Postgres in the nearest region (Render also offers Frankfurt and Singapore Postgres) |
| **Volume tied to specific Fly host** | If we need to move a Luna across regions | Volume snapshot to R2, restore in target region (~1-5 min, planned downtime) |
| **Postgres single-cluster scaling limits** | Beyond ~10-50K tenants on one cluster | Shard by tenant_id range across multiple Render Postgres instances (or migrate to a serverless-Postgres provider at that scale) |
| **Backup/restore granularity per tenant** | Compliance: "export my data" | Already supported via schema dump + R2 prefix copy |
| **Cold-storage tiering of old data** | Years of conversation history accumulate | Lifecycle rule: archive conversations >1 year old to R2, keep Postgres index |
| **Cross-tenant analytics** | Operator visibility | Separate analytics warehouse (Clickhouse/Snowflake) ingests anonymized events |

None of these are blockers for v1. All are solvable within the current architecture.

---

## Summary

Three tiers, each for what it's best at:

1. **Postgres** = the brain (queryable, transactional, audit-secure, with pgvector for memory)
2. **R2** = the warehouse (cheap, durable, web-served, shared assets)
3. **Volume** = the workshop (real filesystem for code, venvs, executables)

Per-tenant isolation:
- **Postgres:** schema + role per tenant (Luna's code unchanged via search_path)
- **R2:** prefix per tenant with scoped credentials
- **Volume:** physically dedicated per Machine
- **Vault key:** derived per tenant from KMS root

Unit economics: ~$0.50/user/month for all file storage at any scale, with headroom for healthy margins on our pricing tiers.

OSS impact: zero invasive changes. A handful of small, generally-useful additions (pluggable storage backend, pluggable vault key source, explicit file_metadata table) that benefit self-hosters too.

This is the storage substrate everything else is built on. Get this right and the rest of the platform falls into place. Get this wrong (one tier doing everything) and we either bleed money or break code execution. The hybrid is what makes Luna Service work.
