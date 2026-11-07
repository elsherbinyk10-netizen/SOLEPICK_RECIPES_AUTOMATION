# SolePick Recipes Automation

Daily Shopify recipe publishing for SolePick Recipes, with a verified YouTube recipe-video check before an article is published.

## Daily schedule and duplicate protection
- The workflow has seasonal primary triggers plus same-day recovery triggers at `0 7 * * *`, `0 8 * * *`, `0 9 * * *`, and `0 10 * * *` UTC. The worker accepts the 10:00 AM Cairo primary trigger and later recovery attempts; Shopify's Cairo-day guard prevents duplicate posts.
- Before publishing, the worker checks Shopify article publication dates in `Africa/Cairo`. If today's article already has a saved embedded player, it skips the run to prevent a duplicate.
- If today's article exists but its saved body is missing the embedded player, the worker repairs that existing article instead of creating another recipe.
- The publishing command retries up to three times after failures. Shopify is re-checked on each attempt, and the Cairo-day guard prevents duplicate posts after an uncertain API response.
- GitHub can delay scheduled runs; the schedule targets 10:00 AM Cairo but cannot guarantee the exact start minute.

## Recipe video checks
- No YouTube API key is required. The worker searches public YouTube results with `yt-dlp`, rejects titles that do not match the recipe's named protein and dish format, and checks each candidate with YouTube oEmbed before accepting an embeddable video. Public search can be rate-limited; when no safe match can be verified, the recipe is skipped and no mismatched video is published.
- Recipe photos are searched automatically on Wikimedia Commons. The worker prefers public-domain/CC0 results, rejects reused or weakly matched images, and supplies descriptive alt text. If no sufficiently relevant image is found, that recipe is skipped rather than published with a mismatched photo. Shopify references the public image URL; the worker does not upload or host the photo on Shopify.
- If no sufficiently close match exists or the video is unavailable/private/not embeddable, the run fails with a `VIDEO REVIEW REQUIRED` or `VIDEO UNAVAILABLE` message. Review the run logs and select a suitable video rather than forcing a weak match.
- The responsive iframe is placed before the YouTube fallback link. After creating or updating an article, the worker checks Shopify's returned saved body for the iframe, expected embed URL, visible heading, Ingredients section, and Instructions section. If the saved iframe is missing on the same Cairo day, the worker repairs that article instead of reporting a false success or publishing a duplicate.
- A saved iframe does not guarantee that every browser, network, or video owner's settings will permit playback. The live article should still be spot-checked on mobile after a publishing run.

## Required GitHub Actions secrets
- `SHOPIFY_STORE_DOMAIN`: the store's `*.myshopify.com` domain.
- `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET`: Shopify app credentials with article/blog permissions.
- `SHOPIFY_BLOG_ID`: retained for backward compatibility only. The worker now discovers the dedicated Shopify blog with handle `recipes` and creates it if missing, so a stale ID pointing to the old News blog cannot misroute recipes.

Never put credentials in repository files.
The daily publisher is pinned to the verified SolePick Shopify domain `0mxbjk-cz.myshopify.com`; it must never use the Valuted News store domain.

## Production publishing trigger
A commit whose message includes `[publish-daily-recipe]` runs the same validated production publisher used by the scheduled workflow. It resolves the Shopify blog by the `recipes` handle, applies the Cairo-day cap of up to three verified recipes, and skips candidates that fail recipe, photo, video, or Shopify verification.

## Tests
Run:
```bash
python -m unittest discover -s tests -v
python recipe_worker.py --dry-run
```

The dry run selects a recipe offline and does not call Shopify. The workflow runs unit tests before attempting publication and retries publishing up to three times. A green workflow now confirms Shopify returned the embedded player markup in the saved article body, but it cannot guarantee that every public browser successfully plays the third-party video. Spot-check the published article URL on mobile after a real run.

## Daily category maintenance
- Every scheduled publishing run first synchronizes canonical category tags across already-published recipe articles whose handles exist in `recipes.json`.
- The four canonical tags are `quick-and-easy`, `fresh-and-green`, `sweet-things`, and `comfort-food`. Existing non-category tags are preserved; unrelated editorial posts are not modified.
- Category assignment is recalculated from the reviewed recipe title, description, tags, and prep/cook times. Vegetarian pasta is not automatically treated as Fresh & Green.
- Newly published recipes receive the same category tags on creation. Existing-article updates also send category tags explicitly.
- When the reviewed catalogue is exhausted, the publisher first checks fresh trend-matched patterns, then replenishes from unused, fully authored evergreen recipes. This fallback does not invent ingredients or claim an evergreen recipe is trending; every candidate still passes the normal instruction, verified-video, verified-image and Shopify read-back gates.
- A recipe is published only after a title-compatible YouTube creator video passes live oEmbed verification and the saved Shopify article is read back with its responsive iframe. A failed video/photo/recipe-quality check skips that candidate; it never inserts an unrelated video.
- The connected Shopify store was verified as `0mxbjk-cz.myshopify.com` with primary domain `solepick.site` and timezone `Africa/Cairo`.

## Recipe library
The worker rotates through `recipes.json`, skips recipes already published by handle, and stops when no eligible recipe remains. Trend-matched candidates are generated only from narrow, pre-authored complete-recipe patterns and still pass all normal instruction, image, video and Shopify checks; unsupported trends never become invented recipes. Review recipe accuracy, food safety, allergens, and any generated or third-party media before scaling the library.

## ElevenLabs video dubbing (manual, safe-by-default)
- The GitHub Actions workflow `.github/workflows/elevenlabs-dubbing.yml` can generate target-language video versions using the `ELEVENLABS_API_KEY` Actions secret and FFmpeg.
- Run it from **Actions → SolePick ElevenLabs Video Dubbing → Run workflow**. Supply a public direct HTTPS video-file URL that you own or are licensed to dub, source language (default `en`), and target codes (default `ar,es,fr`).
- Outputs are uploaded as the `solepick-dubbed-videos` workflow artifact for 7 days. Download and review each video before use.
- This does not scrape or download YouTube/social embeds, publish anything to Shopify, or alter the live theme. The normal daily recipe publisher remains a separate workflow.
- A source video URL is required to run the dubbing API. Saving the API key and installing the workflow does not itself generate dubbed media. Do not use third-party videos without permission.


## Published recipe video audit

The SolePick Daily Recipe Publishing workflow supports a guarded video audit. Run it manually with the `Audit missing videos` option, or use a reviewed push commit containing `[audit-repair-videos]`. The worker checks every published article in the Recipes blog, repairs missing embedded players in place using the verified video-source and embeddability checks, then re-reads Shopify before applying the normal Cairo-day duplicate guard. If today's recipe has not already been published, the same run may publish one eligible recipe; otherwise it does not create a duplicate. Articles whose video or image fails validation remain unchanged and are reported as unresolved.


<!-- Embedded-video audit trigger: 2026-11-07 -->


## One-recipe guarded recovery
A targeted recovery can be triggered with a reviewed `[publish-recipes:recipe-slug]` commit marker alongside `[publish-daily-recipe]`. The workflow still runs the full test suite, published-video audit, recipe-specific instruction checks, live creator/video embeddability verification, dish-photo quality and duplicate-image checks, Shopify duplicate protection, and read-after-write publication verification. A failed media or quality gate holds the recipe; no gate is bypassed.


<!-- One-recipe guarded recovery trigger: image-source and workflow-selection fixes are now in place. -->


<!-- Retry after image provenance diagnostics. -->
