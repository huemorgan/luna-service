# Luna Submodule Change Process

The `luna/` directory is a git submodule pointing at the Luna OSS repo (`huemorgan/luna`). It has its own roadmap, plans, and versioning. **Never** make ad-hoc edits.

## When this skill applies

Any time you need to modify a file inside `luna/` — code, config, plugins, UI, tests, plans, anything.

## Required steps

1. **Get a plan number from the user.** Ask: "What plan number should I use for this Luna change?" Do not pick one yourself. The user tracks the numbering.

2. **Create a plan folder** inside `luna/plans/` named `{number}-luna-service-{short-description}/`. The folder name **must** contain `-luna-service` to mark it as originating from the service project. Example: `luna/plans/005.919-luna-service-fix-missing-plugins/`

3. **Write `PLAN.md`** inside that folder with:
   - What is being changed and why
   - Which files are affected
   - Any risk or migration notes
   - Expected version bump (if any)

4. **Make the code changes** inside `luna/`.

5. **Bump the version** in both places:
   - `luna/luna/__init__.py` (`__version__`)
   - `cloud/.luna-version` (must match)

6. **Commit inside the submodule first** — `cd luna && git add . && git commit && git push origin main`

7. **Then commit the submodule pointer in luna-service** — `cd .. && git add luna cloud/.luna-version && git commit && git push origin main`

8. **Rebuild the image** from the admin panel (Admin > Luna Images > Check for Updates > Build).

9. **Set as Main + Migrate All** once the build succeeds.

## Rules

- The plan folder name **must** include `-luna-service` in it.
- Never skip the plan. Even a one-line fix gets a plan.
- Never force-push to the luna repo.
- If the change touches `luna_serve.py` plugin loading, list every plugin being added/removed in the plan.
