#!/usr/bin/env python3
"""Publish the scheduled SolePick recipe to the configured Shopify blog.

Every publication is gated by recipe-specific instructions, approved publisher video,
strict title matching, verified thumbnail provenance, and a read-after-write Shopify article check. The daily worker uses one serialized publishing slot and validates creator identity live.
"""
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
from image_quality import inspect_image_url, is_high_quality_image

API_VERSION = "2026-07"
CAIRO = ZoneInfo("Africa/Cairo")
FOOD_NETWORK_CHANNEL_ID = "UC8Y-jrV8oR3s2Ix4viDkZtA"
AUTHORIZED_VIDEO_CHANNELS = {
    FOOD_NETWORK_CHANNEL_ID: "Food Network",
    "UCJFp8uSYCjXOMnkUyb3CQ3Q": "Tasty",
    "UCpSgg_ECBj25s9moCDfSTsA": "Jamie Oliver",
    "UC4tAgeVdaNB5vD_mBoxg50w": "Allrecipes",
}
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


def add_recipe_category_tags(recipe):
    """Attach the canonical SolePick collection tags before saving an article."""
    tags = list(recipe.get("tags") or [])
    normalized = {str(tag).strip().lower() for tag in tags}
    text = " ".join([
        str(recipe.get("title") or ""),
        str(recipe.get("description") or ""),
        " ".join(map(str, tags)),
    ]).lower()
    categories = []
    if any(term in text for term in ("dessert", "cake", "cookie", "brownie", "muffin", "pudding", "crumble", "pastry", "sweet treat", "baking", "bake")):
        categories.append("sweet-things")
    if any(term in normalized for term in ("fresh & green", "fresh-and-green", "vegetarian", "vegan", "plant-based", "salad", "vegetables")) or any(term in text for term in ("salad", "fresh & green", "rainbow bowl", "green goddess")):
        categories.append("fresh-and-green")
    if any(term in normalized for term in ("comfort food", "comfort-food", "family meals", "soup", "pasta", "curry", "stew", "casserole")) or any(term in text for term in ("one-pot soup", "comfort food", "casserole", "slow-cooked", "mac and cheese")):
        categories.append("comfort-food")
    prep = int(recipe.get("prep_minutes") or 0)
    cook = int(recipe.get("cook_minutes") or 0)
    if any(term in normalized for term in ("quick", "quick & easy", "quick-and-easy", "easy", "one-pan", "one pan")) or prep + cook <= 35 or any(term in text for term in ("tacos", "wraps", "parfait", "breakfast bowl")):
        categories.append("quick-and-easy")
    if not categories:
        categories.append("comfort-food" if any(term in text for term in ("roast", "family dinner", "baked", "hearty")) else "quick-and-easy")
    for category in categories:
        if category not in normalized:
            tags.append(category)
            normalized.add(category)
    recipe["tags"] = tags
    return recipe


def _video_title_score(recipe_title, video_title):
    stop = {"recipe", "easy", "best", "how", "to", "make", "the", "with", "for", "and", "a", "an", "of", "in", "on", "quick", "simple", "delicious"}
    wanted = {x for x in re.findall(r"[a-z0-9]+", recipe_title.lower()) if x not in stop}
    found = {x for x in re.findall(r"[a-z0-9]+", video_title.lower()) if x not in stop}
    return len(wanted & found) / max(1, len(wanted))


def _video_title_is_compatible(recipe, video_title):
    """Require the same named main protein and every explicit dish-format anchor."""
    wanted_text = str(recipe.get("title", "")).lower()
    found_text = str(video_title or "").lower()
    wanted_tokens = set(re.findall(r"[a-z0-9]+", wanted_text))
    found_tokens = set(re.findall(r"[a-z0-9]+", found_text))

    protein_groups = [
        {"chicken"}, {"salmon"}, {"shrimp", "prawn", "prawns"}, {"tuna"},
        {"beef"}, {"pork"}, {"turkey"}, {"tofu"}, {"tempeh"}, {"egg", "eggs"},
        {"crab"}, {"lobster"}, {"cod"}, {"tilapia"}, {"trout"}, {"mackerel"},
        {"whitefish"}, {"anchovy", "anchovies"}, {"sardine", "sardines"}
    ]
    wanted_proteins = [group for group in protein_groups if group & wanted_tokens]
    found_proteins = [group for group in protein_groups if group & found_tokens]
    if wanted_proteins and not any(group in found_proteins for group in wanted_proteins):
        return False
    # Reject videos whose titles introduce a different main protein (e.g. crab)
    # that is not part of the recipe. A title match on salmon/wrap alone is not enough.
    if found_proteins:
        wanted_groups = set().union(*wanted_proteins) if wanted_proteins else set()
        if not any(group in found_proteins for group in wanted_proteins):
            return False
        for group in found_proteins:
            if not (group & wanted_tokens):
                return False
    # Reject title matches that omit important format or recipe identity words.
    # This prevents a generic salmon video from being reused for pasta, curry, wraps, etc.

    # Require every named format anchor: salmon salad is not a salmon pasta.
    dish_formats = [
        {"salad"}, {"pasta"}, {"taco", "tacos"}, {"noodle", "noodles"},
        {"soup"}, {"curry"}, {"pizza"}, {"pancake", "pancakes"},
        {"parfait", "parfaits"}, {"bowl", "bowls"}, {"fajita", "fajitas"},
        {"frittata"}, {"sandwich", "sandwiches"}, {"stir", "fry"},
        {"stuffed"}, {"sweet", "potato", "potatoes"}, {"rice"},
        {"wrap", "wraps"}, {"tray"}, {"hash"}, {"grain", "grains"},
        {"risotto"}, {"dumpling", "dumplings"}, {"skillet"}
    ]
    wanted_formats = [group for group in dish_formats if group & wanted_tokens]
    for group in wanted_formats:
        if group & found_tokens:
            continue
        # Common video-title wording varies even when the dish format is equivalent.
        # These aliases do not waive the protein/starch checks below.
        if "stuffed" in group and ({"filled", "loaded"} & found_tokens):
            continue
        if "tray" in group and ({"sheet", "pan", "roasted"} & found_tokens):
            continue
        if "hash" in group and ({"skillet", "breakfast"} & found_tokens):
            continue
        if "grain" in group and ({"quinoa", "farro", "rice", "barley"} & found_tokens):
            continue
        return False

    # Core starch/vegetable identity must be present in the candidate title.
    if "sweet" in wanted_tokens and ({"potato", "potatoes"} & wanted_tokens):
        if not ({"sweet", "potato"} <= found_tokens or {"sweet", "potatoes"} <= found_tokens):
            return False
    for term in ("quinoa", "rice"):
        if term in wanted_tokens and term not in found_tokens:
            return False
    return True


