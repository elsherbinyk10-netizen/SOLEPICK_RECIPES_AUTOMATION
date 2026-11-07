#!/usr/bin/env python3
"""Backfill real captions for published Shopify recipe videos, then translate available languages."""
import json
import os
import re
import subprocess
import sys
import urllib.error
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
CAPTIONS = ROOT / "captions"
LANGUAGES = "en,ar,es,fr,de,it,pt,ja,ko,tr,ru,zh-CN,zh-TW,af,sq,am,hy,az,eu,be,bn,bs,bg,my,ca,ceb,ny,co,hr,cs,da,nl,eo,et,tl,fi,fy,gl,ka,el,gu,ht,ha,haw,he,hi,hmn,hu,is,ig,id,ga,jv,kn,kk,km,rw,ky,lo,la,lv,lt,lb,mk,mg,ms,ml,mt,mi,mr,mn,ne,no,or,ps,fa,pl,pa,ro,sm,gd,sr,st,sn,sd,si,sk,sl,so,su,sw,sv,tg,ta,tt,te,th,ti,uk,ur,uz,vi,cy,xh,yi,yo,zu,as,br,dv,ee,fo,ilo,kok,mai,mni,om,sa,sat,ak,bho,doi,gom,kri,lus,mwr,nso"

def get_token(domain, client_id, client_secret):
    import urllib.request
    import urllib.parse
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
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = ""
        try:
            payload = json.loads(error.read().decode())
            detail = str(payload.get("error") or payload.get("error_description") or "")
        except Exception:
            pass
        suffix = f" ({detail})" if detail else ""
        raise RuntimeError(
            f"Shopify caption-backfill token exchange failed with HTTP {error.code}{suffix}. "
            "The main publisher's store domain and app credentials should be identical."
        ) from None
    token = data.get("access_token")
    if not token:
        raise RuntimeError("Shopify credential exchange returned no access_token.")
    return token

