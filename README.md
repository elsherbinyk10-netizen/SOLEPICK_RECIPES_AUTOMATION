# SolePick Recipes Automation

Starter GitHub Actions project for creating daily **draft** recipe articles in a Shopify blog. No paid AI API, Vercel, or GNews required.

## Safety defaults
- Creates Shopify drafts only; it never publishes live articles.
- Uses a stable handle and checks the blog to prevent duplicates.
- Review recipe instructions, food safety, allergens, and nutrition before publishing.
- Never put credentials in repository files.

## Setup
1. Upload the ZIP contents to the root of your GitHub repository, preserving `.github/workflows/`.
2. Open **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `SHOPIFY_STORE_DOMAIN`: domain only, e.g. `example.myshopify.com`.
   - `SHOPIFY_ADMIN_ACCESS_TOKEN`: Admin API token with blog/article read and create permissions.
   - `SHOPIFY_BLOG_ID`: GraphQL ID, e.g. `gid://shopify/Blog/1234567890`.
3. Enable GitHub Actions if prompted.
4. Run **Actions → SolePick Daily Recipe Drafts → Run workflow** manually.
5. Confirm the draft appears in Shopify Admin.

## Schedule
Daily at 07:15 UTC (10:15 Egypt time when UTC+3). GitHub may delay scheduled runs.

## Local test
Requires Python 3.11+:
```bash
python -m unittest discover -s tests -v
python recipe_worker.py --dry-run
```

## Important
This starter rotates through the recipes in `recipes.json`; it does not generate a brand-new recipe from the internet every day. Expand and fact-check the recipe library. Live publishing is deliberately disabled.
