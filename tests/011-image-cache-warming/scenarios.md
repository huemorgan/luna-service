# E2E Scenarios — Image Cache Warming

## Scenario 1: Warm cache indicator on image cards

1. Navigate to `/admin/images`
2. Look at each built image card
3. **Pass if**: each card shows either "Cache warm" with a timestamp or "Cache cold"
4. **Fail if**: no cache indicator visible

## Scenario 2: Manual warm cache button

1. Navigate to `/admin/images`
2. Find a built image that shows "Cache cold"
3. Click "Warm Cache" button
4. **Pass if**: button shows loading state, then indicator changes to "Cache warm"
5. **Fail if**: button does nothing or errors without feedback

## Scenario 3: Auto-warm on promote to main

1. Navigate to `/admin/images`
2. Promote a built image to main (click "Set as Main")
3. Wait a few seconds
4. **Pass if**: the promoted image's cache status updates to "Cache warm"
5. **Fail if**: cache stays cold after promotion

## Scenario 4: Agent detail shows image version

1. Navigate to `/dashboard`
2. Click on a running agent to open its detail page
3. Look at the Compute section
4. **Pass if**: image version is displayed (e.g. "v0.01.007")
5. **Fail if**: no version info in the compute card
