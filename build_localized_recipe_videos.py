"""Build language-specific video candidates for every recipe-language pair.

Requires localized_recipes.json (created by translate_recipe_library.py) and yt-dlp.
Only records candidate videos after a live YouTube oEmbed check and title relevance
check. It does not rewrite/publish Shopify posts; candidates must be reviewed before
being connected to production article embeds.
"""
import json, re, urllib.parse, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def tokens(s):
    return {x for x in re.findall(r"[\w]+",str(s).casefold()) if len(x)>2}
def live(video_id):
    url="https://www.youtube.com/oembed?"+urllib.parse.urlencode({"url":"https://www.youtube.com/watch?v="+video_id,"format":"json"})
    req=urllib.request.Request(url,headers={"User-Agent":"SolePickRecipeVideoChecker/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read().decode())
    except Exception: return None
def main():
    import yt_dlp
    localized=json.loads((ROOT/"localized_recipes.json").read_text(encoding="utf-8"))
    output=ROOT/"localized_recipe_videos.json"
    results=json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}
    for slug,languages in localized.items():
        results.setdefault(slug,{})
        for code,recipe in languages.items():
            if code in results[slug] and results[slug][code].get("verified"): continue
            title=recipe.get("title","").strip()
            if not title: continue
            chosen=None; seen=set()
            for query in (f"ytsearch8:{title} recipe {code}",f"ytsearch8:{title} cooking tutorial"):
                opts={"quiet":True,"no_warnings":True,"skip_download":True,"extract_flat":True,"noplaylist":True,"ignoreerrors":True,"socket_timeout":15,"retries":1}
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl: found=ydl.extract_info(query,download=False) or {}
                except Exception as e:
                    print("Search skipped",slug,code,type(e).__name__); continue
                for item in found.get("entries") or []:
                    if not isinstance(item,dict): continue
                    vid=str(item.get("id") or "")
                    vtitle=str(item.get("title") or "")
                    if not re.fullmatch(r"[A-Za-z0-9_-]{11}",vid) or vid in seen: continue
                    seen.add(vid)
                    overlap=len(tokens(title)&tokens(vtitle))/max(1,len(tokens(title)))
                    if overlap < 0.35: continue
                    info=live(vid)
                    if not info: continue
                    chosen={"video_id":vid,"url":"https://www.youtube.com/watch?v="+vid,"embed_url":"https://www.youtube-nocookie.com/embed/"+vid,"video_title":info.get("title",vtitle),"verified":True,"title_overlap":round(overlap,2),"language":code}
                    break
                if chosen: break
            results[slug][code]=chosen or {"verified":False,"language":code,"reason":"No relevant live embeddable candidate found"}
            output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            print("video candidate",slug,code,"verified" if chosen else "not found")
    print("Saved candidates; these have not been published to Shopify.")
if __name__=="__main__": main()