def make_recipe_specific(recipe):
    """Replace legacy placeholders with concrete ingredient names before publication."""
    import copy
    result = copy.deepcopy(recipe)
    title = str(result.get("title", ""))
    title_tokens = set(re.findall(r"[a-z]+", title.lower()))
    main_groups = [
        ({"chicken"}, "chicken"), ({"salmon"}, "salmon"),
        ({"shrimp", "prawn", "prawns"}, "shrimp"), ({"tuna"}, "tuna"),
        ({"beef"}, "beef"), ({"pork"}, "pork"), ({"turkey"}, "turkey"),
        ({"tofu"}, "tofu"), ({"tempeh"}, "tempeh"),
        ({"chickpea", "chickpeas"}, "chickpeas"), ({"lentil", "lentils"}, "lentils"),
        ({"egg", "eggs"}, "eggs"), ({"pasta"}, "pasta"),
        ({"noodle", "noodles"}, "noodles"), ({"potato", "potatoes"}, "potatoes"),
        ({"rice"}, "rice"), ({"mushroom", "mushrooms"}, "mushrooms")
    ]
    main_food = next((label for tokens, label in main_groups if tokens & title_tokens), None)
    if not main_food:
        first = str((result.get("ingredients") or ["the prepared ingredients"])[0])
        first = re.sub(r"^\s*\d+(?:[./]\d+)?\s*", "", first)
        first = re.sub(r"\b(cups?|tablespoons?|teaspoons?|tbsp|tsp|grams?|g|kg|ml|litres?|liters?|oz|ounces?|pounds?|lb)\b", "", first, flags=re.I)
        main_food = re.sub(r"[,;].*$", "", first).strip().lower() or "prepared filling"

    seasoning_terms = []
    for item in result.get("ingredients", []):
        clean = str(item).lower()
        clean = re.sub(r"^\s*\d+(?:[./]\d+)?\s*", "", clean)
        clean = re.sub(r"\b(cups?|tablespoons?|teaspoons?|tbsp|tsp|grams?|g|kg|ml|litres?|liters?|oz|ounces?|pounds?|lb|cloves?|fresh|dried|chopped|minced|boneless|skinless|medium|large|small)\b", "", clean, flags=re.I)
        clean = re.sub(r"[^a-z -]", " ", clean)
        clean = " ".join(clean.split()).strip(" -")
        if clean and not any(term in clean for term in (main_food, "salt", "black pepper", "to taste")):
            if any(word in clean for word in ("mustard", "honey", "lemon", "lime", "garlic", "ginger", "oregano", "paprika", "cumin", "curry", "chili", "chilli", "soy sauce", "sesame", "thyme", "rosemary", "basil", "coriander", "parsley")):
                seasoning_terms.append(clean)
    seasoning_text = ", ".join(dict.fromkeys(seasoning_terms[:5])) or "the listed seasonings"

    # The old library contains generic templates which can be made to look specific
    # by substituting ingredient names, but that does not create a tested recipe.
    # Block those entries until their actual method is written and reviewed.
    generic_instruction_patterns = (
        r"\bmain ingredient\b",
        r"\blisted flavorings?\b",
        r"\bflavorings\b",
        r"\bvegetables of choice\b",
        r"\bcook until ready\b",
        r"\bif it requires cooking\b",
        r"\bsafely cooked through(?:,? where applicable)?\b",
        r"\bwhere applicable\b",
    )
    original_steps = [str(step) for step in result.get("instructions", [])]
    for step in original_steps:
        if any(re.search(pattern, step, re.I) for pattern in generic_instruction_patterns):
            raise ValueError(
                f"Recipe '{title}' still contains generic template instructions; "
                "manual recipe-specific review is required before publishing."
            )

    instructions = []
    for step in result.get("instructions", []):
        step = re.sub(r"the main ingredient|main ingredient", main_food, str(step), flags=re.I)
        step = re.sub(r"the listed flavorings|listed flavorings|flavorings", seasoning_text, step, flags=re.I)
        step = re.sub(r"vegetables of choice", "the vegetables listed in the ingredients", step, flags=re.I)
        step = re.sub(r"cook until ready", "cook until tender and safely cooked through", step, flags=re.I)
        instructions.append(step)
    # Replace vague safety wording with a concrete internal-temperature target.
    protein = next((label for tokens, label in main_groups if tokens & title_tokens), "")
    safe_temp = None
    if protein in {"chicken", "turkey"}:
        safe_temp = "74°C (165°F) at the thickest part"
    elif protein in {"salmon", "shrimp", "tuna"}:
        safe_temp = "63°C (145°F) for fish, or until shrimp are opaque and firm"
    if safe_temp:
        instructions = [
            re.sub(
                r"safely cooked through(?:, where applicable)?",
                "reaches " + safe_temp,
                step,
                flags=re.I
            )
            for step in instructions
        ]
    result["instructions"] = instructions

    placeholders = ("main ingredient", "flavorings", "vegetables of choice", "cook until ready")
    if any(any(marker in step.lower() for marker in placeholders) for step in instructions):
        raise ValueError(f"Recipe '{title}' still contains generic instruction placeholders.")
    if len(instructions) < 4:
        raise ValueError(f"Recipe '{title}' needs at least four clear, sequential instructions.")
    return result

def _is_authorized_video_channel(channel_id):
    # Accept a real YouTube channel ID; publisher identity is checked against
    # search metadata and then re-confirmed with YouTube oEmbed below.
    return bool(re.fullmatch(r"UC[A-Za-z0-9_-]{22}", str(channel_id or "").strip()))

def food_network_recipe_article_url(description):
    """Extract a direct Food Network recipe-page URL from the official video's description."""
    text = str(description or "")
    candidates = re.findall(r"https?://[^\s<>\"']+", text)
    for candidate in candidates:
        candidate = candidate.rstrip(").,;]")
        parsed = urllib.parse.urlparse(candidate)
        host = (parsed.hostname or "").lower()
        if host not in {"foodnetwork.com", "www.foodnetwork.com"}:
            continue
        if not parsed.path.startswith("/recipes/"):
            continue
        return urllib.parse.urlunparse(("https", "www.foodnetwork.com", parsed.path, "", parsed.query, ""))
    return ""


