# SolePick recipe publishing recovery

- Daily scheduled runs retain the Cairo-time schedule in `.github/workflows/daily-recipes.yml`.
- Each normal run may publish up to three recipes, but only after the full unittest and media quality gates pass.
- A targeted publishing commit uses `[publish-daily-recipe]` and `[publish-recipes:slug-one,slug-two]` in its commit message.
- A target list is validated against `recipes.json`; already-published recipes remain excluded by Shopify article status.
- Image relevance, image uniqueness, video verification, captions, duplicate protection and Shopify authentication remain mandatory gates.
- One-time duplicate-guard bypass remains limited to explicit manual workflow dispatch.
- Workflow concurrency keys separate explicit recovery runs from scheduled runs so stale skipped pushes cannot block a new recovery attempt.

- 2026-11-04: Updated the stale auth unit test to mock the current Shopify client-credentials exchange; this commit intentionally triggers today's three-recipe media-gated recovery batch.
