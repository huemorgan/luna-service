# 081 — Roll out verified long-task Luna image without losing image history

## Problem

The production image defaults still pin older Playbooks, Scheduler, MCP, and Web Access releases and omit DB. Luna `main` is 0.92.057 while 42 running agents remain on older images. The existing `rollout_image.py promote` helper deletes the previous main image record after migration, preventing an easy rollback and conflicting with the service's data-preservation rule.

## Goal

Build Luna 0.92.057 with the complete 19-plugin default set, including the five verified marketplace updates and DB; migrate every running agent; retain the prior image record and registry tag for rollback; verify actual Fly machine images.

## Work

1. Record the live marketplace versions and hashes for all 19 selected plugins in the `plugin-set.toml` fallback. Keep the admin image defaults as the live source of truth and pin the five updated plugins there before build.
2. Add a `promote-preserve` command to the headless rollout helper that composes the existing `set_main_image` and `migrate_all_machines` APIs. Leave the existing legacy `promote` command unchanged. Retain old image rows.
3. Test plugin selection and the preserved-image promotion path, build and deploy the service helper, then build Luna 0.92.057.
4. Confirm the image's plugin-set snapshot contains all 19 expected pins. Run a canary where practical, switch main, migrate the fleet, and use `verify` to ask Fly about every machine.
5. Check the agent health and long-task smoke path; record exact results and any remaining limitations in the execution summary.

## Data and rollback

Do not delete image records, machine volumes, tenant data, or old registry tags. If migration fails, keep the previous image available and retry or return affected machines to it. No automatic deletion on success.

## Acceptance

- Marketplace artifact hashes match the 19 image pins; the five new plugin versions are used and DB is included.
- Luna image 0.92.057 builds successfully and the image snapshot is the intended 19-plugin set.
- Every extant Fly machine reports the new image tag; no agent data is lost; the previous main image remains as a built, non-main row.
- Source change, tests, and operational evidence are committed on service `main`.
