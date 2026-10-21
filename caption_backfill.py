#!/usr/bin/env python3
"""Backfill real captions for published Shopify recipe videos, then translate available languages."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
CAPTIONS = ROOT / "captions"
LANGUAGES = "en,ar,es,fr,de,it,pt,ja,ko,tr,ru,zh-CN,zh-TW,af,sq,am,hy,az,eu,be,bn,bs,bg,my,ca,ceb,ny,co,hr,cs,da,nl,eo,et,tl,fi,fy,gl,ka,el,gu,ht,ha,haw,he,hi,hmn,hu,is,ig,id,ga,jv,kn,kk,km,rw,ky,lo,la,lv,lt,lb,mk,mg,ms,ml,mt,mi,mr,mn,ne,no,or,ps,fa,pl,pa,ro,sm,gd,sr,st,sn,sd,si,sk,sl,so,su,sw,sv,tg,ta,tt,te,th,ti,uk,ur,uz,vi,cy,xh,yi,yo,zu,as,br,dv,ee,fo,ilo,kok,mai,mni,om,sa,sat,ak,bho,doi,gom,kri,lus,mwr,nso"

def get_token(domain, client_id, client_secret):
    import urllib.request
    req = urllib.request.Request(
        f"https://{domain}/admin/oauth/access_token",
        data=json.dumps({"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode())["access_token"]

def shopify_articles():
    import urllib.request
    domain = os.environ["SHOPIFY_STORE_DOMAIN"].replace("https://", "").replace("http://", "").strip("/")
    token = get_token(domain, os.environ["SHOPIFY_CLIENT_ID"], os.environ["SHOPIFY_CLIENT_SECRET"])
    blog_id = os.environ["SHOPIFY_BLOG_ID"]
    query = """query RecipeCaptionBackfill($id: ID!, $after: String) {
      blog(id: $id) { articles(first: 100, after: $after) {
        nodes { title handle body publishedAt }
        pageInfo { hasNextPage endCursor }
      } }
    }"""
    articles, after = [], None
    while True:
        payload = json.dumps({"query": query, "variables": {"id": blog_id, "after": after}}).encode()
        req = urllib.request.Request(f"https://{domain}/admin/api/2026-07/graphql.json", data=payload,
            headers={"Content-Type":"application/json","X-Shopify-Access-Token":token}, method="POST")
        with urllib.request.urlopen(req, timeout=45) as response:
            data = json.loads(response.read().decode())
        if data.get("errors"):
            raise RuntimeError(json.dumps(data["errors"]))
        blog = data.get("data", {}).get("blog")
        if not blog:
            raise RuntimeError("Shopify blog not found; verify SHOPIFY_BLOG_ID.")
        conn = blog["articles"]
        articles.extend(conn["nodes"])
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
    for vid, handles in sorted(video_map.items()):
        directory = CAPTIONS / vid
        english = directory / "en.vtt"
        item = {"handles": handles, "english_status": "existing" if english.is_file() else "missing", "translations": "not_started"}
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
                     "--out-dir", str(directory), "--languages", LANGUAGES, "--install-models",
                     "--report", str(directory / "translation-report.json")]
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
