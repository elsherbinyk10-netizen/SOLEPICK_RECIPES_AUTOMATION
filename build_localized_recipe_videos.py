"""Find YouTube video candidates without paid translation APIs.

Candidates are never approved automatically. A live oEmbed response and title similarity
do not prove that a video is the exact recipe or spoken in the requested language.
A human must set reviewed=true and verified=true before production selectors use it.
"""
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def tokens(value):
    return {word for word in re.findall(r"[\w]+", str(value).casefold()) if len(word) > 2}


def live(video_id):
    url = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({
        "url": "https://www.youtube.com/watch?v=" + video_id, "format": "json"
    })
    request = urllib.request.Request(url, headers={"User-Agent": "SolePickRecipeVideoChecker/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None


def main():
    import yt_dlp

    recipes = json.loads((ROOT / "recipes.json").read_text(encoding="utf-8"))
    languages = json.loads((ROOT / "supported_languages.json").read_text(encoding="utf-8"))
    output = ROOT / "localized_recipe_videos.json"
    results = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}

    # Match the 12 non-English languages exposed in the visitor-facing video selector.
    target_languages = {code: languages[code] for code in
                        ("ar", "es", "fr", "de", "it", "pt", "ja", "ko", "tr", "ru", "zh-CN", "zh-TW")
                        if code in languages}
    for recipe in recipes:
        slug, title = recipe.get("slug"), str(recipe.get("title", "")).strip()
        if not slug or not title:
            continue
        results.setdefault(slug, {})
        for code, language_name in target_languages.items():
            old = results[slug].get(code)
            if isinstance(old, dict) and old.get("reviewed") is True and old.get("verified") is True:
                continue
            chosen, seen = None, set()
            for query in (f"ytsearch2:{title} recipe {language_name}",):
                options = {"quiet": True, "no_warnings": True, "skip_download": True,
                           "extract_flat": True, "noplaylist": True, "ignoreerrors": True,
                           "socket_timeout": 8, "retries": 0, "extractor_retries": 0}
                try:
                    with yt_dlp.YoutubeDL(options) as ydl:
                        found = ydl.extract_info(query, download=False) or {}
                except Exception as exc:
                    print("Search skipped", slug, code, type(exc).__name__)
                    continue
                for item in found.get("entries") or []:
                    if not isinstance(item, dict):
                        continue
                    video_id, video_title = str(item.get("id") or ""), str(item.get("title") or "")
                    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or video_id in seen:
                        continue
                    seen.add(video_id)
                    overlap = len(tokens(title) & tokens(video_title)) / max(1, len(tokens(title)))
                    if overlap < 0.35:
                        continue
                    info = live(video_id)
                    if not info:
                        continue
                    chosen = {
                        "video_id": video_id,
                        "url": "https://www.youtube.com/watch?v=" + video_id,
                        "embed_url": "https://www.youtube-nocookie.com/embed/" + video_id,
                        "video_title": info.get("title", video_title),
                        "candidate_found": True, "verified": False, "reviewed": False,
                        "title_overlap": round(overlap, 2), "language": code,
                        "language_name": language_name, "recipe_slug": slug,
                        "review_note": "Manually confirm exact recipe and spoken language before approval."
                    }
                    break
                if chosen:
                    break
            if chosen:
                results[slug][code] = chosen
            elif not (isinstance(old, dict) and old.get("reviewed") is True):
                results[slug][code] = {
                    "candidate_found": False, "verified": False, "reviewed": False,
                    "language": code, "language_name": language_name, "recipe_slug": slug,
                    "reason": "No candidate found; English remains the safe fallback."
                }
            output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print("candidate", slug, code, "found" if chosen else "not found")
    print("Candidate catalogue saved; nothing was published. Candidates require human review.")


if __name__ == "__main__":
    main()
