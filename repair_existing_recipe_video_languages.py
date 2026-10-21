"""Safely remove legacy caption controls and install the independent video-language selector.

Only touches already-published recipe articles with a recognizable existing YouTube embed.
Never creates articles or replaces the English video. Non-English candidates are enabled only
when reviewed=true, verified=true, and recipe/language metadata matches.
"""
import html
import json
import re
import sys
from pathlib import Path
import recipe_worker as worker

ROOT = Path(__file__).resolve().parent


def approved_candidates(catalogue, slug, language_names):
    entries = catalogue.get(slug, {})
    approved = {}
    for code, entry in entries.items():
        if code == "en" or not isinstance(entry, dict):
            continue
        if entry.get("reviewed") is not True or entry.get("verified") is not True:
            continue
        if entry.get("recipe_slug") != slug or entry.get("language") != code:
            continue
        url = str(entry.get("embed_url", ""))
        if not re.fullmatch(r"https://www\.youtube-nocookie\.com/embed/[A-Za-z0-9_-]{11}", url):
            continue
        approved[code] = {"embed_url": url, "label": language_names.get(code, entry.get("language_name", code))}
    return approved


def build_switcher(slug, approved):
    mapping = json.dumps({code: row["embed_url"] for code, row in approved.items()},
                         ensure_ascii=False, separators=(",", ":"))
    options = ['<option value="en" selected>English</option>']
    options.extend(f'<option value="{worker.esc(code)}">{worker.esc(row["label"])}</option>'
                   for code, row in sorted(approved.items(), key=lambda item: item[1]["label"].casefold()))
    encoded = worker.esc(mapping)
    return (
        f'<div class="solepick-video-language-map" data-recipe-slug="{worker.esc(slug)}" data-video-map="{encoded}" hidden></div>'
        '<div class="solepick-video-language-control">'
        '<label for="solepick-video-language">Video language</label>'
        '<select id="solepick-video-language" class="solepick-video-language-select" aria-label="Video language">'
        + "".join(options) + '</select></div>'
        '<p class="solepick-video-language-fallback" role="status" aria-live="polite" hidden></p>'
        '<script>(function(){var selector=".solepick-video-language-select";'
        'function apply(s){var root=s.closest(".solepick-video-language-control");'
        'var section=root&&root.parentElement;var m=section&&section.querySelector(".solepick-video-language-map");'
        'var map={};try{map=JSON.parse(m&&m.getAttribute("data-video-map")||"{}")}catch(e){}'
        'var f=section&&section.querySelector("iframe.solepick-language-aware-video");'
        'var note=section&&section.querySelector(".solepick-video-language-fallback");if(!f)return;'
        'var lang=s.value||"en";var base=f.getAttribute("data-video-base")||f.src;'
        'var target=lang==="en"?base:(map[lang]||map[lang.split("-")[0]]);'
        'if(target){if(f.src!==target)f.src=target;f.setAttribute("data-active-video-language",lang);'
        'if(note)note.hidden=true}else if(note){note.hidden=false;note.textContent='
        '"A verified video in this language is not available for this recipe yet. The English recipe video remains available."}}'
        'document.addEventListener("change",function(e){if(e.target&&e.target.matches(selector))apply(e.target)});'
        'document.addEventListener("DOMContentLoaded",function(){document.querySelectorAll(selector).forEach(apply)})})();</script>'
    )


def existing_video(body, article_title):
    match = re.search(r'<iframe\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>', body, re.I | re.S)
    if not match:
        return None
    src = html.unescape(match.group(1)).replace("&amp;", "&")
    video_match = re.search(r"(?:youtube-nocookie\.com|youtube\.com)/embed/([A-Za-z0-9_-]{11})", src)
    if not video_match:
        return None
    video_id = video_match.group(1)
    base = "https://www.youtube-nocookie.com/embed/" + video_id
    return {"id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id,
            "title": article_title + " recipe video", "embed_url": base}


