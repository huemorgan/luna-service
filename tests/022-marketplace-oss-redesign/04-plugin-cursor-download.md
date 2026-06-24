# 04 — Cursor plugin-dev kit download

**Goal:** the Marketplaces page offers a downloadable Cursor environment for
building plugins, served from `marketplaces.com.ai` via a branded redirect.

## Steps
1. Load `/products/marketplace`, scroll to "Build plugins" / "Luna Plugin Studio
   for Cursor".
2. Confirm copy describes the kit (SDK + scaffold + test harness + Cursor config)
   and notes it's "Updated on marketplaces.com.ai".
3. The download button points at `/downloads/luna-plugin-cursor.zip`.
4. Backend check: `curl -sI https://luna-service.onrender.com/downloads/luna-plugin-cursor.zip`
   returns `302` with `Location:` on `marketplaces.com.ai`.

## Pass
- Download button present with correct copy.
- `/downloads/luna-plugin-cursor.zip` 302-redirects to the marketplaces.com.ai zip.
