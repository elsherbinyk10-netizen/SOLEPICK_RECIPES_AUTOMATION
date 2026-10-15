# SolePick Recipes Automation

Daily Shopify recipe publishing for SolePick Recipes, with a verified YouTube recipe-video check before an article is published.

## Daily schedule and duplicate protection
- The workflow has two seasonal cron triggers: `0 7 * * *` during Cairo UTC+3 and `0 8 * * *` during Cairo UTC+2. Both map to 10:00 Cairo time.
- The worker reads the cron that actually triggered the run and ignores the non-seasonal trigger. It does not decide based on the delayed runner's current hour.
- Before publishing, the worker checks Shopify article publication dates in `Africa/Cairo`. If an article was already published that Cairo day, it skips the run to prevent a second recipe.
- GitHub may delay scheduled runs. The daily guard is the final protection against duplicate publications.

## Recipe video checks
- No YouTube API key is required. The worker searches public YouTube results with `yt-dlp`, rejects titles that do not match the recipe's named protein and dish format, and checks each candidate with YouTube oEmbed before accepting an embeddable video. Public search can be rate-limited; when no safe match can be verified, the recipe is skipped and no mismatched video is published.
- Recipe photos are curated HTTPS URLs in `recipes.json`. Before publication, the worker requests the image and checks that it is reachable and returns an `image/*` content type. This validates availability, not semantic image matching; the photo URL and alt text must still be reviewed when adding recipes. Shopify references the public image URL; the worker does not upload or host the photo on Shopify.
- If no sufficiently close match exists or the video is unavailable/private/not embeddable, the run fails with a `VIDEO REVIEW REQUIRED` or `VIDEO UNAVAILABLE` message. Review the run logs and select a suitable video rather than forcing a weak match.
- The selected video URL and responsive embed are added to the Shopify article body. Confirm the embed renders on the public article because Shopify/theme sanitization and third-party playback restrictions can only be fully verified in a browser.

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

The dry run selects a recipe offline and does not call Shopify. The scheduled workflow runs unit tests before attempting publication. A green GitHub workflow is not enough by itself to prove a public video played: verify the published article URL and video playback after a real run.

## Recipe library
The worker rotates through `recipes.json`, skips recipes already published by handle, and stops when no eligible recipe remains. It does not invent new recipes from the internet. Review recipe accuracy, food safety, allergens, and any generated or third-party media before scaling the library.
