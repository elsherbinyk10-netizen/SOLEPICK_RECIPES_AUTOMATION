#!/usr/bin/env python3
"""Publish the scheduled SolePick recipe to the configured Shopify blog."""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
import urllib.parse
import re
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


def _youtube_api(endpoint, params):
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Video workflow blocked: add YOUTUBE_API_KEY to GitHub Actions Secrets. No article will be published without a verified recipe video.")
    params = dict(params, key=key)
    url = "https://www.googleapis.com/youtube/v3/" + endpoint + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"YouTube video validation failed with HTTP {error.code}; check YOUTUBE_API_KEY and YouTube Data API quota.") from None
    return data


def _video_title_score(recipe_title, video_title):
    stop = {"recipe", "easy", "best", "how", "to", "make", "the", "with", "for", "and", "a", "an", "of", "in", "on", "quick", "simple", "delicious"}
    wanted = {x for x in re.findall(r"[a-z0-9]+", recipe_title.lower()) if x not in stop}
    found = {x for x in re.findall(r"[a-z0-9]+", video_title.lower()) if x not in stop}
    return len(wanted & found) / max(1, len(wanted))


def find_verified_recipe_video(recipe):
    search = _youtube_api("search", {
        "part": "snippet", "type": "video", "maxResults": 8,
        "q": recipe["title"] + " recipe", "safeSearch": "strict",
        "videoEmbeddable": "true", "order": "relevance",
    })
    candidates = []
    for item in search.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        title = item.get("snippet", {}).get("title", "")
        if video_id:
            candidates.append((_video_title_score(recipe["title"], title), video_id, title))
    candidates.sort(reverse=True)
    if not candidates or candidates[0][0] < 0.45:
        raise RuntimeError(f"VIDEO REVIEW REQUIRED: no sufficiently close YouTube match found for '{recipe['title']}'. Article not published.")
    score, video_id, title = candidates[0]
    details = _youtube_api("videos", {"part": "status,contentDetails,snippet", "id": video_id}).get("items", [])
    if not details:
        raise RuntimeError(f"VIDEO UNAVAILABLE: YouTube no longer returns video {video_id}. Article not published.")
    status = details[0].get("status", {})
    if status.get("privacyStatus") != "public" or not status.get("embeddable", False):
        raise RuntimeError(f"VIDEO UNAVAILABLE: '{title}' is not public and embeddable. Article not published.")
    return {
        "id": video_id, "title": title,
        "url": "https://www.youtube.com/watch?v=" + video_id,
        "embed_url": "https://www.youtube-nocookie.com/embed/" + video_id,
        "match_score": round(score, 2),
    }


def article_html(recipe, video=None):
    ingredients = "".join(f"<li>{esc(item)}</li>" for item in recipe["ingredients"])
    steps = "".join(f"<li>{esc(item)}</li>" for item in recipe["instructions"])
    video_html = ""
    if video:
        video_html = (
            "<h2>Recipe Video</h2>"
            f"<p><a href=\"{esc(video['url'])}\" rel=\"noopener noreferrer\">Watch: {esc(video['title'])}</a></p>"
            f"<div class=\"solepick-recipe-video\" style=\"position:relative;width:100%;aspect-ratio:16/9;\">"
            f"<iframe src=\"{esc(video['embed_url'])}\" title=\"{esc(recipe['title'])} recipe video\" "
            "loading=\"lazy\" allow=\"accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share\" "
            "referrerpolicy=\"strict-origin-when-cross-origin\" allowfullscreen style=\"position:absolute;inset:0;width:100%;height:100%;border:0;\"></iframe></div>"
        )
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


def publish_existing(article):
    mutation = """mutation PublishExistingArticle($article: ArticleUpdateInput!) {
      articleUpdate(article: $article) {
        article { id title handle isPublished }
        userErrors { field message }
      }
    }"""
    result = graphql(mutation, {"article": {"id": article["id"], "isPublished": True}}).get("articleUpdate") or {}
    if result.get("userErrors"):
        raise RuntimeError("Shopify rejected article publishing: " + json.dumps(result["userErrors"]))
    published = result.get("article")
    if not published or not published.get("isPublished"):
        raise RuntimeError("Shopify did not confirm that the existing article is published.")
    return published


def create_published(blog_id, recipe, video):
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
    }
    if recipe.get("image_url"):
        article["image"] = {"url": recipe["image_url"], "altText": recipe.get("image_alt", recipe["title"])}
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
    args = parser.parse_args()
    now = datetime.datetime.now(CAIRO)
    # Select the seasonal trigger by its declared cron, not the delayed runner's wall clock.
    if not args.dry_run and os.environ.get("GITHUB_EVENT_NAME") == "schedule":
        fired_cron = os.environ.get("GITHUB_EVENT_SCHEDULE", "").strip()
        expected_cron = expected_schedule_cron(now)
        if fired_cron != expected_cron:
            print(f"Skipping seasonal trigger {fired_cron!r}; expected {expected_cron!r} for Cairo offset {now.utcoffset()}.")
            return
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

    articles = existing_articles(blog_id)
    published_today = already_published_today(articles, now)
    if published_today:
        print(f"Daily idempotency guard: already published '{published_today.get('handle')}' on {now.date()} Cairo time; no second recipe will be published.")
        return
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
        video = find_verified_recipe_video(recipe)
        print(f"Verified recipe video: {video['title']} | id={video['id']} | match={video['match_score']} | embeddable=yes")
        if existing:
            mutation = """mutation UpdateRecipeArticle($article: ArticleUpdateInput!) {
              articleUpdate(article: $article) { article { id title handle isPublished } userErrors { field message } }
            }"""
            result = graphql(mutation, {"article": {"id": existing["id"], "body": article_html(recipe, video), "isPublished": True}}).get("articleUpdate") or {}
            if result.get("userErrors"):
                raise RuntimeError("Shopify rejected recipe/video update: " + json.dumps(result["userErrors"]))
            article = result.get("article")
            if not article or not article.get("isPublished"):
                raise RuntimeError("Shopify did not confirm recipe article publication.")
        else:
            article = create_published(blog_id, recipe, video)
        print(f"Published recipe with verified video: {article['title']} | handle={article['handle']} | published={article['isPublished']} | video={video['url']}")
        return

    raise RuntimeError("No eligible recipe found. Review recipes.json and Shopify article handles.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
