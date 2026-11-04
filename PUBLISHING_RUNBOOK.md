# SolePick recipe publishing recovery

- Daily scheduled runs retain the Cairo-time schedule in `.github/workflows/daily-recipes.yml`.
- Each normal run may publish up to three recipes, but only after the full unittest and media quality gates pass.
- A targeted publishing commit uses `[publish-daily-recipe]` and `[publish-recipes:slug-one,slug-two]` in its commit message.
- A target list is validated against `recipes.json`; already-published recipes remain excluded by Shopify article status.
- Image relevance, image uniqueness, video verification, captions, duplicate protection and Shopify authentication remain mandatory gates.
- One-time duplicate-guard bypass remains limited to explicit manual workflow dispatch.
- Workflow concurrency keys separate explicit recovery runs from scheduled runs so stale skipped pushes cannot block a new recovery attempt.

- 2026-11-04: Updated the stale auth unit test to mock the current Shopify client-credentials exchange; this commit intentionally triggers today's three-recipe media-gated recovery batch.

- Daily trend updates now save new complete trend-matched recipes back into recipes.json; the workflow commits those library additions after the worker exits, including when media checks correctly defer publication.
- Video discovery now retries official Food Network channel search through public Invidious-compatible indexes when GitHub-hosted YouTube search is bot-challenged. The official channel ID, live title, oEmbed availability and embed response checks remain required.
- The recipe library includes additional reviewed trend patterns for smash-burger tacos, chili-crisp peanut noodles, marry-me chickpeas and pesto eggs.

- 2026-11-04: Final image-gate fix preserves verified thumbnail provenance through the second validation at the Shopify create/update boundary. Trusted official video publishers now include Food Network, Tasty, Jamie Oliver and Allrecipes; exact channel ID, matching oEmbed author/title and live embeddability remain mandatory.