def main():
    video_file = ROOT / "localized_recipe_videos.json"
    catalogue = json.loads(video_file.read_text(encoding="utf-8")) if video_file.exists() else {}
    language_file = ROOT / "supported_languages.json"
    language_names = json.loads(language_file.read_text(encoding="utf-8")) if language_file.exists() else {}
    recipes = json.loads((ROOT / "recipes.json").read_text(encoding="utf-8"))
    blog_id = __import__("os").environ.get("SHOPIFY_BLOG_ID", "").strip()
    if not blog_id:
        raise SystemExit("Set SHOPIFY_BLOG_ID in GitHub Actions Secrets.")
    query = """query Articles($id: ID!, $after: String) {
      blog(id: $id) { articles(first: 100, after: $after) {
        nodes { id title handle body isPublished }
        pageInfo { hasNextPage endCursor }
      } }
    }"""
    articles, after = [], None
    while True:
        data = worker.graphql(query, {"id": blog_id, "after": after})
        blog = data.get("blog")
        if not blog:
            raise RuntimeError("Shopify blog not found; check SHOPIFY_BLOG_ID and permissions.")
        conn = blog["articles"]
        articles.extend(conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]:
            break
        after = conn["pageInfo"]["endCursor"]

    recipe_by_slug = {r.get("slug"): r for r in recipes if r.get("slug")}
    updated = skipped = 0
    for article in articles:
        if not article.get("isPublished"):
            continue
        recipe = recipe_by_slug.get(article.get("handle"))
        if not recipe:
            title = article.get("title", "").casefold().strip()
            recipe = next((r for r in recipes if r.get("title", "").casefold().strip() == title), None)
        if not recipe:
            skipped += 1
            print("SKIP no source recipe match:", article.get("handle"))
            continue

        body = article.get("body") or ""
        section = re.compile(r"<h2>Recipe Video</h2>.*?(?=<h2\b|$)", re.I | re.S)
        match = section.search(body)
        if not match:
            skipped += 1
            print("SKIP no known Recipe Video section:", article.get("handle"))
            continue
        current = existing_video(match.group(0), article.get("title", recipe["title"]))
        if not current:
            skipped += 1
            print("SKIP no recognizable YouTube video; preserving article:", article.get("handle"))
            continue

        approved = approved_candidates(catalogue, recipe["slug"], language_names)
        replacement = worker.recipe_video_section_html(recipe, current) + build_switcher(recipe["slug"], approved)
        updated_body = section.sub(lambda _m: replacement, body, count=1)
        if updated_body == body:
            skipped += 1
            print("SKIP already current:", article.get("handle"))
            continue
        mutation = """mutation UpdateArticleBody($id: ID!, $article: ArticleUpdateInput!) {
          articleUpdate(id:$id,article:$article) { article { id handle isPublished body } userErrors { field message } }
        }"""
        result = worker.graphql(mutation, {"id": article["id"], "article": {"body": updated_body}}).get("articleUpdate") or {}
        if result.get("userErrors"):
            raise RuntimeError("Shopify rejected update for " + article["handle"] + ": " + json.dumps(result["userErrors"]))
        saved = result.get("article")
        saved_body = (saved or {}).get("body") or ""
        if not saved or saved.get("handle") != article["handle"] or not saved.get("isPublished"):
            raise RuntimeError("Could not verify saved published article " + article["handle"])
        if "solepick-video-language-select" not in saved_body or "solepick-language-aware-video" not in saved_body:
            raise RuntimeError("Video selector verification failed for " + article["handle"])
        updated += 1
        print("UPDATED existing article:", article["handle"], "approved non-English languages:", ",".join(approved) or "none; English fallback")
    print(f"Repair finished. Updated={updated}; skipped={skipped}; published articles scanned={len(articles)}. No articles created.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ERROR:", exc, file=sys.stderr)
        raise SystemExit(1)
