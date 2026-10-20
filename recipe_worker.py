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
    if any(not (group & found_tokens) for group in wanted_formats):
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

def _check_video_candidate(recipe, video_id, title):
    """Validate a discovered YouTube candidate before it can be embedded."""
    video_id = str(video_id or "").strip()
    title = str(title or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or not title:
        return None
    if not _video_title_is_compatible(recipe, title):
        return None
    score = _video_title_score(recipe.get("title", ""), title)
    if score < 0.60:
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
    if live_score < 0.60:
        return None
    return {
        "id": video_id,
        "title": live_title,
        "url": "https://www.youtube.com/watch?v=" + video_id,
        "embed_url": "https://www.youtube-nocookie.com/embed/" + video_id,
        "match_score": round(live_score, 2),
    }


def find_verified_recipe_video(recipe):
    """Automatically discover and validate a matching, currently embeddable YouTube video."""
    # Re-check a configured video first, but do not make manual catalogue flags a blocker.
    configured = str(recipe.get("video_url") or "").strip()
    match = re.fullmatch(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})(?:[&?].*)?",
        configured
    )
    if match:
        candidate = _check_video_candidate(recipe, match.group(1), recipe.get("video_title", ""))
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
    queries = [
        f"ytsearch12:{title} recipe",
        f"ytsearch8:{title} cooking tutorial",
    ]
    seen = set()
    failures = 0
    for search_query in queries:
        options = {
            "quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": True, "noplaylist": True, "ignoreerrors": True,
            "socket_timeout": 12, "retries": 1,
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
            if video_id in seen:
                continue
            seen.add(video_id)
            if not _video_title_is_compatible(recipe, title_found):
                continue
            if _video_title_score(title, title_found) < 0.60:
                continue
            candidate = _check_video_candidate(recipe, video_id, title_found)
            if candidate:
                print(f"AUTO-SELECTED VIDEO: {candidate['title']} | match={candidate['match_score']} | live oEmbed check passed.")
                return candidate
            failures += 1
    raise RuntimeError(
        f"No currently embeddable, title-matched video found for '{title}' after checking "
        f"{len(seen)} search results ({failures} candidate checks failed). The workflow will retry tomorrow."
    )

def recipe_video_section_html(recipe, video):
    """Render a YouTube video with a custom timed-caption overlay backed by public VTT files."""
    video_id = str(video.get("id") or "")
    frame_id = "solepick-video-" + video_id
    vtt_base = "https://raw.githubusercontent.com/elsherbinyk10-netizen/SOLEPICK_RECIPES_AUTOMATION/main/captions/" + video_id + "/"
    caption_url = video["embed_url"] + "?enablejsapi=1&origin=https%3A%2F%2Fsolepick.site&playsinline=1&cc_load_policy=1&cc_lang_pref=en&hl=en"
    return (
        "<h2>Recipe Video</h2>"
        f"<p><a href=\"{esc(video['url'])}\" rel=\"noopener noreferrer\">Watch: {esc(video['title'])}</a></p>"
        f"<div class=\"solepick-recipe-video\" data-solepick-video-id=\"{esc(video_id)}\" data-vtt-base=\"{esc(vtt_base)}\" style=\"position:relative;width:100%;aspect-ratio:16/9;background:#111;\">"
        f"<iframe id=\"{esc(frame_id)}\" class=\"solepick-language-aware-video\" data-video-base=\"{esc(video['embed_url'])}\" src=\"{esc(caption_url)}\" title=\"{esc(recipe['title'])} recipe video\" "
        "loading=\"lazy\" allow=\"accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share\" "
        "referrerpolicy=\"strict-origin-when-cross-origin\" allowfullscreen style=\"position:absolute;inset:0;width:100%;height:100%;border:0;\"></iframe>"
        "<div class=\"solepick-caption-overlay\" aria-live=\"polite\" aria-atomic=\"true\" style=\"position:absolute;left:5%;right:5%;bottom:12%;z-index:5;text-align:center;pointer-events:none;color:#fff;font-size:clamp(15px,2.5vw,25px);font-weight:700;line-height:1.35;text-shadow:0 2px 4px #000,0 0 8px #000;padding:0 4px;\"></div>"
        "</div>"
        "<div class=\"solepick-caption-controls\" style=\"display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0 18px;\">"
        "<label style=\"display:flex;gap:8px;align-items:center;\">Captions "
        "<select class=\"solepick-caption-language\" aria-label=\"Caption language\" style=\"max-width:100%;padding:8px;border:1px solid #aaa;border-radius:6px;background:#fff;color:#222;\">"
        "<option value=\"off\">Off</option><option value=\"en\" selected>English</option>"
        "</select></label><span class=\"solepick-caption-status\" role=\"status\" aria-live=\"polite\" style=\"font-size:0.9em;\"></span>"
        "</div>"
        "<script>(function(){"
        "var script=document.currentScript;var block=script&&script.previousElementSibling;"
        "while(block&&!block.matches('.solepick-caption-controls'))block=block.previousElementSibling;"
        "if(!block)return;var wrap=block.previousElementSibling;if(!wrap||!wrap.matches('.solepick-recipe-video'))return;"
        "if(wrap.dataset.captionInit==='1')return;wrap.dataset.captionInit='1';"
        "var frame=wrap.querySelector('iframe'),overlay=wrap.querySelector('.solepick-caption-overlay'),select=block.querySelector('select'),status=block.querySelector('.solepick-caption-status');"
        "var cues=[],timer=null,last=-1,player=null,ready=false,active='en';"
        "function say(s){status.textContent=s||'';}function parseVtt(s){var out=[];var rows=s.replace(/\\r/g,'').split('\\n');"
        "for(var i=0;i<rows.length;i++){var m=rows[i].match(/(\\d{2}:\\d{2}:\\d{2}\\.\\d{3})\\s+-->\\s+(\\d{2}:\\d{2}:\\d{2}\\.\\d{3})/);"
        "if(!m)continue;function sec(t){var p=t.split(/[:.]/).map(Number);return p[0]*3600+p[1]*60+p[2]+p[3]/1000;}"
        "var text=[];for(i++;i<rows.length&&rows[i].trim();i++)if(!/^(WEBVTT|NOTE|\\d+)$/.test(rows[i].trim()))text.push(rows[i].replace(/<[^>]*>/g,''));"
        "if(text.length)out.push({start:sec(m[1]),end:sec(m[2]),text:text.join(' ').trim()});}return out;}"
        "function load(lang){active=lang;overlay.textContent='';cues=[];last=-1;if(timer){clearInterval(timer);timer=null;}"
        "if(lang==='off'){say('Captions off.');return;}var url=wrap.dataset.vttBase+encodeURIComponent(lang)+'.vtt';say('Loading '+lang.toUpperCase()+' captions…');"
        "fetch(url,{cache:'no-cache'}).then(function(r){if(!r.ok)throw Error('not found');return r.text();}).then(function(t){if(active!==lang)return;cues=parseVtt(t);"
        "if(!cues.length)throw Error('empty track');say(lang.toUpperCase()+' captions ready.');timer=setInterval(tick,200);tick();}).catch(function(){if(active!==lang)return;"
        "overlay.textContent='';try{if(player&&player.loadModule){player.loadModule('captions');player.setOption('captions','track',{languageCode:lang});player.setOption('captions','reload',true);say('Using YouTube captions if available. Use CC in the video player.');return;}}catch(e){}say('No separate caption file yet. Try CC in the YouTube player.');});}"
        "function tick(){if(!ready||!player||!cues.length)return;var now;try{now=player.getCurrentTime();}catch(e){return;}"
        "var idx=-1;for(var i=0;i<cues.length;i++){if(now>=cues[i].start&&now<cues[i].end){idx=i;break;}}if(idx!==last){last=idx;overlay.textContent=idx<0?'':cues[idx].text;}}"
        "function initPlayer(){if(!window.YT||!window.YT.Player||player)return;try{player=new YT.Player(frame,{events:{onReady:function(){ready=true;tick();},onStateChange:function(){tick();}}});}catch(e){say('Video caption sync is unavailable in this browser.');}}"
        "function loadApi(){if(window.YT&&window.YT.Player){initPlayer();return;}if(!document.querySelector('script[data-solepick-yt-api]')){var s=document.createElement('script');s.src='https://www.youtube.com/iframe_api';s.dataset.solepickYtApi='1';document.head.appendChild(s);}"
        "var prior=window.onYouTubeIframeAPIReady;window.onYouTubeIframeAPIReady=function(){if(typeof prior==='function')prior();initPlayer();};}"
        "select.addEventListener('change',function(){load(this.value);});"
        "var siteLang=document.querySelector('#SolePickTranslateSelect,#solepick-language-switcher,select[name=language],.language-selector select');"
        "if(siteLang){siteLang.addEventListener('change',function(){var l=String(this.value||'en').split('-')[0].toLowerCase();if(Array.from(select.options).some(function(o){return o.value===l;}))select.value=l;});}"
        "loadApi();load('en');"
        "})();</script>"
    )

def upsert_recipe_video_section(existing_body, recipe, video):
    """Insert or replace only the video section, preserving the article's other content."""
    section = recipe_video_section_html(recipe, video)
    pattern = r"<h2>Recipe Video</h2>.*?(?=<h2\b|$)"
    if re.search(pattern, existing_body, flags=re.IGNORECASE | re.DOTALL):
        return re.sub(pattern, lambda _match: section, existing_body, count=1, flags=re.IGNORECASE | re.DOTALL)
    match = re.search(r"<h2\b", existing_body, flags=re.IGNORECASE)
    if match:
        return existing_body[:match.start()] + section + existing_body[match.start():]
    return existing_body.rstrip() + "\n" + section


def generate_recipe_image(recipe):
    """Automatically find a unique, reachable public-domain/CC0 food photo on Wikimedia Commons."""
    catalogue = json.loads(RECIPES_PATH.read_text(encoding="utf-8"))
    used_urls = {
        str(item.get("image_url") or "").strip()
        for item in catalogue
        if item.get("slug") != recipe.get("slug") and item.get("image_url")
    }
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
    searches = [
        title + " real food photograph",
        " ".join(word for word in query_terms if word not in stop) + " plated recipe food photo",
        (main_food or title) + " cooked meal photograph",
    ]
    seen = set()
    reject_terms = {"seed", "seeds", "catalogue", "catalog", "flower", "flowers", "illustration", "poster", "advertisement", "advert", "logo", "clipart", "drawing", "painting", "poultry", "supplies"}
    for search_text in searches:
        params = urllib.parse.urlencode({
            "action": "query", "generator": "search", "gsrsearch": search_text,
            "gsrnamespace": 6, "gsrlimit": 15, "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": 1600, "format": "json",
        })
        request = urllib.request.Request(
            "https://commons.wikimedia.org/w/api.php?" + params,
            headers={"User-Agent": "SolePickRecipesBot/1.0 (recipe image selection; contact site owner)"}
        )
        # Wikimedia Commons can briefly rate-limit or return 5xx errors.
        # Retry transient failures with backoff before abandoning this search term.
        payload = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or 500 <= error.code < 600
                print(f"WIKIMEDIA PHOTO SEARCH attempt {attempt + 1}/3: HTTP {error.code}")
                if not retryable or attempt == 2:
                    break
                retry_after = error.headers.get("Retry-After", "")
                try:
                    delay = min(12, max(2, int(retry_after)))
                except (TypeError, ValueError):
                    delay = 2 ** (attempt + 1)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
                print(f"WIKIMEDIA PHOTO SEARCH attempt {attempt + 1}/3: {type(error).__name__}")
                if attempt == 2:
                    break
                time.sleep(2 ** (attempt + 1))
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
            if not image_url.startswith("https://") or image_url in used_urls or image_url in seen:
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

def featured_image_for(recipe, generated_image):
    """Use a configured public recipe image without generated-image APIs or upload permissions."""
    image = generated_image or {}
    url = (image.get("url") or recipe.get("image_url") or "").strip()
    if not url.startswith(("https://", "http://")):
        raise RuntimeError("No configured public featured image URL for " + recipe["title"])
    return {"url": url, "altText": image.get("altText") or recipe.get("image_alt") or ("Finished " + recipe["title"])}

def article_html(recipe, video=None):
    ingredients = "".join(f"<li>{esc(item)}</li>" for item in recipe["ingredients"])
    steps = "".join(f"<li>{esc(item)}</li>" for item in recipe["instructions"])
    video_html = recipe_video_section_html(recipe, video) if video else ""
    # Embed verified language-specific candidates when the cache exists. The client
    # script switches only to verified candidates and otherwise retains the base video.
    video_map = {}
    try:
        cache_path = Path(__file__).resolve().parent / "localized_recipe_videos.json"
        cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        for code, candidate in cache.get(recipe.get("slug", ""), {}).items():
            if candidate.get("verified") and candidate.get("embed_url", "").startswith("https://www.youtube-nocookie.com/embed/"):
                video_map[code] = candidate["embed_url"]
    except (OSError, ValueError, TypeError):
        video_map = {}
    video_data = esc(json.dumps(video_map, ensure_ascii=False, separators=(",", ":")))
    switcher = (
        f'<div class="solepick-video-language-map" data-recipe-slug="{esc(recipe.get("slug", ""))}" data-video-map="{video_data}" hidden></div>'
        '<script>(function(){function apply(){var maps=document.querySelectorAll(".solepick-video-language-map");var sel=document.querySelector("#SolePickTranslateSelect,#solepick-language-switcher,#vm-language-switcher,select[name=language],.language-selector select");var lang=sel&&sel.value?sel.value.split("-")[0]:"en";maps.forEach(function(m){var map={};try{map=JSON.parse(m.getAttribute("data-video-map")||"{}")}catch(e){}var frame=document.querySelector(".solepick-language-aware-video");if(frame){var base=frame.getAttribute("data-video-base")||frame.src;var target=map[lang]||base;try{var u=new URL(target);u.searchParams.set("cc_load_policy","1");u.searchParams.set("cc_lang_pref",lang);u.searchParams.set("hl",lang);frame.src=u.toString();frame.setAttribute("data-active-language",lang)}catch(e){}}})}document.addEventListener("change",function(e){if(e.target&&e.target.matches("#SolePickTranslateSelect,#solepick-language-switcher,#vm-language-switcher,select[name=language],.language-selector select"))apply()});document.addEventListener("DOMContentLoaded",apply);})();</script>'
    )
    return (
        f"<p>{esc(recipe['description'])}</p>"
        f"<p><strong>Prep:</strong> {recipe['prep_minutes']} minutes · "
        f"<strong>Cook:</strong> {recipe['cook_minutes']} minutes · "
        f"<strong>Serves:</strong> {recipe['servings']}</p>"
        f"{video_html}{switcher}"
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
            recipe = make_recipe_specific(recipe)
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
            generated_image = generate_recipe_image(recipe)
        except RuntimeError as error:
            print(f"SKIPPING recipe with unavailable/invalid image: {recipe['title']}. {error}")
            continue
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
