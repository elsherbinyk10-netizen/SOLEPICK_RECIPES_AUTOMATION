# SolePick Recipes Automation

Daily Shopify recipe publishing for SolePick Recipes, with a verified YouTube recipe-video check before an article is published.

## Daily schedule and duplicate protection
- The workflow has two UTC triggers: `0 7 * * *` and `0 8 * * *`. The worker compares the trigger with Cairo's current UTC offset and ignores the off-season trigger, targeting 10:00 AM Cairo time year-round.
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
- `SHOPIFY_BLOG_ID`: the target blog's GraphQL ID.

Never put credentials in repository files.

## Tests
Run:
```bash
python -m unittest discover -s tests -v
python recipe_worker.py --dry-run
```

The dry run selects a recipe offline and does not call Shopify. The workflow runs unit tests before attempting publication and retries publishing up to three times. A green workflow now confirms Shopify returned the embedded player markup in the saved article body, but it cannot guarantee that every public browser successfully plays the third-party video. Spot-check the published article URL on mobile after a real run.

## Recipe library
The worker rotates through `recipes.json`, skips recipes already published by handle, and stops when no eligible recipe remains. It does not invent new recipes from the internet. Review recipe accuracy, food safety, allergens, and any generated or third-party media before scaling the library.

## ElevenLabs video dubbing (manual, safe-by-default)
- The GitHub Actions workflow `.github/workflows/elevenlabs-dubbing.yml` can generate target-language video versions using the `ELEVENLABS_API_KEY` Actions secret and FFmpeg.
- Run it from **Actions → SolePick ElevenLabs Video Dubbing → Run workflow**. Supply a public direct HTTPS video-file URL that you own or are licensed to dub, source language (default `en`), and target codes (default `ar,es,fr`).
- Outputs are uploaded as the `solepick-dubbed-videos` workflow artifact for 7 days. Download and review each video before use.
- This does not scrape or download YouTube/social embeds, publish anything to Shopify, or alter the live theme. The normal daily recipe publisher remains a separate workflow.
- A source video URL is required to run the dubbing API. Saving the API key and installing the workflow does not itself generate dubbed media. Do not use third-party videos without permission.
