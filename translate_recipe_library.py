"""Build a resumable translation cache for recipe text. No Shopify publishing occurs here."""
import json, os, urllib.parse, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ENDPOINT="https://translation.googleapis.com/language/translate/v2"
def tr(text,lang,key):
    if not text: return text
    data=urllib.parse.urlencode({"q":text,"source":"en","target":lang,"format":"text","key":key}).encode()
    req=urllib.request.Request(ENDPOINT,data=data)
    with urllib.request.urlopen(req,timeout=45) as r: return json.loads(r.read())["data"]["translations"][0]["translatedText"]
def main():
    key=os.getenv("GOOGLE_TRANSLATE_API_KEY","").strip()
    if not key: raise SystemExit("Set GOOGLE_TRANSLATE_API_KEY in repository Actions secrets.")
    recipes=json.loads((ROOT/"recipes.json").read_text())
    languages=json.loads((ROOT/"supported_languages.json").read_text())
    out=ROOT/"localized_recipes.json"
    cache=json.loads(out.read_text()) if out.exists() else {}
    for recipe in recipes:
        slug=recipe["slug"]; cache.setdefault(slug,{})
        for lang in languages:
            if lang in cache[slug]: continue
            row={"slug":slug,"language":lang}
            for field in ("title","description"):
                row[field]=tr(str(recipe.get(field,"")),lang,key)
            for field in ("ingredients","instructions"):
                row[field]=[tr(str(x),lang,key) for x in recipe.get(field,[])]
            for field in ("prep_minutes","cook_minutes","servings","tags"):
                if field in recipe: row[field]=recipe[field]
            cache[slug][lang]=row
            out.write_text(json.dumps(cache,ensure_ascii=False,indent=2)+"\n")
            print("cached",slug,lang)
    print("Translation cache generated. This script does not publish Shopify articles.")
if __name__=="__main__": main()
