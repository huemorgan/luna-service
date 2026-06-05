# E2E Scenarios — 009 GitHub Version Check

## Scenario 1: Check for Updates shows live version

1. Go to `https://luna.com.ai/admin/images`
2. Click "Check for Updates"
3. **Expect:** spinner appears briefly, then the update banner shows
4. **Expect:** "Submodule version" label shows the live version from GitHub
   (should match what `luna/__init__.py` on GitHub `main` says)
5. **Expect:** "Latest built" shows the most recent built image version
6. **Expect:** if they differ, "Build X.Y.Z" button is visible
7. **Expect:** if they match, "Up to date" badge is visible

## Scenario 2: API failure falls back gracefully

1. This is a code-path test — verify by reading the implementation
   that a failed GitHub API call falls back to `cloud/.luna-version`
2. The UI should still work even if GitHub is unreachable

## Scenario 3: Repeated clicks don't spam GitHub

1. Click "Check for Updates" twice within 10 seconds
2. **Expect:** both respond quickly (cached result on second call)
3. **Expect:** no rate-limit error in the response
