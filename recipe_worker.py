#!/usr/bin/env python3
"""Publish the scheduled SolePick recipe to the configured Shopify blog."""
import argparse
import base64
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
import urllib.parse
import re
import time
from pathlib import Path
from zoneinfo import ZoneInfo

API_VERSION = "2026-07"
CAIRO = ZoneInfo("Africa/Cairo")
RECIPES_PATH = Path(__file__).with_name("recipes.json")
ACCESS_TOKEN = None


def load_recipes():
    recipes = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    if not recipes:
        raise ValueError("recipes.json is empty")
    slugs = [r.get("slug", "") for r in recipes]
    if any(not s for s in slugs) or len(slugs) != len(set(slugs)):
        raise ValueError("Every recipe needs a unique, non-empty slug")
    required = {"title", "description", "ingredients", "instructions", "prep_minutes", "cook_minutes", "servings"}
    for recipe in recipes:
        missing = sorted(required - recipe.keys())
        if missing:
            raise ValueError(f"Recipe {recipe.get('slug', '(no slug)')} missing: {', '.join(missing)}")
        if not recipe["ingredients"] or not recipe["instructions"]:
            raise ValueError(f"Recipe {recipe['slug']} needs ingredients and instructions")
    return recipes


def esc(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _video_title_score(recipe_title, video_title):
    stop = {"recipe", "easy", "best", "how", "to", "make", "the", "with", "for", "and", "a", "an", "of", "in", "on", "quick", "simple", "delicious"}
    wanted = {x for x in re.findall(r"[a-z0-9]+", recipe_title.lower()) if x not in stop}
    found = {x for x in re.findall(r"[a-z0-9]+", video_title.lower()) if x not in stop}
    return len(wanted & found) / max(1, len(wanted))


def _video_title_is_compatible(recipe, video_title):
    """Reject videos with a different main protein or dish format before scoring similarity."""
    wanted_text = str(recipe.get("title", "")).lower()
    found_text = str(video_title or "").lower()

    protein_groups = [
        {"chicken"}, {"salmon"}, {"shrimp", "prawn", "prawns"}, {"tuna"},
        {"beef"}, {"pork"}, {"turkey"}, {"tofu"}, {"tempeh"},
        {"chickpea", "chickpeas"}, {"lentil", "lentils"}, {"egg", "eggs"}
    ]
    wanted_proteins = [group for group in protein_groups if any(term in wanted_text for term in group)]
    found_proteins = [group for group in protein_groups if any(term in found_text for term in group)]
    if wanted_proteins and not any(group in found_proteins for group in wanted_proteins):
        return False
    dish_formats = [
        {"salad"}, {"pasta"}, {"taco", "tacos"}, {"noodle", "noodles"},
        {"soup"}, {"curry"}, {"pizza"}, {"pancake", "pancakes"},
        {"parfait", "parfaits"}, {"bowl", "bowls"}, {"fajita", "fajitas"},
        {"frittata"}, {"sandwich", "sandwiches"}, {"stir-fry", "stir fry"}
    ]
    wanted_formats = [group for group in dish_formats if any(term in wanted_text for term in group)]
    if wanted_formats and not any(any(term in found_text for term in group) for group in wanted_formats):
        return False
    return True


def find_verified_recipe_video(recipe):
    """Find a relevant, publicly embeddable recipe video without a YouTube Data API key.

    yt-dlp searches YouTube's public search results; YouTube's oEmbed endpoint
    is then used as a no-key check that the selected video is publicly
    accessible and permits embedding. If a candidate cannot be verified, try
    the next candidate rather than publishing an unverified iframe.
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("Video search dependency missing: install yt-dlp in the workflow.") from None

    search_options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "socket_timeout": 20,
        "playlistend": 8,
    }
    query = recipe["title"] + " recipe"
    try:
        with yt_dlp.YoutubeDL(search_options) as ydl:
            search = ydl.extract_info("ytsearch8:" + query, download=False) or {}
    except Exception as error:
        raise RuntimeError(
            "No-API YouTube search failed. YouTube may be temporarily limiting automated search; "
            "retry later or add a manually reviewed video URL to this recipe. "
            f"Details: {type(error).__name__}"
        ) from None

    candidates = []
    for item in search.get("entries") or []:
        if not item:
            continue
        video_id = item.get("id")
        title = item.get("title") or ""
        if not video_id or not title:
            continue
        if not _video_title_is_compatible(recipe, title):
            print(f"Rejecting incompatible video title for '{recipe['title']}': {title}")
            continue
        score = _video_title_score(recipe["title"], title)
        if score >= 0.45:
            candidates.append((score, video_id, title))
    candidates.sort(reverse=True)

    for score, video_id, title in candidates:
        video_url = "https://www.youtube.com/watch?v=" + video_id
        oembed_url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({
            "url": video_url, "format": "json"
        })
        request = urllib.request.Request(
            oembed_url,
            headers={"Accept": "application/json", "User-Agent": "SolePickRecipePublisher/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                metadata = json.loads(response.read().decode("utf-8"))
            # oEmbed returns metadata only for videos YouTube allows to be embedded.
            verified_title = metadata.get("title") or title
            return {
                "id": video_id,
                "title": verified_title,
                "url": video_url,
                "embed_url": "https://www.youtube-nocookie.com/embed/" + video_id,
                "match_score": round(score, 2),
            }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
            # Private, removed, or non-embeddable videos are rejected; try the next match.
            continue

    raise RuntimeError(
        f"VIDEO REVIEW REQUIRED: no close, publicly embeddable YouTube match could be verified "
        f"without an API key for '{recipe['title']}'. Article not published."
    )

def recipe_video_section_html(recipe, video):
    return (
        "<h2>Recipe Video</h2>"
        f"<p><a href=\"{esc(video['url'])}\" rel=\"noopener noreferrer\">Watch: {esc(video['title'])}</a></p>"
        "<div class=\"solepick-recipe-video\" style=\"position:relative;width:100%;aspect-ratio:16/9;\">"
        f"<iframe src=\"{esc(video['embed_url'])}\" title=\"{esc(recipe['title'])} recipe video\" "
        "loading=\"lazy\" allow=\"accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share\" "
        "referrerpolicy=\"strict-origin-when-cross-origin\" allowfullscreen style=\"position:absolute;inset:0;width:100%;height:100%;border:0;\"></iframe></div>"
    )


def upsert_recipe_video_section(existing_body, recipe, video):
    """Insert or replace only the video section, preserving the article's other content."""
    section = recipe_video_section_html(recipe, video)
    pattern = r"<h2>Recipe Video</h2>.*?(?=<h2\b|$)"
    if re.search(pattern, existing_body, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(pattern, section, existing_body, count=1, flags=re.IGNORECASE | re.DOTALL)
    match = re.search(r"<h2\b", existing_body, flags=re.IGNORECASE)
    if match:
        return existing_body[:match.start()] + section + existing_body[match.start():]
    return existing_body.rstrip() + "\n" + section


def generate_recipe_image(recipe):
    """Use the recipe's preconfigured public photo URL and upload it to Shopify; no image-generation API is needed."""
    source_url = (recipe.get("image_url") or "").strip()
    if not source_url.startswith(("https://", "http://")):
        raise RuntimeError(
            "Recipe has no configured image_url. Add a reviewed food-photo URL and image_alt to recipes.json."
        )
    alt_text = (recipe.get("image_alt") or ("Finished " + recipe["title"] + " served and ready to eat")).strip()
    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "SolePickRecipePublisher/1.0", "Accept": "image/avif,image/webp,image/jpeg,image/png,*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].lower()
            image_bytes = response.read(15 * 1024 * 1024 + 1)
        if len(image_bytes) > 15 * 1024 * 1024:
            raise RuntimeError("Configured recipe photo is larger than 15 MB.")
        if not content_type.startswith("image/") or not image_bytes:
            raise RuntimeError("Configured recipe image URL did not return image data.")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Configured recipe image could not be downloaded (HTTP {error.code}).") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise RuntimeError(f"Configured recipe image could not be downloaded: {type(error).__name__}.") from None

    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/avif": "avif"}.get(content_type, "jpg")
    filename = re.sub(r"[^a-z0-9-]+", "-", recipe["slug"].lower()).strip("-") + "-featured." + extension
    stage_mutation = """mutation StageRecipeImage($input: [StagedUploadInput!]!) { stagedUploadsCreate(input: $input) { stagedTargets { url resourceUrl parameters { name value } } userErrors { field message } } }"""
    staged = graphql(stage_mutation, {"input": [{"filename": filename, "mimeType": content_type, "resource": "IMAGE", "httpMethod": "PUT", "fileSize": str(len(image_bytes))}]}).get("stagedUploadsCreate") or {}
    if staged.get("userErrors"):
        raise RuntimeError("Shopify could not stage recipe image: " + json.dumps(staged["userErrors"]))
    targets = staged.get("stagedTargets") or []
    if not targets:
        raise RuntimeError("Shopify returned no upload target for recipe image.")
    target = targets[0]
    upload_headers = {"Content-Type": content_type}
    for parameter in target.get("parameters") or []:
        if parameter.get("name") and parameter.get("value"):
            upload_headers[parameter["name"]] = parameter["value"]
    upload = urllib.request.Request(target["url"], data=image_bytes, headers=upload_headers, method="PUT")
    try:
        with urllib.request.urlopen(upload, timeout=90) as response:
            if response.status not in (200, 201, 204):
                raise RuntimeError(f"Shopify image upload returned HTTP {response.status}.")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Uploading recipe image to Shopify failed (HTTP {error.code}).") from None
    file_mutation = """mutation CreateRecipeImageFile($files: [FileCreateInput!]!) { fileCreate(files: $files) { files { id fileStatus ... on MediaImage { image { url altText } } } userErrors { field message } } }"""
    created = graphql(file_mutation, {"files": [{"originalSource": target["resourceUrl"], "contentType": "IMAGE", "filename": filename, "alt": alt_text}]}).get("fileCreate") or {}
    if created.get("userErrors"):
        raise RuntimeError("Shopify rejected recipe image: " + json.dumps(created["userErrors"]))
    files = created.get("files") or []
    if not files or not files[0].get("id"):
        raise RuntimeError("Shopify did not return a recipe image file ID.")
    file_id = files[0]["id"]
    status_query = """query RecipeImageStatus($id: ID!) { node(id: $id) { ... on MediaImage { id fileStatus image { url altText } } } }"""
    for _ in range(30):
        node = graphql(status_query, {"id": file_id}).get("node") or {}
        image = node.get("image") or {}
        if node.get("fileStatus") == "READY" and image.get("url"):
            print("RECIPE IMAGE VERIFIED: Shopify-hosted configured photo ready for " + recipe["title"])
            return {"url": image["url"], "altText": alt_text}
        if node.get("fileStatus") == "FAILED":
            raise RuntimeError("Shopify failed to process recipe image for " + recipe["title"])
        time.sleep(2)
    raise RuntimeError("Shopify image processing timed out; article was not published.")


def featured_image_for(recipe, generated_image):
    """Only accept a newly generated and Shopify-verified recipe image."""
    if not generated_image or not generated_image.get("url"):
        raise RuntimeError("No verified generated featured image for " + recipe["title"])
    return {"url": generated_image["url"], "altText": generated_image.get("altText") or ("Finished " + recipe["title"])}

def article_html(recipe, video=None):
    ingredients = "".join(f"<li>{esc(item)}</li>" for item in recipe["ingredients"])
    steps = "".join(f"<li>{esc(item)}</li>" for item in recipe["instructions"])
    video_html = recipe_video_section_html(recipe, video) if video else ""
    return (
        f"<p>{esc(recipe['description'])}</p>"
        f"<p><strong>Prep:</strong> {recipe['prep_minutes']} minutes · "
        f"<strong>Cook:</strong> {recipe['cook_minutes']} minutes · "
        f"<strong>Serves:</strong> {recipe['servings']}</p>"
        f"{video_html}"
        f"<h2>Ingredients</h2><ul>{ingredients}</ul>"
        f"<h2>Instructions</h2><ol>{steps}</ol>"
        "<p><em>Check labels for allergens and follow safe food-handling practices. "
        "Cooking times vary; verify food is safely cooked before serving.</em></p>"
    )


def expected_schedule_cron(now=None):
    now = now or datetime.datetime.now(CAIRO)
    return "0 7 * * *" if now.utcoffset() == datetime.timedelta(hours=3) else "0 8 * * *"


def already_published_today(articles, now=None):
    now = now or datetime.datetime.now(CAIRO)
    for article in articles.values():
        published_at = article.get("publishedAt")
        if article.get("isPublished") and published_at:
            try:
                published_date = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00")).astimezone(CAIRO).date()
            except (ValueError, TypeError):
                continue
            if published_date == now.date():
                return article
    return None


def get_access_token(domain):
    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Set SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET in GitHub Actions Secrets.")
    payload = {"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret}
    req = urllib.request.Request(
        f"https://{domain}/admin/oauth/access_token",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Shopify token exchange failed with HTTP {error.code}; check app installation, credentials, and permissions.") from None
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Shopify returned no access token.")
    return token


def graphql(query, variables):
    global ACCESS_TOKEN
    domain = os.environ.get("SHOPIFY_STORE_DOMAIN", "").strip()
    if not domain:
        raise RuntimeError("Set SHOPIFY_STORE_DOMAIN in GitHub Actions Secrets.")
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    if "/" in domain or not domain.endswith(".myshopify.com"):
        raise RuntimeError("SHOPIFY_STORE_DOMAIN must be a *.myshopify.com domain.")
    if ACCESS_TOKEN is None:
        ACCESS_TOKEN = get_access_token(domain)
    req = urllib.request.Request(
        f"https://{domain}/admin/api/{API_VERSION}/graphql.json",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": ACCESS_TOKEN},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Shopify API returned HTTP {error.code}; verify domain, token, and permissions.") from None
    if data.get("errors"):
        raise RuntimeError("Shopify GraphQL errors: " + json.dumps(data["errors"]))
    return data.get("data", {})


def existing_articles(blog_id):
    query = """query ArticleHandles($id: ID!, $after: String) {
      blog(id: $id) { articles(first: 100, after: $after) {
        nodes { id handle isPublished publishedAt }
        pageInfo { hasNextPage endCursor }
      } }
    }"""
    found, after = {}, None
    while True:
        data = graphql(query, {"id": blog_id, "after": after})
        blog = data.get("blog")
        if not blog:
            raise RuntimeError("Blog not found; verify SHOPIFY_BLOG_ID and token permissions.")
        conn = blog["articles"]
        for article in conn["nodes"]:
            found[article["handle"]] = article
        if not conn["pageInfo"]["hasNextPage"]:
            return found
        after = conn["pageInfo"]["endCursor"]


def get_existing_article_for_repair(blog_id, handle):
    query = """query RepairArticleByHandle($id: ID!, $after: String) {
      blog(id: $id) { articles(first: 100, after: $after) {
        nodes { id title handle body isPublished }
        pageInfo { hasNextPage endCursor }
      } }
    }"""
    after = None
    while True:
        data = graphql(query, {"id": blog_id, "after": after})
        blog = data.get("blog")
        if not blog:
            raise RuntimeError("Blog not found; verify SHOPIFY_BLOG_ID and token permissions.")
        conn = blog["articles"]
        for article in conn["nodes"]:
            if article.get("handle") == handle:
                return article
        if not conn["pageInfo"]["hasNextPage"]:
            return None
        after = conn["pageInfo"]["endCursor"]


def repair_existing_article_video(blog_id, handle, recipes):
    existing = get_existing_article_for_repair(blog_id, handle)
    if not existing:
        raise RuntimeError(f"No existing Shopify article found for handle '{handle}'. No Shopify changes made.")
    if not existing.get("isPublished"):
        raise RuntimeError(f"Article '{handle}' is not published; refusing to change its publication state.")
    # The target article may not be part of the rotating recipes.json library.
    # Use its actual Shopify title for video search and preserve its existing body.
    recipe = {"title": existing.get("title") or handle}
    print(f"Repairing video only for existing article: {existing.get('title')} | handle={handle}")
    video = find_verified_recipe_video(recipe)
    print(f"Verified recipe video: {video['title']} | id={video['id']} | match={video['match_score']} | embeddable=yes")
    updated_body = upsert_recipe_video_section(existing.get("body") or "", recipe, video)
    mutation = """mutation RepairExistingArticleVideo($id: ID!, $article: ArticleUpdateInput!) {
      articleUpdate(id: $id, article: $article) {
        article { id title handle body isPublished }
        userErrors { field message }
      }
    }"""
    result = graphql(mutation, {"id": existing["id"], "article": {"body": updated_body}}).get("articleUpdate") or {}
    if result.get("userErrors"):
        raise RuntimeError("Shopify rejected existing article video repair: " + json.dumps(result["userErrors"]))
    updated = result.get("article")
    if not updated or updated.get("handle") != handle or not updated.get("isPublished"):
        raise RuntimeError("Shopify did not confirm the existing published article was updated.")
    if video["embed_url"] not in (updated.get("body") or ""):
        raise RuntimeError("Shopify update response did not contain the verified video embed URL.")
    print(f"REPAIR VERIFIED: existing article updated without creating a new article | handle={handle} | video={video['url']}")
    return updated


def publish_existing(article):
    mutation = """mutation PublishExistingArticle($id: ID!, $article: ArticleUpdateInput!) {
      articleUpdate(id: $id, article: $article) {
        article { id title handle isPublished }
        userErrors { field message }
      }
    }"""
    result = graphql(mutation, {"id": article["id"], "article": {"isPublished": True}}).get("articleUpdate") or {}
    if result.get("userErrors"):
        raise RuntimeError("Shopify rejected article publishing: " + json.dumps(result["userErrors"]))
    published = result.get("article")
    if not published or not published.get("isPublished"):
        raise RuntimeError("Shopify did not confirm that the existing article is published.")
    return published


def create_published(blog_id, recipe, video, generated_image):
    mutation = """mutation CreatePublishedArticle($article: ArticleCreateInput!) {
      articleCreate(article: $article) {
        article { id title handle isPublished }
        userErrors { field message }
      }
    }"""
    article = {
        "blogId": blog_id, "title": recipe["title"], "handle": recipe["slug"],
        "author": {"name": "SolePick Recipes"}, "body": article_html(recipe, video),
        "summary": recipe["description"], "tags": recipe.get("tags", []), "isPublished": True,
        "image": featured_image_for(recipe, generated_image),
    }
    result = graphql(mutation, {"article": article}).get("articleCreate") or {}
    if result.get("userErrors"):
        raise RuntimeError("Shopify rejected recipe publishing: " + json.dumps(result["userErrors"]))
    published = result.get("article")
    if not published or not published.get("isPublished"):
        raise RuntimeError("Shopify did not confirm that the new article is published.")
    return published


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repair-handle", help="Update the video section on an existing published Shopify article without creating a new article.")
    parser.add_argument("--one-time-test", action="store_true", help="Manual one-time test: bypass the same-day guard for one eligible new recipe only.")
    args = parser.parse_args()
    if args.one_time_test and args.repair_handle:
        parser.error("--one-time-test cannot be combined with --repair-handle")
    now = datetime.datetime.now(CAIRO)
    # GitHub may delay scheduled workflows well beyond their cron time.
    # Do not reject a scheduled run based on the runner's current clock or seasonal
    # offset: the Shopify same-Cairo-day idempotency guard below prevents duplicate
    # posts when both seasonal cron triggers run. Video verification still gates publish.
    recipes = load_recipes()
    day_number = (now.date() - datetime.date(2025, 1, 1)).days

    # Dry-run is deliberately offline: it does not call Shopify.
    if args.dry_run:
        recipe = recipes[day_number % len(recipes)]
        print(f"Dry-run selection for {now.date()} Cairo time: {recipe['title']} ({recipe['slug']})")
        print("Dry run only; no Shopify request made.")
        return

    blog_id = os.environ.get("SHOPIFY_BLOG_ID", "").strip()
    if not blog_id:
        raise RuntimeError("Set SHOPIFY_BLOG_ID in GitHub Actions Secrets.")

    if args.repair_handle:
        repair_existing_article_video(blog_id, args.repair_handle.strip(), recipes)
        return

    articles = existing_articles(blog_id)
    published_today = already_published_today(articles, now)
    if published_today and not args.one_time_test:
        print(f"Daily idempotency guard: already published '{published_today.get('handle')}' on {now.date()} Cairo time; no second recipe will be published.")
        return
    if published_today and args.one_time_test:
        print(f"ONE-TIME TEST MODE: allowing one additional eligible recipe despite today's existing article '{published_today.get('handle')}'. Normal daily guard remains enabled for all other runs.")
    start = day_number % len(recipes)

    eligible = [
        recipe for recipe in recipes
        if not (articles.get(recipe["slug"]) and articles[recipe["slug"]].get("isPublished"))
    ]
    print(f"Recipe library status: {len(eligible)} of {len(recipes)} recipes remain eligible.")

    if len(eligible) <= 3:
        print("WARNING: Recipe library is nearly exhausted. Add original recipes to recipes.json.")

    if not eligible:
        raise RuntimeError(
            "Recipe library exhausted. Add new original recipes to recipes.json."
        )

    # Rotate from today's recipe, skipping already-published recipes.
    for offset in range(len(recipes)):
        recipe = recipes[(start + offset) % len(recipes)]
        existing = articles.get(recipe["slug"])

        if existing and existing.get("isPublished"):
            print(f"Skipping already-published recipe: {recipe['title']} ({recipe['slug']}).")
            continue

        print(f"Selected for {now.date()} Cairo time: {recipe['title']} ({recipe['slug']})")
        try:
            video = find_verified_recipe_video(recipe)
        except RuntimeError as error:
            print(f"SKIPPING recipe without a verified matching video: {recipe['title']}. {error}")
            continue
        print(f"Verified recipe video: {video['title']} | id={video['id']} | match={video['match_score']} | embeddable=yes")
        generated_image = generate_recipe_image(recipe)
        print(f"Generated and verified Shopify-hosted featured image for: {recipe['title']}")
        if existing:
            mutation = """mutation UpdateRecipeArticle($id: ID!, $article: ArticleUpdateInput!) {
              articleUpdate(id: $id, article: $article) { article { id title handle isPublished } userErrors { field message } }
            }"""
            result = graphql(mutation, {"id": existing["id"], "article": {
                "body": article_html(recipe, video),
                "image": featured_image_for(recipe, generated_image),
                "isPublished": True,
            }}).get("articleUpdate") or {}
            if result.get("userErrors"):
                raise RuntimeError("Shopify rejected recipe/video update: " + json.dumps(result["userErrors"]))
            article = result.get("article")
            if not article or not article.get("isPublished"):
                raise RuntimeError("Shopify did not confirm recipe article publication.")
        else:
            article = create_published(blog_id, recipe, video, generated_image)
        print(f"Published recipe with verified video: {article['title']} | handle={article['handle']} | published={article['isPublished']} | video={video['url']}")
        return

    raise RuntimeError("No eligible recipe found. Review recipes.json and Shopify article handles.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