def _check_video_candidate(recipe, video_id, title, channel_id="", source_article_url="", expected_publisher=""):
    """Validate a real creator-published YouTube recipe video and its live metadata."""
    if not _is_authorized_video_channel(channel_id):
        return None
    parsed_source = urllib.parse.urlparse(str(source_article_url or ""))
    if source_article_url and (
        (parsed_source.hostname or "").lower() not in {"foodnetwork.com", "www.foodnetwork.com"}
        or not parsed_source.path.startswith("/recipes/")
    ):
        return None
    video_id = str(video_id or "").strip()
    title = str(title or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or not title:
        return None
    if not _video_title_is_compatible(recipe, title):
        return None
    score = _video_title_score(recipe.get("title", ""), title)
    if score < 0.72:
        return None
    # YouTube oEmbed rejects removed/private videos and many videos that disallow embedding.
    oembed_url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({
        "url": "https://www.youtube.com/watch?v=" + video_id, "format": "json"
    })
    request = urllib.request.Request(
        oembed_url,
        headers={"Accept": "application/json", "User-Agent": "SolePickRecipePublisher/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            metadata = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    # Trust the live YouTube metadata, not stale search-index data.
    live_title = str(metadata.get("title") or "").strip()
    if not live_title or not _video_title_is_compatible(recipe, live_title):
        return None
    live_score = _video_title_score(recipe.get("title", ""), live_title)
    if live_score < 0.72:
        return None
    live_author = str(metadata.get("author_name") or "").strip()
    publisher = str(expected_publisher or AUTHORIZED_VIDEO_CHANNELS.get(channel_id) or live_author).strip()
    if not live_author or live_author.casefold() != publisher.casefold():
        return None
    author_url = urllib.parse.urlparse(str(metadata.get("author_url") or ""))
    if channel_id not in AUTHORIZED_VIDEO_CHANNELS and (author_url.hostname or "").lower() not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        return None
    return {
        "id": video_id,
        "title": live_title,
        "url": "https://www.youtube.com/watch?v=" + video_id,
        "embed_url": "https://www.youtube-nocookie.com/embed/" + video_id,
        "match_score": round(live_score, 2),
        "channel_id": channel_id,
        "publisher": publisher,
        "source_article_url": ("https://www.foodnetwork.com" + parsed_source.path + (("?" + parsed_source.query) if parsed_source.query else "")) if source_article_url else "",
    }


def search_verified_recipe_videos(query):
    """Search public indexes for real YouTube creator uploads with live-verifiable metadata.

    This is a fallback for hosted runners where YouTube's direct search endpoint
    returns a bot-verification challenge. Results are re-verified with
    YouTube oEmbed, channel ID, creator name, live title and embeddability.
    """
    instances = [
        "https://invidious.logicism.tv",
        "https://inv.nadeko.net",
        "https://yewtu.be",
    ]
    for instance in instances:
        endpoint = instance + "/api/v1/search?" + urllib.parse.urlencode({
            "q": query, "type": "video", "sort_by": "relevance"
        })
        request = urllib.request.Request(
            endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": "SolePickRecipesBot/1.0 (+https://solepick.site)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                continue
            matches = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                channel_id = str(item.get("authorId") or "").strip()
                publisher = str(item.get("author") or "").strip()
                if not _is_authorized_video_channel(channel_id) or not publisher:
                    continue
                video_id = str(item.get("videoId") or "").strip()
                title = str(item.get("title") or "").strip()
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) and title:
                    matches.append({
                        "id": video_id,
                        "title": title,
                        "channel_id": channel_id,
                        "publisher": publisher,
                        "description": str(item.get("description") or ""),
                    })
            if matches:
                print(f"INVIDIOUS VIDEO SEARCH: {instance} returned {len(matches)} creator candidate(s) for live verification.")
                return matches
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
            print(f"INVIDIOUS VIDEO SEARCH: {instance} unavailable ({type(error).__name__}); trying another public index.")
    return []


def find_verified_recipe_video(recipe):
    """Automatically discover and validate a matching, currently embeddable YouTube video."""
    # Re-check a configured video first, but do not make manual catalogue flags a blocker.
    configured = str(recipe.get("video_url") or "").strip()
    match = re.fullmatch(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})(?:[&?].*)?",
        configured
    )
    if match:
        candidate = _check_video_candidate(recipe, match.group(1), recipe.get("video_title", ""), recipe.get("video_channel_id", ""), recipe.get("source_article_url", ""))
        if candidate:
            return candidate

    # yt-dlp is installed by the scheduled GitHub Actions workflow. Search multiple
    # results so a removed, private, or unrelated top result does not stop publishing.
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("Automatic video search unavailable: install yt-dlp in the workflow.") from None

    title = str(recipe.get("title") or "").strip()
    if not title:
        raise RuntimeError("Cannot search for a recipe video without a recipe title.")
    # Search broadly enough to recover from sparse YouTube results without
    # weakening the strict protein/dish-format and live-embeddability checks.
    # A recipe is published only after a title-compatible video passes oEmbed.
    queries = [
        f"ytsearch30:{title} recipe",
        f"ytsearch20:{title} cooking",
    ]
    seen = set()
    failures = 0
    for search_query in queries:
        options = {
            "quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": True, "noplaylist": True, "ignoreerrors": True,
            "socket_timeout": 12, "retries": 1,
            # Use YouTube's embeddable web client: it is designed for public
            # embedded playback and avoids relying on a signed-in browser session.
            "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                result = ydl.extract_info(search_query, download=False)
        except Exception as error:
            print(f"VIDEO SEARCH RETRY: {search_query} failed ({type(error).__name__}).")
            continue
        entries = (result or {}).get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            video_id = str(entry.get("id") or "").strip()
            title_found = str(entry.get("title") or "").strip()
            channel_id = str(entry.get("channel_id") or "").strip()
            if not _is_authorized_video_channel(channel_id):
                continue
            if video_id in seen:
                continue
            seen.add(video_id)
            if not _video_title_is_compatible(recipe, title_found):
                continue
            if _video_title_score(title, title_found) < 0.72:
                continue
            description = str(entry.get("description") or "")
            source_article_url = food_network_recipe_article_url(description)
            if not source_article_url:
                # YouTube often blocks unauthenticated description lookups from
                # hosted CI. The verified official channel, exact dish title and
                # live oEmbed author/title checks are sufficient provenance;
                # an optional Food Network recipe link is retained when present.
                print("VIDEO SOURCE NOTE: official channel result has no exposed recipe URL; validating channel, live title and embeddability directly.")
            publisher = str(entry.get("channel") or entry.get("uploader") or "").strip()
            candidate = _check_video_candidate(recipe, video_id, title_found, channel_id, source_article_url, publisher)
            if candidate:
                print(f"AUTO-SELECTED VIDEO: {candidate['title']} | match={candidate['match_score']} | live oEmbed check passed.")
                return candidate
            failures += 1
    # Public-index fallback: YouTube direct search is frequently bot-challenged
    # on GitHub-hosted runners. Creator names and channel IDs are checked against
    # live YouTube oEmbed metadata before any video can be used.
    for query in (f"{title} recipe", f"{title} cooking"):
        for entry in search_verified_recipe_videos(query):
            video_id = entry["id"]
            if video_id in seen:
                continue
            seen.add(video_id)
            if not _video_title_is_compatible(recipe, entry["title"]):
                continue
            if _video_title_score(title, entry["title"]) < 0.72:
                continue
            source_article_url = food_network_recipe_article_url(entry.get("description", ""))
            candidate = _check_video_candidate(
                recipe, video_id, entry["title"], entry["channel_id"], source_article_url, entry.get("publisher", "")
            )
            if candidate:
                print(f"AUTO-SELECTED VIDEO: {candidate['title']} | publisher={candidate['publisher']} | live oEmbed check passed.")
                return candidate

    raise RuntimeError(
        f"No currently embeddable, title-matched verified-publisher video found for '{title}' after checking "
        f"{len(seen)} candidates ({failures} direct-search candidate checks failed). "
        "All configured public video indexes were exhausted; the workflow will retry at the next scheduled run."
    )

def recipe_video_section_html(recipe, video):
    """Render the base recipe video without the custom caption-selection box."""
    video_id = str(video.get("id") or "")
    frame_id = "solepick-video-" + video_id
    source_article_url = str(video.get("source_article_url") or "").strip()
    source_article_link = (
        f" <a href='{esc(source_article_url)}' target='_blank' rel='noopener noreferrer'>View the publisher's original recipe article</a>."
        if source_article_url else ""
    )
    return (
        "<h2>Watch the Recipe Video Here</h2>"
        f"<p><small>Video: {esc(video.get('publisher', 'Food Network'))}. <a href='{esc(video['url'])}' target='_blank' rel='noopener noreferrer'>Watch the original video</a>."
        f"{source_article_link}</small></p>"
        f"<div class=\"solepick-recipe-video\" style=\"position:relative;width:100%;aspect-ratio:16/9;background:#111;margin:0 0 1rem;overflow:hidden;\">"
        f"<iframe id=\"{esc(frame_id)}\" class=\"solepick-language-aware-video\" data-video-base=\"{esc(video['embed_url'])}\" src=\"{esc(video['embed_url'])}?playsinline=1\" title=\"{esc(recipe['title'])} recipe video\" "
        "loading=\"eager\" allow=\"accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share\" "
        "referrerpolicy=\"strict-origin-when-cross-origin\" allowfullscreen style=\"position:absolute;inset:0;width:100%;height:100%;border:0;display:block;\"></iframe>"
        "</div>"
        f"<p><small>If the player does not load, <a href=\"{esc(video['url'])}\" target=\"_blank\" rel=\"noopener noreferrer\">watch this video on YouTube</a>.</small></p>"
    )

def upsert_recipe_video_section(existing_body, recipe, video):
    """Insert or replace only the video section, preserving the article's other content."""
    section = recipe_video_section_html(recipe, video)
    pattern = r"<h2\b[^>]*>\s*(?:Recipe Video|Watch the Recipe Video Here)\s*</h2>.*?(?=<h2\b|$)"
    if re.search(pattern, existing_body, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(pattern, lambda _match: section, existing_body, count=1, flags=re.IGNORECASE | re.DOTALL)
    match = re.search(r"<h2\b", existing_body, flags=re.IGNORECASE)
    if match:
        return existing_body[:match.start()] + section + existing_body[match.start():]
    return existing_body.rstrip() + "\n" + section


def _image_identity(url):
    """Normalize CDN copies of the same source photo to one stable identity."""
    value = str(url or "").strip()
    if not value:
        return ""
    parsed = urllib.parse.urlparse(value)
    path = urllib.parse.unquote(parsed.path).lower()
    filename = path.rsplit("/", 1)[-1]
    # Shopify appends a unique UUID to each imported copy, so strip it to detect
    # the same original photo across different articles.
    filename = re.sub(r"_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?=\.)", "", filename)
    return filename


def _is_retail_product_image(title_text, image_url="", metadata=None):
    """Reject grocery-store shelves, retail aisles, packaged-goods displays and product shots."""
    metadata = metadata or {}
    parts = [str(title_text or ""), str(image_url or "")]
    for key in ("ObjectName", "ImageDescription", "Description", "Categories"):
        item = metadata.get(key) or {}
        value = item.get("value", "") if isinstance(item, dict) else item
        if isinstance(value, list):
            value = " ".join(map(str, value))
        parts.append(re.sub(r"<[^>]+>", " ", str(value or "")))
    tokens = set(re.findall(r"[a-z0-9]+", " ".join(parts).lower()))
    retail_terms = {
        "supermarket", "grocery", "groceries", "market", "store", "shelf", "shelves",
        "aisle", "aisles", "retail", "checkout", "cashier", "shopping", "shop",
        "packaging", "package", "packaged", "product", "products", "brand", "brands",
        "display", "displayed", "merchandise", "stock", "stocked", "price", "prices",
        "barcode", "carton", "cartons", "box", "boxes", "cans", "bottles", "wrapper",
        "wrappers", "label", "labels"
    }
    # "market" is too broad on its own (e.g. farmers-market food photography);
    # require a more specific retail cue for that word.
    strong_terms = retail_terms - {"market", "store", "shop", "product", "brand", "display", "stock"}
    if tokens & strong_terms:
        return True
    if "market" in tokens and tokens & {"aisle", "shelf", "supermarket", "grocery", "retail", "checkout"}:
        return True
    if tokens & {"store", "shop", "product", "brand", "display", "stock"} and tokens & {"shelf", "shelves", "aisle", "packaging", "package", "packaged", "barcode", "price", "prices", "carton", "boxes"}:
        return True
    return False


def _is_document_like_image(title_text, image_url, metadata):
    """Reject document scans and PDF-preview thumbnails using filename and descriptive metadata."""
    path = urllib.parse.unquote(urllib.parse.urlparse(str(image_url or "")).path).lower()
    if ".pdf." in path or path.endswith(".pdf"):
        return True
    reject_terms = {
        "document", "archived", "archive", "historic", "historical", "scientific",
        "policy", "policies", "practice", "practices", "pdf", "scan", "scanned",
        "manuscript", "book", "journal", "report", "form", "letter", "newspaper",
        "magazine", "blueprint", "screenshot", "screengrab",
    }
    parts = [str(title_text or "")]
    for key in ("ObjectName", "ImageDescription", "Description", "Categories"):
        item = metadata.get(key) or {}
        value = item.get("value", "") if isinstance(item, dict) else item
        if isinstance(value, list):
            value = " ".join(map(str, value))
        parts.append(re.sub(r"<[^>]+>", " ", str(value or "")))
    tokens = set(re.findall(r"[a-z0-9]+", " ".join(parts).lower()))
    return bool(tokens & reject_terms)


def generate_recipe_image(recipe, published_articles=None):
    """Find a dish-relevant public-domain/CC0 photo unique across catalogue and published Shopify articles."""
    catalogue = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    used_urls = {
        str(item.get("image_url") or "").strip()
        for item in catalogue
        if item.get("slug") != recipe.get("slug") and item.get("image_url")
    }
    for article in (published_articles or []):
        image = article.get("image") or {}
        if image.get("url"):
            used_urls.add(str(image["url"]).strip())
    used_identities = {_image_identity(url) for url in used_urls if _image_identity(url)}
    # Search Commons using the actual dish name. Prefer exact recipe terms and reject
    # generic images unless both a main ingredient and dish-format anchor are present.
    title = str(recipe.get("title") or "").strip()
    if not title:
        raise RuntimeError("Cannot search for a food photo without a recipe title.")
    query_terms = re.findall(r"[a-z0-9]+", title.lower())
    stop = {"with", "and", "the", "a", "an", "of", "in", "on", "easy", "quick", "recipe"}
    wanted = {word for word in query_terms if word not in stop and len(word) > 2}
    main_food = next((word for word in ("salmon","chicken","shrimp","prawn","tofu","beef","tuna","turkey","lentil","lentils","chickpea","chickpeas","bean","beans","pasta","noodle","noodles","rice","egg","eggs","potato","potatoes","mushroom","mushrooms") if word in wanted), None)
    formats = {"salad","pasta","noodle","noodles","bowl","bowls","taco","tacos","soup","curry","wrap","wraps","sandwich","sandwiches","rice","tray","hash","potato","potatoes","stuffed","pizza","stew","dal"}
    wanted_formats = wanted & formats
    # Wikimedia added global API rate limits in 2026. Use three distinct
    # searches instead of five near-duplicates for every recipe.
    searches = [
        title + " food",
        " ".join(word for word in query_terms if word not in stop) + " plated meal",
        (main_food or title) + " " + (" ".join(sorted(wanted_formats)) if wanted_formats else "cooked dish"),
    ]
    seen = set()
    # Reject non-food scans and document thumbnails, including PDF previews Shopify can show as .pdf.jpg.
    reject_terms = {"seed", "seeds", "catalogue", "catalog", "flower", "flowers", "illustration", "poster", "advertisement", "advert", "logo", "clipart", "drawing", "painting", "poultry", "supplies", "document", "archived", "archive", "historic", "historical", "scientific", "policy", "policies", "practice", "practices", "pdf", "scan", "scanned", "manuscript", "page"}
    for search_text in searches:
        params = urllib.parse.urlencode({
            "action": "query", "generator": "search", "gsrsearch": search_text,
            "gsrnamespace": 6, "gsrlimit": 10, "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": 1600, "format": "json",
        })
        request = urllib.request.Request(
            "https://commons.wikimedia.org/w/api.php?" + params,
            headers={"User-Agent": "SolePickRecipesBot/1.1 (https://solepick.site; recipe image selection)"}
        )
        # Respect Retry-After and avoid retry storms. If Commons is still
        # rate-limiting after one retry, move to the next distinct search term.
        payload = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code < 600
                print(f"WIKIMEDIA PHOTO SEARCH attempt {attempt + 1}/2: HTTP {error.code}")
                if not retryable or attempt == 1:
                    break
                retry_after = error.headers.get("Retry-After", "")
                try:
                    delay = min(30, max(5, int(retry_after)))
                except (TypeError, ValueError):
                    delay = 5 * (attempt + 1)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
                print(f"WIKIMEDIA PHOTO SEARCH attempt {attempt + 1}/2: {type(error).__name__}")
                if attempt == 1:
                    break
                time.sleep(5)
        if payload is None:
            continue
        pages = ((payload.get("query") or {}).get("pages") or {})
        for page in pages.values():
            title_text = str(page.get("title") or "").lower()
            info_list = page.get("imageinfo") or []
            if not info_list:
                continue
            info = info_list[0]
            metadata = info.get("extmetadata") or {}
            license_name = str((metadata.get("LicenseShortName") or {}).get("value") or "").strip()
            license_lower = re.sub(r"<[^>]+>", "", license_name).lower()
            # Restrict to public-domain/CC0 media to avoid needing per-image credit lines.
            if "public domain" not in license_lower and "cc0" not in license_lower:
                continue
            image_url = str(info.get("thumburl") or info.get("url") or "").strip()
            # Commons can expose scans and PDF pages as ordinary JPEG thumbnails.
            # Reject candidates based on URL plus descriptive metadata, not extension alone.
            if _is_document_like_image(title_text, image_url, metadata):
                print("REJECTED DOCUMENT/ARCHIVE/SCAN IMAGE: " + title_text)
                continue
            if _is_retail_product_image(title_text, image_url, metadata):
                print("REJECTED GROCERY/RETAIL/PACKAGED-PRODUCT IMAGE: " + title_text)
                continue
            mime = str(info.get("mime") or "").lower()
            width = int(info.get("thumbwidth") or info.get("width") or 0)
            height = int(info.get("thumbheight") or info.get("height") or 0)
            if mime and not mime.startswith("image/"):
                print("REJECTED NON-IMAGE MEDIA: " + title_text + " | mime=" + mime)
                continue
            quality = inspect_image_url(image_url)
            if not is_high_quality_image(quality):
                print("REJECTED LOW-QUALITY IMAGE: " + title_text + " | " + str(quality))
                continue
            if (
                not image_url.startswith("https://")
                or image_url in used_urls
                or _image_identity(image_url) in used_identities
                or image_url in seen
                or _image_identity(image_url) in {_image_identity(item) for item in seen}
            ):
                print("REJECTED DUPLICATE PHOTO: " + title_text)
                continue
            seen.add(image_url)
            found = set(re.findall(r"[a-z0-9]+", title_text))
            if found & reject_terms:
                print("REJECTED UNRELATED IMAGE TITLE: " + title_text)
                continue
            overlap = len(wanted & found) / max(1, len(wanted))
            has_main = bool(main_food and main_food in found)
            has_format = bool(wanted_formats & found)
            # Require meaningful dish relevance, not merely a generic food photograph.
            if overlap < 0.40 and not (has_main and (has_format or len(wanted_formats) == 0)):
                continue
            if main_food and not has_main:
                continue
            if wanted_formats and not has_format:
                continue
            alt = " ".join((title_text.removeprefix("file:")).replace("_", " ").split())
            alt = re.sub(r"\.(jpg|jpeg|png|webp|svg)$", "", alt, flags=re.I)
            alt = (alt[:240] or "Food photograph for " + title)
            print("AUTO-SELECTED PUBLIC-DOMAIN PHOTO: " + title_text + " | license=" + license_name)
            return {"url": image_url, "altText": alt}
    # No unreviewed catalogue fallback: that was the cause of repeated/mismatched photos.
    raise RuntimeError(
        "No unique, relevant public-domain/CC0 Wikimedia photo found automatically for '"
        + title + "'. Recipe was not published with a repeated or unverified image; "
        "the next scheduled run will retry."
    )

def catalogue_image_fallback(recipe, published_articles=None):
    """Use a relevant catalogue photo only if its source is unique across catalogue and published articles."""
    url = str(recipe.get("image_url") or "").strip()
    alt = str(recipe.get("image_alt") or "").strip()
    if not url.startswith("https://") or not alt:
        return None
    # A catalogue alt-text describing a PDF/archive is not a food photo.
    alt_tokens = set(re.findall(r"[a-z0-9]+", alt.lower()))
    if alt_tokens & {"document", "archived", "archive", "historic", "historical", "scientific", "policy", "practice", "pdf", "scan", "scanned", "manuscript"}:
        print("REJECTED NON-FOOD CATALOGUE IMAGE: " + recipe.get("title", "(untitled)"))
        return None
    if ".pdf." in urllib.parse.unquote(urllib.parse.urlparse(url).path).lower():
        print("REJECTED PDF THUMBNAIL FROM CATALOGUE: " + recipe.get("title", "(untitled)"))
        return None
    if _is_retail_product_image(alt, url):
        print("REJECTED GROCERY/RETAIL CATALOGUE IMAGE: " + recipe.get("title", "(untitled)"))
        return None

    catalogue = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    used_urls = {
        str(item.get("image_url") or "").strip()
        for item in catalogue
        if item.get("slug") != recipe.get("slug") and item.get("image_url")
    }
    for article in (published_articles or []):
        image = article.get("image") or {}
        if image.get("url"):
            used_urls.add(str(image["url"]).strip())
    image_id = _image_identity(url)
    if url in used_urls or (image_id and image_id in {_image_identity(item) for item in used_urls}):
        print("REJECTED DUPLICATE CATALOGUE PHOTO: " + recipe.get("title", "(untitled)"))
        return None

    title_words = set(re.findall(r"[a-z0-9]+", str(recipe.get("title") or "").lower()))
    alt_words = set(re.findall(r"[a-z0-9]+", alt.lower()))
    stop = {"with", "and", "the", "a", "an", "of", "in", "on", "easy", "quick", "recipe", "fresh", "colorful", "served", "ready"}
    wanted = {word for word in title_words if word not in stop and len(word) > 2}
    formats = {"salad","pasta","noodle","noodles","bowl","bowls","taco","tacos","soup","curry","wrap","wraps","sandwich","sandwiches","rice","tray","hash","potato","potatoes","stuffed","pizza","stew","dal"}
    main_food = next((word for word in ("salmon","chicken","shrimp","prawn","tofu","beef","tuna","turkey","lentil","lentils","chickpea","chickpeas","bean","beans","pasta","noodle","noodles","rice","egg","eggs","potato","potatoes","mushroom","mushrooms") if word in wanted), None)
    wanted_formats = wanted & formats
    overlap = len(wanted & alt_words) / max(1, len(wanted))
    has_main = bool(main_food and main_food in alt_words)
    has_format = bool(wanted_formats & alt_words)

    # Do not use a generic or clearly unrelated catalogue image just to force a post.
    if main_food and not has_main:
        return None
    if wanted_formats and not has_format and overlap < 0.45:
        return None
    if overlap < 0.25 and not has_main:
        return None

    print("USING RELEVANT PRE-CURATED CATALOGUE PHOTO AS FALLBACK: " + recipe["title"])
    return {"url": url, "altText": alt}


def youtube_thumbnail_for(recipe, video):
    """Use only the verified publisher video's own high-resolution thumbnail."""
    video_id = str(video.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise RuntimeError("Cannot select a thumbnail without a verified publisher video ID.")
    for url in (
        f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
        f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
    ):
        quality = inspect_image_url(url)
        if is_high_quality_image(quality):
            publisher = str(video.get("publisher") or "Verified publisher")
            return {"url": url, "altText": f"{publisher} cooking video thumbnail for {recipe['title']}", "source_type": "official_youtube_thumbnail", "publisher": publisher}
        print(f"REJECTED PUBLISHER THUMBNAIL: {url} | {quality}")
    raise RuntimeError("No high-resolution verified creator thumbnail passed image checks; refusing to publish.")


def featured_image_for(recipe, generated_image):
    """Require the verified official publisher thumbnail; no generated or stock fallback."""
    image = generated_image or {}
    url = str(image.get("url") or "").strip()
    image_path = urllib.parse.unquote(urllib.parse.urlparse(url).path).lower()
    alt_tokens = set(re.findall(r"[a-z0-9]+", str(image.get("altText") or "").lower()))
    forbidden_alt = {"document", "archived", "archive", "historic", "historical", "scientific", "policy", "practice", "pdf", "scan", "scanned", "manuscript"}
    if ".pdf." in image_path or image_path.endswith(".pdf") or (alt_tokens & forbidden_alt):
        raise RuntimeError("Rejected document/PDF-style image for " + recipe["title"] + "; refusing to publish without a real food photo.")
    if _is_retail_product_image(str(image.get("altText") or ""), url):
        raise RuntimeError("Rejected grocery-store, retail-shelf or packaged-product image for " + recipe["title"] + "; refusing to publish without a prepared-food photograph.")
    if image.get("source_type") != "official_youtube_thumbnail" or not url.startswith("https://img.youtube.com/vi/"):
        raise RuntimeError("Featured image must be the verified official publisher video thumbnail.")
    quality = inspect_image_url(url)
    if not is_high_quality_image(quality):
        raise RuntimeError("Rejected low-resolution or soft recipe image for " + recipe["title"] + ": " + str(quality))
    alt = str(image.get("altText") or "").strip()
    publisher = str(image.get("publisher") or "").strip()
    if not publisher or publisher == "Verified publisher" or publisher.casefold() not in alt.casefold():
        raise RuntimeError("Verified creator thumbnail is missing creator-specific alt text for " + recipe["title"])
    # Preserve the verification provenance for the second validation performed
    # inside create_published/articleUpdate. Dropping source_type here caused
    # already-verified thumbnails to be rejected at the final Shopify boundary.
    return {**image, "url": url, "altText": alt}

def seo_metadata(recipe):
    """Create concise, intent-led search metadata without keyword stuffing."""
    title = re.sub(r"\s+", " ", str(recipe.get("title", "")).strip())
    seo_title = title if len(title) <= 58 else title[:55].rsplit(" ", 1)[0].rstrip(" -|:") + " | SolePick"
    description = re.sub(r"\s+", " ", str(recipe.get("description", "")).strip())
    if not description:
        description = f"Make {title} with clear step-by-step instructions and everyday ingredients."
    if len(description) > 155:
        description = description[:152].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
    elif len(description) < 110:
        description = (description.rstrip(".") + ". Get the ingredients, prep time and easy step-by-step method.").strip()
        description = description[:155].rsplit(" ", 1)[0].rstrip(" ,;:")
    return {"title": seo_title, "description": description}


def recipe_editorial_sections(recipe):
    """Render only recipe-specific practical notes supplied and reviewed in recipes.json."""
    sections = []
    notes = [str(value).strip() for value in recipe.get("cook_notes", []) if str(value).strip()]
    swaps = [str(value).strip() for value in recipe.get("substitutions", []) if str(value).strip()]
    storage = str(recipe.get("storage") or "").strip()
    if notes:
        sections.append("<h2>Recipe Tips</h2><ul>" + "".join(f"<li>{esc(value)}</li>" for value in notes) + "</ul>")
    if swaps:
        sections.append("<h2>Ingredient Swaps</h2><ul>" + "".join(f"<li>{esc(value)}</li>" for value in swaps) + "</ul>")
    if storage:
        sections.append("<h2>Make-Ahead and Storage</h2><p>" + esc(storage) + "</p>")
    return "".join(sections)


def related_recipe_links(recipe, published_handles=None):
    """Add up to three contextual links to published/approved related SolePick recipes."""
    try:
        catalogue = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    current_tags = set(recipe.get("tags") or [])
    allowed_handles = set(published_handles or [])
    ranked = []
    for item in catalogue:
        if item.get("slug") == recipe.get("slug") or item.get("slug") not in allowed_handles:
            continue
        overlap = len(current_tags & set(item.get("tags") or []))
        if overlap:
            ranked.append((overlap, item.get("title", ""), item.get("slug", "")))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    links = [
        f'<li><a href="https://solepick.site/blogs/recipes/{esc(slug)}">{esc(title)}</a></li>'
        for _, title, slug in ranked[:3] if title and slug
    ]
    if not links:
        return ""
    return "<h2>More Recipes to Try</h2><ul>" + "".join(links) + "</ul>"


def recipe_json_ld(recipe):
    """Schema.org Recipe JSON-LD for search engines and recipe rich results."""
    metadata = seo_metadata(recipe)
    image = recipe.get("published_image_url") or recipe.get("image_url")
    data = {
        "@context": "https://schema.org",
        "@type": "Recipe",
        "name": recipe["title"],
        "description": metadata["description"],
        "author": {"@type": "Organization", "name": "SolePick Recipes", "url": "https://solepick.site/"},
        "datePublished": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
        "keywords": ", ".join(dict.fromkeys(
            [str(recipe.get("title") or "").strip()]
            + [str(value).strip() for value in recipe.get("tags", [])]
            + [str(value).strip() for value in recipe.get("ingredients", [])]
        ))[:500],
        **({"video": {"@type": "VideoObject", "name": recipe["title"] + " video", "contentUrl": recipe.get("published_video_url"), "embedUrl": recipe.get("published_video_url"), "thumbnailUrl": image}} if recipe.get("published_video_url") else {}),
        "prepTime": f"PT{int(recipe['prep_minutes'])}M",
        "cookTime": f"PT{int(recipe['cook_minutes'])}M",
        "totalTime": f"PT{int(recipe['prep_minutes']) + int(recipe['cook_minutes'])}M",
        "recipeYield": str(recipe["servings"]),
        "recipeCategory": ", ".join(recipe.get("tags", [])[:3]),
        "recipeIngredient": recipe["ingredients"],
        "recipeInstructions": [
            {"@type": "HowToStep", "position": index, "text": step}
            for index, step in enumerate(recipe["instructions"], 1)
        ],
    }
    if image:
        data["image"] = [image]
    slug = str(recipe.get("slug") or "").strip()
    if slug and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        canonical = "https://solepick.site/blogs/recipes/" + slug
        data["url"] = canonical
        data["mainEntityOfPage"] = {"@type": "WebPage", "@id": canonical}
    return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def article_html(recipe, video=None, published_handles=None):
    ingredients = "".join(f"<li>{esc(item)}</li>" for item in recipe["ingredients"])
    steps = "".join(f"<li>{esc(item)}</li>" for item in recipe["instructions"])
    video_html = recipe_video_section_html(recipe, video) if video else ""
    metadata = seo_metadata(recipe)
    related = related_recipe_links(recipe, published_handles)
    return (
        f"<p>{esc(metadata['description'])}</p>"
        f"<p><strong>Prep:</strong> {recipe['prep_minutes']} minutes · "
        f"<strong>Cook:</strong> {recipe['cook_minutes']} minutes · "
        f"<strong>Serves:</strong> {recipe['servings']}</p>"
        f"{video_html}"
        "<p><small>Video credit: Food Network. Recipe text and method are independently authored by SolePick Recipes; see the publisher's original recipe article above.</small></p>"
        f"<h2>Ingredients</h2><ul>{ingredients}</ul>"
        f"<h2>Instructions</h2><ol>{steps}</ol>"
        f"{recipe_editorial_sections(recipe)}"
        f"{related}"
        "<p><em>Check labels for allergens and follow safe food-handling practices. "
        "Cooking times vary; verify food is safely cooked before serving.</em></p>"
        f"{recipe_json_ld(recipe)}"
    )


def expected_schedule_cron(now=None):
    now = now or datetime.datetime.now(CAIRO)
    return "0 7 * * *" if now.utcoffset() == datetime.timedelta(hours=3) else "0 8 * * *"


def should_run_scheduled_event(event_schedule, now=None):
    """Accept the seasonal 10:00 Cairo trigger and a later same-day recovery run."""
    now = now or datetime.datetime.now(CAIRO)
    if event_schedule == expected_schedule_cron(now):
        return True
    # The non-primary seasonal trigger or the 09:00 UTC recovery trigger may
    # be the only run GitHub delivers. Never publish before 10:00 Cairo;
    # after 10:00, the daily Shopify idempotency guard makes retries safe.
    return now.hour >= 10


def already_published_today(articles, now=None, recipe_slugs=None):
    """Return today's published recipe, ignoring unrelated blog posts."""
    now = now or datetime.datetime.now(CAIRO)
    allowed_slugs = set(recipe_slugs) if recipe_slugs is not None else None
    for article in articles.values():
        # The Shopify blog may also contain editorial or legacy articles.
        # Only handles from recipes.json can consume the daily recipe slot.
        if allowed_slugs is not None and article.get("handle") not in allowed_slugs:
            continue
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
    """Exchange the Dev Dashboard app credentials for a short-lived Admin API token."""
    client_id = os.environ.get("SHOPIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise RuntimeError("Set both SHOPIFY_CLIENT_ID and SHOPIFY_CLIENT_SECRET GitHub Actions secrets.")
    payload = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode("ascii")
    req = urllib.request.Request(
        f"https://{domain}/admin/oauth/access_token",
        data=payload,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as error:
        error_code = ""
        try:
            error_payload = json.loads(error.read().decode())
            error_code = str(error_payload.get("error") or "")
        except Exception:
            pass
        detail = f" ({error_code})" if error_code else ""
        raise RuntimeError(
            f"Shopify client-credentials exchange failed with HTTP {error.code}{detail}; "
            "verify that the app credentials are current and the store belongs to the app's Shopify organization."
        ) from None
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Shopify returned no access token from the client-credentials exchange.")
    granted_scopes = {scope.strip() for scope in str(data.get("scope") or "").split(",") if scope.strip()}
    # Shopify write_content includes the corresponding read_content capability.
    # The token response may therefore list write_content without read_content.
    required_scopes = {"write_content"}
    missing_scopes = sorted(required_scopes - granted_scopes)
    if missing_scopes:
        raise RuntimeError(
            "Shopify token is missing required granted scope(s): " + ", ".join(missing_scopes)
            + ". Release/approve an app version with write_content, then retry."
        )
    print("Shopify client-credentials authentication succeeded; write_content grants the required read/write content access.")
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


def resolve_recipe_blog():
    """Always publish to the dedicated Recipes blog, not a legacy News/default blog."""
    query = """query SolePickBlogs {
      blogs(first: 50) { nodes { id title handle } }
    }"""
    data = graphql(query, {})
    blogs = (data.get("blogs") or {}).get("nodes") or []
    recipes_blog = next((item for item in blogs if item.get("handle") == "recipes"), None)
    if recipes_blog:
        print("SHOPIFY BLOG VERIFIED: " + recipes_blog.get("title", "Recipes") +
              " | handle=recipes | id=" + recipes_blog["id"])
        return recipes_blog["id"]

    mutation = """mutation CreateSolePickRecipesBlog($blog: BlogCreateInput!) {
      blogCreate(blog: $blog) {
        blog { id title handle }
        userErrors { field message }
      }
    }"""
    result = graphql(mutation, {"blog": {
        "title": "Recipes", "handle": "recipes", "commentPolicy": "CLOSED"
    }}).get("blogCreate") or {}
    errors = result.get("userErrors") or []
    if errors:
        raise RuntimeError("Unable to create dedicated Recipes blog: " + json.dumps(errors))
    created = result.get("blog")
    if not created or created.get("handle") != "recipes" or not created.get("id"):
        raise RuntimeError("Shopify did not confirm creation of the dedicated Recipes blog.")
    print("SHOPIFY BLOG CREATED AND VERIFIED: Recipes | handle=recipes | id=" + created["id"])
    return created["id"]


def existing_articles(blog_id):
    query = """query ArticleHandles($id: ID!, $after: String) {
      blog(id: $id) { articles(first: 100, after: $after) {
        nodes { id title handle body tags isPublished publishedAt image { url altText width height } }
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
    saved_body = updated.get("body") or ""
    if video["embed_url"] not in saved_body or "<iframe" not in saved_body.lower():
        raise RuntimeError("Shopify update response did not contain the verified embedded video iframe.")
    if re.search(r"<h[1-6][^>]*>\s*Recipe Video\s*</h[1-6]>", saved_body, flags=re.IGNORECASE):
        raise RuntimeError("Shopify saved the legacy Recipe Video heading that the storefront cleanup script removes.")
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


def verify_published_article(article, recipe, video):
    """Fail the workflow unless Shopify saved the actual embedded player in the published body."""
    if not article or not article.get("isPublished"):
        raise RuntimeError("Shopify did not confirm the recipe article is published.")
    body = str(article.get("body") or "")
    if "<iframe" not in body.lower():
        raise RuntimeError(
            f"Shopify did not return an iframe in the saved body for '{recipe['title']}'. "
            "The workflow will not report a successful video publication."
        )
    if video["embed_url"] not in body:
        raise RuntimeError(
            f"Shopify did not return the expected embed URL in the saved body for '{recipe['title']}'."
        )
    if not re.search(r"<h2\b[^>]*>\s*Watch the Recipe Video Here\s*</h2>", body, flags=re.IGNORECASE):
        raise RuntimeError(
            f"Shopify did not return the expected visible video heading for '{recipe['title']}'."
        )
    if "<h2>Ingredients</h2>" not in body or "<h2>Instructions</h2>" not in body:
        raise RuntimeError(f"Shopify's saved body is missing recipe sections for '{recipe['title']}'.")
    if 'application/ld+json' not in body or '"@type": "Recipe"' not in body:
        raise RuntimeError(
            f"Shopify did not preserve Recipe JSON-LD structured data for '{recipe['title']}'."
        )
    return article


def create_published(blog_id, recipe, video, generated_image, published_handles=None):
    mutation = """mutation CreatePublishedArticle($article: ArticleCreateInput!) {
      articleCreate(article: $article) {
        article { id title handle isPublished body }
        userErrors { field message }
      }
    }"""
    # Ensure Recipe JSON-LD references the exact verified image that Shopify
    # receives as the article's featured image, including generated Commons assets.
    recipe_for_markup = dict(recipe)
    recipe_for_markup["published_image_url"] = generated_image.get("url") if generated_image else ""
    recipe_for_markup["published_video_url"] = video.get("url") if video else ""
    article = {
        "blogId": blog_id, "title": recipe["title"], "handle": recipe["slug"],
        "author": {"name": "SolePick Recipes"}, "body": article_html(recipe_for_markup, video, published_handles),
        "summary": seo_metadata(recipe)["description"],
        "metafields": [
            {"namespace": "global", "key": "title_tag", "type": "single_line_text_field", "value": seo_metadata(recipe)["title"]},
            {"namespace": "global", "key": "description_tag", "type": "single_line_text_field", "value": seo_metadata(recipe)["description"]},
        ],
        "tags": recipe.get("tags", []), "isPublished": True,
        "image": featured_image_for(recipe, generated_image),
    }
    result = graphql(mutation, {"article": article}).get("articleCreate") or {}
    if result.get("userErrors"):
        raise RuntimeError("Shopify rejected recipe publishing: " + json.dumps(result["userErrors"]))
    published = result.get("article")
    if not published or not published.get("isPublished"):
        raise RuntimeError("Shopify did not confirm that the new article is published.")
    return published


def persist_generated_recipe_candidates(existing_recipes, generated_candidates, path=RECIPES_PATH):
    """Persist new trend-matched, complete recipes so the daily library grows over time."""
    known = {item.get("slug") for item in existing_recipes}
    additions = []
    required = {"slug", "title", "description", "ingredients", "instructions", "prep_minutes", "cook_minutes", "servings"}
    for candidate in generated_candidates or []:
        missing = sorted(required - set(candidate))
        if missing or candidate.get("slug") in known:
            continue
        if not candidate.get("ingredients") or len(candidate.get("instructions") or []) < 4:
            continue
        additions.append(candidate)
        known.add(candidate["slug"])
    if not additions:
        return []
    current = json.loads(Path(path).read_text(encoding="utf-8"))
    current_slugs = {item.get("slug") for item in current}
    additions = [item for item in additions if item["slug"] not in current_slugs]
    if not additions:
        return []
    updated = current + additions
    Path(path).write_text(json.dumps(updated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PERSISTED TREND RECIPES: {len(additions)} new complete recipes added to recipes.json.")
    return additions


def configured_max_recipes_per_run():
    """Read the daily batch size, capped at three to keep each publishing run controlled."""
    raw = os.environ.get("MAX_RECIPES_PER_RUN", "3").strip()
    try:
        requested = int(raw)
    except ValueError:
        raise ValueError("MAX_RECIPES_PER_RUN must be a whole number from 1 to 3.")
    if requested < 1:
        raise ValueError("MAX_RECIPES_PER_RUN must be a whole number from 1 to 3.")
    return min(requested, 3)


def requested_target_recipes(recipes):
    """Resolve an optional comma-separated list of recipes for a targeted publishing run."""
    raw = os.environ.get("TARGET_RECIPE_SLUGS", "").strip()
    if not raw:
        return None
    slugs = [value.strip() for value in raw.split(",") if value.strip()]
    if not slugs:
        return None
    if len(slugs) != len(set(slugs)):
        raise ValueError("TARGET_RECIPE_SLUGS contains duplicate recipe slugs.")
    by_slug = {recipe["slug"]: recipe for recipe in recipes}
    missing = [slug for slug in slugs if slug not in by_slug]
    if missing:
        raise ValueError("Requested recipe slug(s) not found in recipes.json: " + ", ".join(missing))
    return [by_slug[slug] for slug in slugs]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--repair-handle", help="Update the video section on an existing published Shopify article without creating a new article.")
    parser.add_argument("--one-time-test", action="store_true", help="Manual one-time test: bypass the same-day guard for one eligible new recipe only.")
    args = parser.parse_args()
    max_publish = 1 if args.one_time_test else configured_max_recipes_per_run()
    if args.one_time_test and args.repair_handle:
        parser.error("--one-time-test cannot be combined with --repair-handle")
    now = datetime.datetime.now(CAIRO)
    # Seasonal primary cron plus a recovery path: if GitHub skips the exact
    # 10:00 Cairo run, a later scheduled event may still publish that Cairo day.
    # The Shopify daily idempotency guard below prevents duplicate articles.
    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    event_schedule = os.environ.get("GITHUB_EVENT_SCHEDULE", "").strip()
    if event_name == "schedule" and event_schedule and not should_run_scheduled_event(event_schedule, now):
        print(
            f"Schedule guard: ignoring cron {event_schedule} before 10:00 Cairo; "
            f"primary trigger today is {expected_schedule_cron(now)}."
        )
        return
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

    # Resolve by the stable Recipes blog handle. This deliberately overrides a
    # stale SHOPIFY_BLOG_ID that may still point at the old empty "News" blog.
    blog_id = resolve_recipe_blog()

    if args.repair_handle:
        repair_existing_article_video(blog_id, args.repair_handle.strip(), recipes)
        return

    articles = existing_articles(blog_id)
    published_today = already_published_today(articles, now, recipe_slugs={recipe['slug'] for recipe in recipes})
    if published_today and not args.one_time_test:
        body = str(published_today.get("body") or "")
        video_is_saved = (
            "<iframe" in body.lower()
            and "youtube-nocookie.com/embed/" in body
            and bool(re.search(r"<h2\b[^>]*>\s*Watch the Recipe Video Here\s*</h2>", body, flags=re.IGNORECASE))
        )
        if not video_is_saved:
            print(
                f"Daily guard found today's article '{published_today.get('handle')}' but its saved body is missing the verified embed. "
                "Repairing that existing article before considering additional recipes."
            )
            repair_existing_article_video(blog_id, published_today["handle"], recipes)
            return
        published_today_count = sum(
            1 for article in articles.values()
            if article.get("isPublished")
            and article.get("handle") in {recipe["slug"] for recipe in recipes}
            and article.get("publishedAt")
            and datetime.datetime.fromisoformat(article["publishedAt"].replace("Z", "+00:00")).astimezone(CAIRO).date() == now.date()
        )
        if published_today_count >= max_publish:
            print(f"Daily idempotency guard: {published_today_count}/{max_publish} verified recipes already published today; no duplicates will be created.")
            return
        print(f"Daily multi-publish continuation: {published_today_count}/{max_publish} verified recipes already published today; continuing with remaining eligible recipes.")
    if published_today and args.one_time_test:
        print(f"ONE-TIME TEST MODE: allowing one additional eligible recipe despite today's existing article '{published_today.get('handle')}'. Normal daily guard remains enabled for all other runs.")
    start = day_number % len(recipes)

    target_slug = os.environ.get("TARGET_RECIPE_SLUG", "").strip()
    target_list = requested_target_recipes(recipes)
    if target_slug and target_list is not None:
        parser.error("Use TARGET_RECIPE_SLUG or TARGET_RECIPE_SLUGS, not both.")
    if target_slug:
        target_recipe = next((recipe for recipe in recipes if recipe["slug"] == target_slug), None)
        if target_recipe is None:
            raise RuntimeError(f"Requested target recipe '{target_slug}' is not in recipes.json.")
        target_recipes = [target_recipe]
    else:
        target_recipes = target_list

    eligible_source = target_recipes if target_recipes is not None else recipes
    eligible = [
        recipe for recipe in eligible_source
        if not (articles.get(recipe["slug"]) and articles[recipe["slug"]].get("isPublished"))
    ]
    print(f"Recipe library status: {len(eligible)} of {len(recipes)} recipes remain eligible.")

    if len(eligible) <= 3:
        print("WARNING: Recipe library is nearly exhausted. Add original recipes to recipes.json.")

    if not eligible:
        raise RuntimeError(
            "Recipe library exhausted. Add new original recipes to recipes.json."
        )

    # Normal scheduled runs may publish up to three distinct, fully verified recipes.
    # Explicit targeted repairs/tests remain single-item operations.
    published_count = sum(
        1 for article in articles.values()
        if article.get("isPublished")
        and article.get("handle") in {recipe["slug"] for recipe in recipes}
        and article.get("publishedAt")
        and datetime.datetime.fromisoformat(article["publishedAt"].replace("Z", "+00:00")).astimezone(CAIRO).date() == now.date()
    ) if not args.one_time_test else 0
    # A one-time targeted run processes only the requested recipe; normal runs rotate.
    candidates = target_recipes if target_recipes is not None else [
        recipes[(start + offset) % len(recipes)] for offset in range(len(recipes))
    ]
    if target_recipes is None:
        # Combine current Google search-trend terms, food-news coverage and public
        # TikTok Creative Center signals; rank only recipes already in the reviewed catalogue.
        from trend_engine import collect_all_food_trend_signals, rank_trending_recipes, score_recipe_trends
        from trend_recipe_builder import generate_trend_recipe_candidates
        trend_signals = collect_all_food_trend_signals()
        generated_candidates = generate_trend_recipe_candidates(
            trend_signals,
            existing_slugs=set(articles) | {item["slug"] for item in recipes},
            limit=3,
        )
        persisted_candidates = persist_generated_recipe_candidates(recipes, generated_candidates)
        if persisted_candidates:
            recipes.extend(persisted_candidates)
        if generated_candidates:
            print("TREND RECIPE GENERATION: " + json.dumps([
                {"title": item["title"], "slug": item["slug"],
                 "sources": item["trend_sources"], "evidence_count": item["trend_evidence_count"]}
                for item in generated_candidates
            ]))
            candidates = generated_candidates + candidates
        else:
            print("TREND RECIPE GENERATION: no supported trend matched a reviewed complete-recipe pattern; no speculative recipe was created.")
        if trend_signals:
            ranked_catalogue = rank_trending_recipes(candidates, trend_signals)
            # Generated candidates are already evidence-matched and stay ahead of
            # generic catalogue rotation; rank all matching candidates by their score.
            candidates = sorted(
                ranked_catalogue,
                key=lambda item: -score_recipe_trends(item, trend_signals),
            )
            scored = [(score_recipe_trends(item, trend_signals), item["title"]) for item in candidates]
            print(f"FOOD TREND DISCOVERY: signals={len(trend_signals)} | new_candidates={len(generated_candidates)} | ranked_candidates={json.dumps(scored[:10])}")
            if not any(score > 0 for score, _ in scored):
                print("No recipe matched fresh trend signals; catalogue rotation remains a last-resort fallback.")
        else:
            print("FOOD TREND DISCOVERY: no fresh signals; only existing reviewed catalogue recipes are eligible.")
    remaining_publish = max(0, max_publish - published_count)
    print(f"DAILY PUBLISH TARGET: up to {max_publish} distinct recipes; already published={published_count}; remaining={remaining_publish}. Every recipe must pass instruction, video, image and Shopify verification.")
    for recipe in candidates:
        if published_count >= max_publish:
            break
        existing = articles.get(recipe["slug"])

        if existing and existing.get("isPublished"):
            print(f"Skipping already-published recipe: {recipe['title']} ({recipe['slug']}).")
            continue

        print(f"Selected for {now.date()} Cairo time: {recipe['title']} ({recipe['slug']})")
        try:
            recipe = make_recipe_specific(recipe)
            recipe = add_recipe_category_tags(recipe)
        except ValueError as error:
            print(f"SKIPPING recipe with low-quality instructions: {error}")
            continue
        try:
            video = find_verified_recipe_video(recipe)
        except RuntimeError as error:
            print(f"SKIPPING recipe without a verified matching video: {recipe['title']}. {error}")
            continue
        print(f"Verified recipe video: {video['title']} | id={video['id']} | match={video['match_score']} | embeddable=yes")
        try:
            generated_image = youtube_thumbnail_for(recipe, video)
            generated_image = featured_image_for(recipe, generated_image)
            recipe["published_image_url"] = generated_image["url"]
        except RuntimeError as error:
            print(f"SKIPPING recipe without a verified dish-relevant photo: {recipe['title']}. {error}")
            continue
        if existing:
            mutation = """mutation UpdateRecipeArticle($id: ID!, $article: ArticleUpdateInput!) {
              articleUpdate(id: $id, article: $article) { article { id title handle isPublished body } userErrors { field message } }
            }"""
            result = graphql(mutation, {"id": existing["id"], "article": {
                "body": article_html(recipe, video, {
                    handle for handle, existing_article in articles.items()
                    if existing_article.get("isPublished")
                }),
                "summary": seo_metadata(recipe)["description"],
                "image": featured_image_for(recipe, generated_image),
                "isPublished": True,
            }}).get("articleUpdate") or {}
            if result.get("userErrors"):
                raise RuntimeError("Shopify rejected recipe/video update: " + json.dumps(result["userErrors"]))
            article = result.get("article")
            if not article or not article.get("isPublished"):
                raise RuntimeError("Shopify did not confirm recipe article publication.")
            verify_published_article(article, recipe, video)
        else:
            published_handles = {
                handle for handle, existing_article in articles.items()
                if existing_article.get("isPublished")
            }
            article = create_published(blog_id, recipe, video, generated_image, published_handles)
            verify_published_article(article, recipe, video)
        print(f"Published recipe with verified embedded video: {article['title']} | handle={article['handle']} | published={article['isPublished']} | iframe=verified | video={video['url']}")
        published_count += 1
        # Add the just-published article to the in-memory Shopify set so the next
        # recipe cannot reuse its image or related-link handle during this same run.
        articles[article["handle"]] = {
            **(article if isinstance(article, dict) else {}),
            "id": article.get("id"),
            "handle": article.get("handle"),
            "title": article.get("title"),
            "isPublished": True,
            "publishedAt": article.get("publishedAt") or now.isoformat(),
            "image": {"url": generated_image["url"]},
        }

    if published_count:
        print(f"DAILY PUBLISH COMPLETE: {published_count}/{max_publish} verified recipe(s) published. Unqualified candidates were skipped; no quality gate was bypassed.")
        return
    raise RuntimeError("No eligible recipe passed all quality gates. No unverified recipe was published.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
