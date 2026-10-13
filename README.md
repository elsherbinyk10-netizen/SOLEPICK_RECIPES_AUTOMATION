# SolePick Recipes Automation

Daily Shopify recipe publishing for SolePick Recipes, with a verified YouTube recipe-video check before an article is published.

## Daily schedule and duplicate protection
- The workflow has two seasonal cron triggers: `0 7 * * *` during Cairo UTC+3 and `0 8 * * *` during Cairo UTC+2. Both map to 10:00 Cairo time.
- The worker reads the cron that actually triggered the run and ignores the non-seasonal trigger. It does not decide based on the delayed runner's current hour.
- Before publishing, the worker checks Shopify article publication dates in `Africa/Cairo`. If an article was already published that Cairo day, it skips the run to prevent a second recipe.
- GitHub may delay scheduled runs. The daily guard is the final protection against duplicate publications.

## Recipe video checks
- Add the repository secret `YOUTUBE_API_KEY` (YouTube Data API v3 enabled). If it is missing or the API fails, publication stops rather than reporting success without a video.
- For each selected recipe, the worker searches YouTube using the recipe title, checks title overlap, then verifies that the video still exists, is public, and is embeddable.
- If no sufficiently close match exists or the video is unavailable/private/not embeddable, the run fails with a `VIDEO REVIEW REQUIRED` or `VIDEO UNAVAILABLE` message. Review the run logs and select a suitable video rather than forcing a weak match.
- The selected video URL and responsive embed are added to the Shopify article body. Confirm the embed renders on the public article because Shopify/theme sanitization and third-party playback restrictions can only be fully verified in a browser.

## Required GitHub Actions secrets
- `SHOPIFY_STORE_DOMAIN`: the store's `*.myshopify.com` domain.
- `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET`: Shopify app credentials with article/blog permissions.
- `SHOPIFY_BLOG_ID`: the target blog's GraphQL ID.
- `YOUTUBE_API_KEY`: YouTube Data API v3 key with YouTube Data API enabled.

Never put credentials in repository files.

## Tests
Run:
```bash
python -m unittest discover -s tests -v
python recipe_worker.py --dry-run
```

The dry run selects a recipe offline and does not call Shopify. The scheduled workflow runs unit tests before attempting publication. A green GitHub workflow is not enough by itself to prove a public video played: verify the published article URL and video playback after a real run.

## Recipe library
The worker rotates through `recipes.json`, skips recipes already published by handle, and stops when no eligible recipe remains. It does not invent new recipes from the internet. Review recipe accuracy, food safety, allergens, and any generated or third-party media before scaling the library.
