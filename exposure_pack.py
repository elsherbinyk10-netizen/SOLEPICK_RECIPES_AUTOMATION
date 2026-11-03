import argparse
import csv
import html
import json
import os
import re
from html.parser import HTMLParser
from pathlib import Path

from recipe_worker import graphql


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.links = 0
        self.headings = 0

    def handle_data(self, data):
        value = re.sub(r"\\s+", " ", data).strip()
        if value:
            self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links += 1
        if tag in ("h1", "h2", "h3"):
            self.headings += 1


def inspect(value):
    parser = Text()
    parser.feed(str(value or ""))
    text = re.sub(r"\\s+", " ", html.unescape(" ".join(parser.parts))).strip()
    return text, parser.links, parser.headings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()
    blog_id = os.environ.get("SHOPIFY_BLOG_ID", "").strip()
    if not blog_id:
        raise RuntimeError("SHOPIFY_BLOG_ID is required")
    query = """query Exposure($id: ID!, $n: Int!) {
      blog(id: $id) { articles(first: $n, reverse: true) {
        nodes { title handle summary body isPublished tags image { url }
          metafields(first: 10, namespace: "global") { nodes { key value } }
        }
      } }
    }"""
    data = graphql(query, {"id": blog_id, "n": max(1, min(args.limit, 10))})
    packs = []
    for article in (data.get("blog") or {}).get("articles", {}).get("nodes", []):
        if not article.get("isPublished") or not article.get("handle"):
            continue
        title = inspect(article.get("title"))[0]
        body, links, headings = inspect(article.get("body"))
        summary = inspect(article.get("summary"))[0] or body[:230]
        url = "https://solepick.site/blogs/recipes/" + article["handle"]
        metafields = {
            item.get("key"): item.get("value", "")
            for item in (article.get("metafields") or {}).get("nodes", [])
        }
        seo_title = metafields.get("title_tag") or title
        description = metafields.get("description_tag") or summary
        image = (article.get("image") or {}).get("url", "")
        words = len(body.split())
        ingredients = bool(re.search(r"ingredients", body, re.I))
        instructions = bool(re.search(r"instructions|method|directions|how to make", body, re.I))
        checks = {
            "seo_title_60_chars_or_less": len(seo_title) <= 60,
            "meta_description_110_to_160_chars": 110 <= len(description) <= 160,
            "featured_image_present": bool(image),
            "recipe_body_at_least_350_words_review": words >= 350,
            "ingredients_section_present": ingredients,
            "method_or_instructions_section_present": instructions,
            "at_least_one_article_link": links >= 1,
            "heading_structure_present": headings >= 1,
            "summary_present": bool(summary),
        }
        issues = [key for key, passed in checks.items() if not passed]
        tags = []
        for raw in list(article.get("tags") or []) + re.findall(r"[A-Za-z0-9]+", title):
            tag = "".join(part.title() for part in re.findall(r"[A-Za-z0-9]+", str(raw)))
            if len(tag) > 2 and tag.lower() not in {"the", "and", "with", "from", "recipe", "recipes"}:
                value = "#" + tag
                if value not in tags:
                    tags.append(value)
        social = {
            "facebook": f"{title}\\n\\n{summary}\\n\\nSave this recipe: {url}",
            "instagram": f"{title}\\n\\n{summary}\\n\\nSave for later — link in bio.\\n{' '.join(tags[:10])}",
            "x": f"{title[:160]} — {url}",
            "pinterest": f"{title} — {summary}\\n{url}",
        }
        packs.append({
            "title": title, "url": url, "seo_title": seo_title,
            "meta_description": description, "image_url": image,
            "body_word_count": words, "social": social,
            "audit": checks, "issues_to_review": issues,
        })

    out = Path("exposure_output")
    out.mkdir(exist_ok=True)
    (out / "solepick-exposure.json").write_text(
        json.dumps(packs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# SolePick — daily growth and recipe audit", "",
        "This report checks visible recipe-content signals and prepares promotion copy.",
        "It does not publish to social accounts or change Shopify SEO fields.", "",
        f"Recipes checked: {len(packs)}", ""
    ]
    for pack in packs:
        lines += [
            f"## {pack['title']}", f"URL: {pack['url']}",
            f"SEO title: {pack['seo_title']}",
            f"Meta description: {pack['meta_description']}",
            f"Body words: {pack['body_word_count']}",
            f"Featured image: {pack['image_url'] or 'MISSING'}", "",
            "### Review flags"
        ]
        lines += [f"- [{'x' if ok else ' '}] {key}" for key, ok in pack["audit"].items()]
        if pack["issues_to_review"]:
            lines += ["- Manual review: " + ", ".join(pack["issues_to_review"])]
        lines += [""]
        for platform, copy in pack["social"].items():
            lines += [f"### {platform.title()} copy", copy, ""]

    lines += [
        "# Free-traffic operating plan", "",
        "1. Prioritize genuinely tested, distinctive recipes with accurate ingredient quantities, clear steps, substitutions, storage guidance and original photography.",
        "2. Use Pinterest as a discovery channel: create one vertical pin per strong recipe with a descriptive title, image and direct recipe URL.",
        "3. Share selectively on Facebook and relevant cooking communities; follow group rules and avoid repetitive promotional drops.",
        "4. Add contextual links between related recipes, meal-prep guides and ingredient guides.",
        "5. Build helpful search-led hubs (weeknight dinners, budget meals, high-protein meals) with non-duplicative introductions.",
        "6. Review Search Console weekly for queries with impressions but low CTR; improve titles and snippets without keyword stuffing.",
        "7. Review GA4 landing pages and engaged sessions to identify recipes that attract returning readers.",
        "8. Monetization: assess ad-network eligibility and add relevant kitchen-tool affiliate links only where they genuinely help readers.",
        "9. Work toward $60/month as an initial SolePick contribution to the $100 combined target; this is a goal, not a forecast.",
        "",
        "## Important limitation",
        "The automation reads published Shopify content and creates this report. It does not modify SEO metafields, submit URLs to search engines, or publish social posts."
    ]
    (out / "solepick-growth-plan.md").write_text("\\n".join(lines), encoding="utf-8")
    tracker = out / "monthly-performance-tracker.csv"
    if not tracker.exists():
        with tracker.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["month", "site", "sessions", "pageviews", "search_clicks", "search_impressions", "ad_revenue_usd", "affiliate_revenue_usd", "other_revenue_usd", "notes"])
    print(f"Audited {len(packs)} published SolePick recipes; report and tracker generated.")


if __name__ == "__main__":
    main()
