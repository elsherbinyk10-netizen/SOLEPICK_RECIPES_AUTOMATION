#!/usr/bin/env python3
"""Repair low-resolution/soft featured images on existing published SolePick recipes."""
import json
import os
import sys

import recipe_worker as worker
from image_quality import inspect_image_url, is_high_quality_image

BLOG_ID = os.environ.get("SHOPIFY_BLOG_ID", "").strip()
MAX_REPAIRS = max(1, min(50, int(os.environ.get("MAX_IMAGE_REPAIRS", "10"))))


def is_recipe_article(article):
    tags = {str(tag).strip().lower() for tag in article.get("tags", [])}
    body = str(article.get("body") or "").lower()
    has_recipe_sections = ("ingredients" in body and ("instructions" in body or "method" in body))
    recipe_tags = bool(tags & {"recipe", "recipes", "dinner", "lunch", "breakfast", "quick & easy", "fresh & green", "comfort food"})
    return has_recipe_sections or recipe_tags


def main():
    if not BLOG_ID:
        raise RuntimeError("SHOPIFY_BLOG_ID is required.")
    articles = worker.existing_articles(BLOG_ID)
    published = [a for a in articles.values() if a.get("isPublished")]
    recipe_articles = [a for a in published if is_recipe_article(a)]
    print(f"Published articles scanned: {len(published)}; recipe articles identified: {len(recipe_articles)}")
    repaired = 0
    skipped = 0
    for article in recipe_articles:
        image = article.get("image") or {}
        current_url = str(image.get("url") or "")
        quality = inspect_image_url(current_url)
        if is_high_quality_image(quality):
            print(f"PASS {article['handle']} | {quality['width']}x{quality['height']} | edge={quality['edge_variance']}")
            continue
        print(f"REPAIR NEEDED {article['handle']} | {quality}")
        if repaired >= MAX_REPAIRS:
            print("Batch repair limit reached; remaining low-quality images will be handled by the next scheduled batch.")
            break
        try:
            candidate = worker.generate_recipe_image({"title": article["title"], "slug": article["handle"]}, published)
            candidate_quality = inspect_image_url(candidate.get("url"))
            if not is_high_quality_image(candidate_quality):
                raise RuntimeError(f"Replacement photo did not pass image quality validation: {candidate_quality}")
        except RuntimeError as error:
            print(f"DEFERRED {article['handle']} | no verified replacement yet | {error}")
            continue
        mutation = """mutation UpdateRecipeImage($id: ID!, $article: ArticleUpdateInput!) {
          articleUpdate(id: $id, article: $article) {
            article { id title handle isPublished image { url altText } }
            userErrors { field message }
          }
        }"""
        result = worker.graphql(mutation, {"id": article["id"], "article": {"image": candidate}})
        update = result.get("articleUpdate") or {}
        if update.get("userErrors"):
            raise RuntimeError("Shopify rejected image update for " + article["handle"] + ": " + json.dumps(update["userErrors"]))
        saved = update.get("article") or {}
        if not saved.get("isPublished") or not (saved.get("image") or {}).get("url"):
            raise RuntimeError("Shopify did not confirm the image update for " + article["handle"])
        verified = inspect_image_url(saved["image"]["url"])
        if not is_high_quality_image(verified):
            raise RuntimeError(f"Shopify saved image failed final validation for {article['handle']}: {verified}")
        print(f"REPAIRED {article['handle']} | {verified['width']}x{verified['height']} | {saved['image']['url']}")
        repaired += 1
        published = [a for a in published if a["id"] != article["id"]]
        published.append(saved)
    print(f"IMAGE REPAIR SUMMARY: repaired={repaired}; already_good_or_skipped={skipped}; recipe_articles={len(recipe_articles)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("IMAGE REPAIR FAILED: " + str(exc), file=sys.stderr)
        raise