def resolve_recipe_blog_id(domain, token, api_version):
    """Resolve the same dedicated Recipes blog used by recipe_worker.py; never guess an ID."""
    import urllib.request
    query = """query SolePickCaptionBlogs {
      blogs(first: 50) { nodes { id title handle } }
    }"""
    req = urllib.request.Request(
        f"https://{domain}/admin/api/{api_version}/graphql.json",
        data=json.dumps({"query": query, "variables": {}}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.loads(response.read().decode())
    if data.get("errors"):
        raise RuntimeError("Shopify blog discovery failed: " + json.dumps(data["errors"]))
    blogs = (data.get("data", {}).get("blogs") or {}).get("nodes") or []
    recipes_blog = next((blog for blog in blogs if blog.get("handle") == "recipes" and blog.get("id")), None)
    if not recipes_blog:
        available = ", ".join(
            f'{blog.get("title", "(untitled)")} [{blog.get("handle", "no handle")}]'
            for blog in blogs
        ) or "none returned"
        raise RuntimeError(
            "The dedicated SolePick blog with handle 'recipes' was not found. "
            f"Available blogs: {available}. The backfill will not scan another blog."
        )
    print(
        "SHOPIFY BLOG VERIFIED: "
        + recipes_blog.get("title", "Recipes")
        + " | handle=recipes | id="
        + recipes_blog["id"]
    )
    return recipes_blog["id"]


def shopify_articles():
    import urllib.request
    domain = os.environ["SHOPIFY_STORE_DOMAIN"].replace("https://", "").replace("http://", "").strip("/")
    token = get_token(domain, os.environ["SHOPIFY_CLIENT_ID"], os.environ["SHOPIFY_CLIENT_SECRET"])
    api_version = os.environ.get("SHOPIFY_API_VERSION", "2026-07").strip()
    blog_id = resolve_recipe_blog_id(domain, token, api_version)
    query = """query RecipeCaptionBackfill($id: ID!, $after: String) {
      blog(id: $id) { articles(first: 100, after: $after) {
        nodes { title handle body publishedAt }
        pageInfo { hasNextPage endCursor }
      } }
    }"""
    articles, after = [], None
    while True:
        payload = json.dumps({"query": query, "variables": {"id": blog_id, "after": after}}).encode()
        req = urllib.request.Request(f"https://{domain}/admin/api/{api_version}/graphql.json", data=payload,
            headers={"Content-Type":"application/json","X-Shopify-Access-Token":token}, method="POST")
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.loads(response.read().decode())
        if data.get("errors"):
            raise RuntimeError(json.dumps(data["errors"]))
        blog = data.get("data", {}).get("blog")
        if not blog:
            raise RuntimeError("The verified Recipes blog disappeared during article retrieval; stopping safely.")
        conn = blog["articles"]
        # The Admin API can return drafts in the blog connection; only process live articles.
        articles.extend(article for article in conn["nodes"] if article.get("publishedAt"))
        if not conn["pageInfo"]["hasNextPage"]:
            return articles
        after = conn["pageInfo"]["endCursor"]

def video_ids(html):
    ids = set()
    for src in re.findall(r'''(?:src|href)\s*=\s*["']([^"']+)["']''', html or "", flags=re.I):
        try:
            u = urlparse(src.replace("&amp;", "&"))
            host = u.netloc.lower()
            if "youtube.com" in host and "/embed/" in u.path:
                m = re.search(r"/embed/([A-Za-z0-9_-]{11})", u.path)
                if m: ids.add(m.group(1))
            elif host.endswith("youtu.be"):
                m = re.match(r"/([A-Za-z0-9_-]{11})", u.path)
                if m: ids.add(m.group(1))
            elif "youtube.com" in host and u.path == "/watch":
                v = parse_qs(u.query).get("v", [""])[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", v): ids.add(v)
        except Exception:
            continue
    # Also catch iframe URLs embedded with escaped slashes.
    for vid in re.findall(r"(?:youtube(?:-nocookie)?\.com/embed/|youtu\.be/)([A-Za-z0-9_-]{11})", html or ""):
        ids.add(vid)
    return sorted(ids)

def fetch_native_tracks(vid, directory):
    """Prefer genuine YouTube subtitle tracks in every available language."""
    import shutil
    import tempfile
    from generate_captions import clean_youtube_vtt
    temp = Path(tempfile.mkdtemp(prefix="solepick-subs-" + vid + "-"))
    template = str(temp / "source.%(language)s.%(ext)s")
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-progress",
           "--skip-download", "--write-subs", "--write-auto-subs",
           "--sub-langs", "all", "--sub-format", "vtt", "--output", template,
           "https://www.youtube.com/watch?v=" + vid]
    try:
        result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        count = 0
        for source in sorted(temp.glob("source.*.vtt")):
            parts = source.name.split(".")
            if len(parts) < 3:
                continue
            raw_code = parts[1].lower().replace("_", "-")
            code = raw_code.split("-")[0]
            if not re.fullmatch(r"[a-z]{2,3}", code):
                continue
            target = directory / (code + ".vtt")
            if target.exists():
                continue
            try:
                cues = clean_youtube_vtt(source, target)
                if cues:
                    count += 1
                    print("Saved existing YouTube caption track " + raw_code + " -> " + str(target))
            except Exception as exc:
                print("Could not validate " + source.name + ": " + type(exc).__name__ + ": " + str(exc))
        return {"tracks_saved": count, "returncode": result.returncode, "log": result.stdout[-1500:]}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return {"tracks_saved": 0, "error": type(exc).__name__ + ": " + str(exc)}
    finally:
        shutil.rmtree(temp, ignore_errors=True)

def main():
    articles = shopify_articles()
    video_map = {}
    for article in articles:
        for vid in video_ids(article.get("body", "")):
            video_map.setdefault(vid, []).append(article.get("handle", "unknown"))
    print(f"Found {len(video_map)} unique YouTube videos across {len(articles)} Shopify recipe articles.")
    if not video_map:
        raise RuntimeError("No YouTube video IDs were found in published recipe article HTML; no files were changed.")
    report = {"articles_checked": len(articles), "videos_found": len(video_map), "videos": {}, "languages": LANGUAGES.split(",")}
    models_install_attempted = False
    for vid, handles in sorted(video_map.items()):
        directory = CAPTIONS / vid
        directory.mkdir(parents=True, exist_ok=True)
        english = directory / "en.vtt"
        item = {"handles": handles, "english_status": "existing" if english.is_file() else "missing", "translations": "not_started"}
        item["native_caption_tracks"] = fetch_native_tracks(vid, directory)
        if not english.is_file():
            cmd = [sys.executable, str(ROOT / "generate_captions.py"), "--video-url", f"https://www.youtube.com/watch?v={vid}"]
            result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=360)
            item["caption_generation_log"] = result.stdout[-2500:]
            if result.returncode == 0 and english.is_file():
                item["english_status"] = "generated"
            else:
                item["english_status"] = "blocked_or_failed"
                report["videos"][vid] = item
                print(f"SKIP {vid}: could not generate genuine English captions; will not fabricate.")
                continue
        trans_cmd = [sys.executable, str(ROOT / "translate_captions.py"), "--source", str(english),
                     "--out-dir", str(directory), "--languages", LANGUAGES,
                     "--report", str(directory / "translation-report.json")]
        # Model downloads persist for this runner job. Attempt installation once, not once per video.
        if not models_install_attempted:
            trans_cmd.append("--install-models")
            models_install_attempted = True
        result = subprocess.run(trans_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200)
        item["translation_log"] = result.stdout[-3000:]
        item["translations"] = "processed" if result.returncode == 0 else "failed"
        report["videos"][vid] = item
        print(f"Processed {vid} ({', '.join(handles)}): English={item['english_status']}; translation step={item['translations']}")
    report_path = ROOT / "caption-backfill-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Report written: {report_path}")
    print("A language is usable only when its validated captions/<video-id>/<language>.vtt file exists.")
if __name__ == "__main__":
    main()
