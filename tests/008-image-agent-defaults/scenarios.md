# E2E Scenarios — 008 Image Agent Defaults

## Scenario 1: Navigate to image config

1. Go to `https://luna.com.ai/admin/images`
2. Click the `>` chevron on the main image card
3. **Expect:** page navigates to `/admin/images/{id}`
4. **Expect:** page shows image build info (version, status, SHA)
5. **Expect:** four config sections visible: Machine, Models, Plugins, Environment
6. Click back arrow
7. **Expect:** returns to image list

## Scenario 2: Machine config

1. Navigate to the main image's config page
2. **Expect:** Machine section shows current defaults (shared, 1 CPU, 1024 MB, sjc)
3. Change CPU Kind to "performance"
4. Change Memory to "2 GB"
5. Change Region to "iad"
6. **Expect:** "Saved" indicator appears after each change
7. Refresh the page
8. **Expect:** values persist (performance, 1 CPU, 2048 MB, iad)

## Scenario 3: Models config

1. On the config page, find the Models section
2. **Expect:** Primary and Fast model rows visible with current values
3. Change the Primary model to "claude-sonnet-4-20250514"
4. **Expect:** saves successfully
5. Refresh — values persist

## Scenario 4: Plugin toggles

1. On the config page, find the Plugins section
2. **Expect:** all plugins listed with toggle switches, all ON by default
3. **Expect:** plugin_web and plugin_approvals toggles are disabled (required)
4. Toggle plugin_funnelfighters OFF
5. **Expect:** toggle switches to gray/off position, "Saved" indicator
6. Toggle plugin_brain OFF
7. Refresh the page
8. **Expect:** plugin_funnelfighters and plugin_brain are OFF, rest are ON

## Scenario 5: Environment overrides

1. On the config page, find the Environment section
2. **Expect:** empty state with "Add variable" button
3. Click "Add variable"
4. Enter key: `LUNA_FILES_MAX_SIZE_GB`, value: `10`
5. **Expect:** saves successfully
6. Add another: `LUNA_LOG_LEVEL` = `DEBUG`
7. Delete the second row
8. Refresh the page
9. **Expect:** only `LUNA_FILES_MAX_SIZE_GB=10` remains

## Scenario 6: Config shows in image list

1. Return to `/admin/images`
2. Click into a non-main image
3. **Expect:** config page loads with defaults (since no config was set on it)
4. Changes made to this image don't affect the main image's config
