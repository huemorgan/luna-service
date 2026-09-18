# Fleet rollout checks

1. Before build, inspect the live official plugin index, admin defaults, and the committed fallback file. Confirm the 19 selected names, versions, and SHA-256 values match. Confirm the five new artifacts download with those hashes.
2. Build Luna `main` 0.92.057. Read the build record and plugin-set snapshot. Pass only if built status and all 19 pins are exact.
3. Exercise `promote-preserve` on the built image and inspect old/new image rows. Pass if the new image becomes main, every running machine migrates, and the old image row remains.
4. Run `verify --version 0.92.057` and inspect machine states. Pass only if every existing machine reports the expected tag. Check the control-plane agent counts separately for no-machine records.
5. Open the hosted Luna admin image page and a running agent conversation. Confirm the new main image and a basic plugin-backed long-task interaction work without obvious UI or runtime regressions. Record actual evidence and limits; do not infer fleet health from build success alone.
