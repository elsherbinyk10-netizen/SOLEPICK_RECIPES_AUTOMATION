#!/usr/bin/env python3
"""Create one Shopify recipe article as a draft. Live publishing is not supported."""
import argparse, datetime, json, os, sys, urllib.error, urllib.request
from pathlib import Path

API_VERSION = "2026-07"
RECIPES_PATH = Path(__file__).with_name("recipes.json")

def load_recipes():
    recipes = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    if not recipes:
        raise ValueError("recipes.json is empty")
    slugs = [r.get("slug", "") for r in recipes]
    if any(not s for s in slugs) or len(slugs) != len(set(slugs)):
        raise ValueError("Every recipe needs a unique, non-empty slug")
    return recipes

def esc(v):
    return str(v).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def article_html(r):
    ingredients = "".join(f"<li>{esc(x)}</li>" for x in r["ingredients"])
    steps = "".join(f"<li>{esc(x)}</li>" for x in r["instructions"])
    return (f"<p>{esc(r['description'])}</p>"
            f"<p><strong>Prep:</strong> {r['prep_minutes']} minutes · "
            f"<strong>Cook:</strong> {r['cook_minutes']} minutes · "
            f"<strong>Serves:</strong> {r['servings']}</p>"
            f"<h2>Ingredients</h2><ul>{ingredients}</ul>"
            f"<h2>Instructions</h2><ol>{steps}</ol>"
            "<p><em>Check labels for allergens and follow safe food-handling practices. "
            "Cooking times vary; verify food is safely cooked before serving.</em></p>")

ACCESS_TOKEN = None

def get_access_token(domain):
    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Set SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET in GitHub Actions Secrets."
        )

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    req = urllib.request.Request(
        f"https://{domain}/admin/oauth/access_token",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(
            f"Shopify token exchange failed with HTTP {e.code}; "
            "check the app installation, credentials, and permissions."
        ) from None

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
    token = ACCESS_TOKEN
    req = urllib.request.Request(
        f"https://{domain}/admin/api/{API_VERSION}/graphql.json",
        data=json.dumps({"query":query,"variables":variables}).encode(),
        headers={"Content-Type":"application/json","X-Shopify-Access-Token":token},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Shopify API returned HTTP {e.code}; verify domain, token, and permissions.") from None
    if data.get("errors"):
        raise RuntimeError("Shopify GraphQL errors: " + json.dumps(data["errors"]))
    return data.get("data", {})

def existing_handles(blog_id):
    query = """query ArticleHandles($id: ID!, $after: String) {
      blog(id:$id) { articles(first:100, after:$after) {
        nodes { handle } pageInfo { hasNextPage endCursor }
      } }
    }"""
    handles, after = set(), None
    while True:
        data = graphql(query, {"id":blog_id,"after":after})
        blog = data.get("blog")
        if not blog:
            raise RuntimeError("Blog not found; verify SHOPIFY_BLOG_ID and token permissions.")
        conn = blog["articles"]
        handles.update(n["handle"] for n in conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]:
            return handles
        after = conn["pageInfo"]["endCursor"]

def create_draft(blog_id, r):
    mutation = """mutation ArticleCreate($article: ArticleCreateInput!) {
      articleCreate(article:$article) {
        article { id title handle isPublished }
        userErrors { field message }
      }
    }"""
    article = {"blogId":blog_id,"title":r["title"],"handle":r["slug"],
               "author":{"name":"SolePick Recipes"},
               "body":article_html(r),"summary":r["description"],
               "tags":r.get("tags",[]),"isPublished":False}
    if r.get("image_url"):
        article["image"] = {
            "url": r["image_url"],
            "altText": r.get("image_alt", r["title"])
        }
    result = graphql(mutation, {"article":article}).get("articleCreate") or {}
    if result.get("userErrors"):
        raise RuntimeError("Shopify rejected draft: " + json.dumps(result["userErrors"]))
    return result.get("article")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    recipes = load_recipes()
    today = datetime.datetime.now(datetime.timezone.utc).date()
    recipe = recipes[(today - datetime.date(2025,1,1)).days % len(recipes)]
    print(f"Selected: {recipe['title']} ({recipe['slug']})")
    if args.dry_run:
        print("Dry run only; no Shopify request made.")
        return
    blog_id = os.environ.get("SHOPIFY_BLOG_ID","").strip()
    if not blog_id:
        raise RuntimeError("Set SHOPIFY_BLOG_ID in GitHub Actions Secrets.")
    if recipe["slug"] in existing_handles(blog_id):
        print("Recipe handle already exists; skipping.")
        return
    article = create_draft(blog_id, recipe)
    print(f"Created draft: {article['title']} | handle={article['handle']} | published={article['isPublished']}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
