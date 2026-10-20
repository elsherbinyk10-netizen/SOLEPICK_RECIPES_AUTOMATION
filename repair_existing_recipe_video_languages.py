"""Repair existing published SolePick recipe article embeds using verified language video candidates.

Requires Shopify credentials and localized_recipe_videos.json. Never creates articles.
Only updates the video section of already-published articles when at least one verified
language-specific candidate exists; unmatched articles are reported and left unchanged.
"""
import json, re, sys
from pathlib import Path
import recipe_worker as worker

ROOT = Path(__file__).resolve().parent
def main():
    video_file = ROOT / "localized_recipe_videos.json"
    if not video_file.exists():
        raise SystemExit("localized_recipe_videos.json is missing. Run the translation/video-candidate workflow first.")
    candidates = json.loads(video_file.read_text(encoding="utf-8"))
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
    articles=[]; after=None
    while True:
        data=worker.graphql(query, {"id": blog_id, "after": after})
        blog=data.get("blog")
        if not blog: raise RuntimeError("Shopify blog not found; check SHOPIFY_BLOG_ID and permissions.")
        conn=blog["articles"]; articles.extend(conn["nodes"])
        if not conn["pageInfo"]["hasNextPage"]: break
        after=conn["pageInfo"]["endCursor"]
    recipe_by_slug={r.get("slug"):r for r in recipes if r.get("slug")}
    updated=0; skipped=0
    for article in articles:
        if not article.get("isPublished"): continue
        recipe=recipe_by_slug.get(article.get("handle"))
        if not recipe:
            title=article.get("title","").casefold().strip()
            recipe=next((r for r in recipes if r.get("title","").casefold().strip()==title),None)
        if not recipe:
            skipped+=1; print("SKIP no source recipe match:",article.get("handle")); continue
        slug=recipe["slug"]
        per_language=candidates.get(slug,{})
        verified={code:entry for code,entry in per_language.items()
                  if isinstance(entry,dict) and entry.get("verified")
                  and str(entry.get("embed_url","")).startswith("https://www.youtube-nocookie.com/embed/")}
        if not verified:
            skipped+=1; print("SKIP no verified language videos:",slug); continue
        base=next(iter(verified.values()))
        body=article.get("body") or ""
        # Build JSON mapping safely for HTML attributes.
        mapping=json.dumps({code:entry["embed_url"] for code,entry in verified.items()},ensure_ascii=False,separators=(",",":"))
        marker='<div class="solepick-video-language-map" data-video-map="'
        encoded=worker.esc(mapping)
        switcher=(f'<div class="solepick-video-language-map" data-video-map="{encoded}" hidden></div>'
          '<script>(function(){function apply(){var s=document.querySelector("#SolePickTranslateSelect,#solepick-language-switcher,#vm-language-switcher,select[name=language],.language-selector select");var lang=s&&s.value?s.value:"en";document.querySelectorAll(".solepick-video-language-map").forEach(function(m){var map={};try{map=JSON.parse(m.getAttribute("data-video-map")||"{}")}catch(e){}var f=m.parentElement.querySelector("iframe.solepick-language-aware-video")||document.querySelector("iframe.solepick-language-aware-video");if(f&&map[lang])f.src=map[lang];else if(f&&map[lang.split("-")[0]])f.src=map[lang.split("-")[0]]})}document.addEventListener("change",function(e){if(e.target&&e.target.matches("#SolePickTranslateSelect,#solepick-language-switcher,#vm-language-switcher,select[name=language],.language-selector select"))apply()});document.addEventListener("DOMContentLoaded",apply)})();</script>')
        # Replace only the known Recipe Video section; retain article body and other embeds.
        section=re.compile(r"<h2>Recipe Video</h2>.*?(?=<h2\b|$)",re.I|re.S)
        if section.search(body):
            updated_body=section.sub(worker.recipe_video_section_html(recipe,base)+switcher,body,count=1)
        elif "solepick-language-aware-video" in body:
            updated_body=body
            if "solepick-video-language-map" not in body: updated_body += switcher
        else:
            # Do not overwrite or replace an unknown existing video: append our verified section.
            updated_body=body.rstrip()+"\n"+worker.recipe_video_section_html(recipe,base)+switcher
        if updated_body==body:
            skipped+=1; print("SKIP already current:",article["handle"]); continue
        mutation="""mutation UpdateArticleBody($id: ID!, $article: ArticleUpdateInput!) {
          articleUpdate(id:$id,article:$article) { article { id handle isPublished body } userErrors { field message } }
        }"""
        result=worker.graphql(mutation,{"id":article["id"],"article":{"body":updated_body}}).get("articleUpdate") or {}
        if result.get("userErrors"): raise RuntimeError("Shopify rejected update for "+article["handle"]+": "+json.dumps(result["userErrors"]))
        saved=result.get("article")
        if not saved or saved.get("handle")!=article["handle"] or not saved.get("isPublished") or "solepick-video-language-map" not in (saved.get("body") or ""):
            raise RuntimeError("Could not verify language video map saved for "+article["handle"])
        updated+=1; print("UPDATED existing article:",article["handle"],"verified languages:",",".join(verified))
    print(f"Repair finished. Updated={updated}; skipped={skipped}; total articles scanned={len(articles)}. No articles created.")
if __name__=="__main__":
    try: main()
    except Exception as exc:
        print("ERROR:",exc,file=sys.stderr); raise SystemExit(1)
