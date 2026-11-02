"""Free, no-key trend discovery for SolePick's approved recipe catalogue.

Signals come from Google News RSS searches for current food/recipe coverage.
The module never generates ingredients or instructions; it only ranks recipes
that already exist in recipes.json. If RSS is unavailable, callers retain their
normal deterministic rotation.
"""
import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

STOP_WORDS = {
    "the", "and", "with", "for", "from", "that", "this", "your", "how", "make",
    "made", "easy", "best", "quick", "recipe", "recipes", "food", "foods",
    "viral", "trending", "trend", "tiktok", "new", "style", "ideas", "video",
    "cook", "cooking", "meal", "meals", "dinner", "lunch", "breakfast",
}
TREND_QUERIES = (
    '"viral recipe" OR "trending recipe" OR "food trend"',
    '"TikTok recipe" OR "viral food" OR "popular recipe"',
    '"high protein recipe" OR "one pot recipe" OR "easy dinner trend"',
)


def _tokens(value):
    return {
        token for token in re.findall(r"[a-z0-9]+", html.unescape(str(value or "")).lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def fetch_food_trend_signals(timeout=10, now=None):
    """Return fresh headline/body signals from public Google News RSS; no API key."""
    now = now or datetime.now(timezone.utc)
    signals = []
    seen = set()
    for query in TREND_QUERIES:
        params = urllib.parse.urlencode({
            "q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"
        })
        url = "https://news.google.com/rss/search?" + params
        request = urllib.request.Request(
            url, headers={"User-Agent": "SolePickTrendDiscovery/1.0 (+https://solepick.site)"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                root = ET.fromstring(response.read())
        except Exception as error:
            print(f"FOOD TREND RSS unavailable ({type(error).__name__}); continuing.")
            continue
        for item in root.findall(".//item"):
            title = html.unescape(item.findtext("title") or "").strip()
            description = html.unescape(item.findtext("description") or "").strip()
            text = re.sub(r"<[^>]+>", " ", title + " " + description)
            key = " ".join(_tokens(title))
            if not title or not key or key in seen:
                continue
            pub_date = item.findtext("pubDate")
            if pub_date:
                try:
                    published = parsedate_to_datetime(pub_date)
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    if published < now - timedelta(days=14):
                        continue
                except (TypeError, ValueError, OverflowError):
                    pass
            seen.add(key)
            signals.append(text[:1800])
    return signals


def score_recipe_trends(recipe, signals):
    """Rank recipes using search demand, food coverage and public social trend signals."""
    title_tokens = _tokens(recipe.get("title", ""))
    tag_tokens = _tokens(
        " ".join(recipe.get("tags", []) if isinstance(recipe.get("tags"), list) else [])
    )
    ingredient_tokens = _tokens(
        " ".join(recipe.get("ingredients", []) if isinstance(recipe.get("ingredients"), list) else [])
    )
    # Ingredient terms are valuable long-tail search intent (e.g. salmon + lemon),
    # even when a current trend headline does not repeat the full recipe title.
    recipe_tokens = title_tokens | tag_tokens | ingredient_tokens
    if not recipe_tokens:
        return 0.0
    weights = {
        "google_news": 1.0,
        "google_trends": 2.4,
        "tiktok_creative_center": 2.0,
        "youtube": 1.4,
        "pinterest": 1.2,
    }
    score = 0.0
    for signal in signals:
        signal_text = signal.get("text", "") if isinstance(signal, dict) else signal
        signal_tokens = _tokens(signal_text)
        overlap = recipe_tokens & signal_tokens
        title_overlap = title_tokens & signal_tokens
        ingredient_overlap = ingredient_tokens & signal_tokens
        if not overlap:
            continue
        source = signal.get("source", "google_news") if isinstance(signal, dict) else "google_news"
        weight = weights.get(source, 1.0)
        traffic = signal.get("traffic", "") if isinstance(signal, dict) else ""
        traffic_match = re.search(r"([0-9]+(?:\\.[0-9]+)?)\\s*([KMB]?)", str(traffic).upper())
        demand_boost = 1.0
        if traffic_match:
            amount = float(traffic_match.group(1))
            suffix = traffic_match.group(2)
            amount *= {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
            demand_boost += min(1.5, amount / 1_000_000)
        overlap_score = min(
            14,
            len(overlap) * 2 + len(title_overlap) * 2 + len(ingredient_overlap),
        )
        score += overlap_score * weight * demand_boost
    return round(score, 2)


def rank_trending_recipes(recipes, signals):
    """Stable trend ranking; original rotation order breaks ties and is the fallback."""
    indexed = list(enumerate(recipes))
    if not signals:
        return list(recipes)
    scored = [(score_recipe_trends(recipe, signals), index, recipe) for index, recipe in indexed]
    if not any(score > 0 for score, _, _ in scored):
        return list(recipes)
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [recipe for _, _, recipe in scored]



def _fetch_text(url, timeout=10):
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (compatible; SolePickTrendDiscovery/1.0)"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_google_search_trends(timeout=10, now=None):
    """Read Google's public Trending Searches RSS for current search-demand topics."""
    now = now or datetime.now(timezone.utc)
    signals = []
    for geo in ("US", "GB", "CA", "AU", "EG"):
        url = "https://trends.google.com/trending/rss?geo=" + geo
        try:
            root = ET.fromstring(_fetch_text(url, timeout))
        except Exception as error:
            print(f"GOOGLE SEARCH TRENDS unavailable for {geo} ({type(error).__name__}); continuing.")
            continue
        for item in root.findall(".//item"):
            title = html.unescape(item.findtext("title") or "").strip()
            traffic = item.findtext("{https://trends.google.com/trending/rss}approx_traffic") or ""
            if title:
                signals.append({"text": title, "source": "google_trends", "traffic": traffic, "geo": geo})
    print(f"GOOGLE SEARCH TRENDS: {len(signals)} current trending-search terms collected across 5 markets.")
    return signals


def fetch_tiktok_food_trends(timeout=10):
    """Best-effort public TikTok Creative Center signal; never required for publishing."""
    url = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en"
    signals = []
    try:
        page = _fetch_text(url, timeout)
        # Public Creative Center pages expose trend names in rendered/embedded page data.
        for match in re.findall(r'"hashtagName"\s*:\s*"([^"]+)"', page):
            name = html.unescape(match).strip().lstrip("#")
            if name:
                signals.append({"text": name.replace("_", " "), "source": "tiktok_creative_center"})
        for match in re.findall(r'"name"\s*:\s*"#?([A-Za-z][A-Za-z0-9_ ]{2,40})"', page):
            name = html.unescape(match).strip().lstrip("#")
            if name and any(word in name.lower() for word in ("food", "recipe", "cook", "meal", "bake", "pasta", "chicken", "protein")):
                signals.append({"text": name.replace("_", " "), "source": "tiktok_creative_center"})
    except Exception as error:
        print(f"TIKTOK CREATIVE CENTER unavailable ({type(error).__name__}); continuing with search/RSS signals.")
    unique = {}
    for item in signals:
        unique[item["text"].lower()] = item
    result = list(unique.values())
    print(f"TIKTOK CREATIVE CENTER: {len(result)} public trend signals collected.")
    return result


def collect_all_food_trend_signals():
    """Combine Google News coverage, Google trending searches and public TikTok trend names."""
    combined = []
    combined.extend({"text": value, "source": "google_news"} for value in fetch_food_trend_signals())
    combined.extend(fetch_google_search_trends())
    combined.extend(fetch_tiktok_food_trends())
    deduped = {}
    for signal in combined:
        key = " ".join(_tokens(signal.get("text", "")))
        if key:
            deduped.setdefault(key, signal)
    print("MULTI-SOURCE FOOD TRENDS: " + json.dumps({
        "google_news": sum(x["source"] == "google_news" for x in deduped.values()),
        "google_trends": sum(x["source"] == "google_trends" for x in deduped.values()),
        "tiktok_creative_center": sum(x["source"] == "tiktok_creative_center" for x in deduped.values()),
        "total": len(deduped),
    }))
    return list(deduped.values())
