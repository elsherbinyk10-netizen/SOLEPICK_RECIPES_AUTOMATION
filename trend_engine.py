"""Free, no-key trend discovery for SolePick's approved recipe catalogue.

Signals come from Google News RSS searches for current food/recipe coverage.
The module never generates ingredients or instructions; it only ranks recipes
that already exist in recipes.json. If RSS is unavailable, callers retain their
normal deterministic rotation.
"""
import html
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
    """Score catalogue recipes by meaningful ingredient/dish overlap with fresh signals."""
    title_tokens = _tokens(recipe.get("title", ""))
    recipe_tokens = _tokens(
        " ".join(recipe.get("tags", []) if isinstance(recipe.get("tags"), list) else [])
    )
    recipe_tokens |= title_tokens
    if not recipe_tokens:
        return 0
    score = 0
    for signal in signals:
        signal_tokens = _tokens(signal)
        overlap = recipe_tokens & signal_tokens
        title_overlap = title_tokens & signal_tokens
        if len(overlap) >= 2:
            score += min(12, len(overlap) * 2 + len(title_overlap) * 2)
        elif len(overlap) == 1 and title_overlap:
            score += 2
    return score


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
