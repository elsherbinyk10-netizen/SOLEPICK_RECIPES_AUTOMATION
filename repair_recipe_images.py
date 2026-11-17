#!/usr/bin/env python3
"""Repair low-quality or disallowed packaged-product images on published SolePick recipes."""
import json
import os
import re
import sys
from pathlib import Path

import recipe_worker as worker
from image_quality import inspect_image_url, is_high_quality_image

MAX_REPAIRS = max(1, min(50, int(os.environ.get("MAX_IMAGE_REPAIRS", "10"))))


def is_recipe_article(article):
    tags = {str(tag).strip().lower() for tag in article.get("tags", [])}
    body = str(article.get("body") or "").lower()
    has_recipe_sections = ("ingredients" in body and ("instructions" in body or "method" in body))
    recipe_tags = bool(tags & {"recipe", "recipes", "dinner", "lunch", "breakfast", "quick & easy", "fresh & green", "comfort food"})
    return has_recipe_sections or recipe_tags


def requested_image_handles():
    raw = os.environ.get("TARGET_IMAGE_HANDLES", "").strip()
    if not raw:
        event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
        if event_path and Path(event_path).is_file():
            try:
                event = json.loads(Path(event_path).read_text(encoding="utf-8"))
                message = str((event.get("head_commit") or {}).get("message") or "")
                match = re.search(r"\[repair-image:([a-z0-9,-]+)\]", message)
                if match:
                    raw = match.group(1)
            except (OSError, ValueError, TypeError):
                raw = ""
    if not raw:
        return None
    handles = [item.strip() for item in raw.split(",") if item.strip()]
    if len(handles) != len(set(handles)):
        raise RuntimeError("TARGET_IMAGE_HANDLES contains duplicate handles.")
    return handles


def main():
    blog_id = worker.resolve_recipe_blog()
    articles = worker.existing_articles(blog_id)
    published = [a for a in articles.values() if a.get("isPublished")]
    recipe_articles = [a for a in published if is_recipe_article(a)]
    targets = requested_image_handles()
    if targets:
        by_handle = {str(a.get("handle") or ""): a for a in recipe_articles}
        missing = [handle for handle in targets if handle not in by_handle]
        if missing:
            raise RuntimeError("Requested published recipe article(s) not found: " + ", ".join(missing))
        recipe_articles = [by_handle[handle] for handle in targets]
        print("TARGETED IMAGE REPAIR: " + ", ".join(targets))
    print(f"Published articles scanned: {len(published)}; recipe articles selected: {len(recipe_articles)}")

    catalogue = {item["slug"]: item for item in worker.load_recipes()}
    repaired = 0
    for article in recipe_articles:
        handle = str(article.get("handle") or "")
        image = article.get("image") or {}
        current_url = str(image.get("url") or "")
        current_alt = str(image.get("altText") or "")
        quality = inspect_image_url(current_url)
        retail = worker._is_retail_product_image(current_alt, current_url)
        if is_high_quality_image(quality) and not retail:
            print(f"PASS {handle} | {quality['width']}x{quality['height']} | edge={quality['edge_variance']}")
            continue

        reason = "disallowed packaged/retail image" if retail else str(quality)
        print(f"REPAIR NEEDED {handle} | {reason}")
        if repaired >= MAX_REPAIRS:
            print("Batch repair limit reached; remaining low-quality images will be handled by the next scheduled batch.")
            break

        recipe_source = catalogue.get(handle)
        if not recipe_source:
            raise RuntimeError("No source recipe found in recipes.json for targeted handle: " + handle)
        recipe = worker.add_recipe_category_tags(worker.make_recipe_specific(recipe_source))

        try:
            video = worker.find_verified_recipe_video(recipe)
            if targets:
                try:
                    # Prefer the exact verified dish-video thumbnail for a targeted correction.
                    candidate = worker.youtube_thumbnail_for(recipe, video, published)
                except RuntimeError as thumbnail_error:
                    print(f"EXACT VIDEO THUMBNAIL UNAVAILABLE {handle} | {thumbnail_error}; trying licensed dish photo.")
                    candidate = worker.generate_recipe_image(recipe, published)
            else:
                try:
                    candidate = worker.generate_recipe_image(recipe, published)
                except RuntimeError as commons_error:
                    print(f"COMMONS REPLACEMENT UNAVAILABLE {handle} | {commons_error}")
                    candidate = worker.youtube_thumbnail_for(recipe, video, published)
            candidate = worker.featured_image_for(recipe, candidate)
            candidate_quality = inspect_image_url(candidate.get("url"))
            if not is_high_quality_image(candidate_quality):
                raise RuntimeError(f"Replacement photo failed image validation: {candidate_quality}")
            if worker._is_retail_product_image(
                candidate.get("title"), candidate.get("url"),
                {"ImageDescription": {"value": candidate.get("altText", "")}}
            ):
                raise RuntimeError("Replacement image matched the packaged/retail product filter.")
        except RuntimeError as error:
            print(f"DEFERRED {handle} | no verified replacement image/video pair yet | {error}")
            continue

        published_handles = {
            str(item.get("handle") or "") for item in published if item.get("isPublished")
        }
        article_payload = worker.recipe_article_update_input(
            recipe, video, published_handles, candidate
        )
        mutation = """mutation UpdateRecipeImage($id: ID!, $article: ArticleUpdateInput!) {
          articleUpdate(id: $id, article: $article) {
            article { id title handle isPublished body image { url altText } }
            userErrors { field message }
          }
        }"""
        result = worker.graphql(mutation, {"id": article["id"], "article": article_payload})
        update = result.get("articleUpdate") or {}
        if update.get("userErrors"):
            raise RuntimeError("Shopify rejected image/body update for " + handle + ": " + json.dumps(update["userErrors"]))
        saved = update.get("article") or {}
        if not saved.get("isPublished") or not (saved.get("image") or {}).get("url"):
            raise RuntimeError("Shopify did not confirm the image update for " + handle)
        worker.verify_published_article(saved, recipe, video)
        verified = inspect_image_url(saved["image"]["url"])
        if not is_high_quality_image(verified):
            raise RuntimeError(f"Shopify saved image failed final validation for {handle}: {verified}")
        if worker._is_retail_product_image(saved["image"].get("altText"), saved["image"]["url"]):
            raise RuntimeError("Shopify saved a disallowed packaged/retail image for " + handle)
        # Shopify may normalize the featured-image URL to its CDN in the
        # article response; JSON-LD retains the verified source URL we supplied.
        if candidate["url"] not in str(saved.get("body") or ""):
            raise RuntimeError("Updated article JSON-LD/body does not reference the verified source image for " + handle)

        print(
            f"REPAIRED {handle} | {verified['width']}x{verified['height']} | "
            f"source={candidate.get('source_type')} | featured={saved['image']['url']}"
        )
        repaired += 1
        published = [item for item in published if item.get("id") != article.get("id")]
        published.append(saved)

    print(f"IMAGE REPAIR SUMMARY: repaired={repaired}; recipe_articles={len(recipe_articles)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("IMAGE REPAIR FAILED: " + str(exc), file=sys.stderr)
        raise
