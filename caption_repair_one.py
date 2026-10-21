#!/usr/bin/env python3
"""Repair captions for one recipe video from permitted subtitle/media sources.

Never fabricates a transcript. A successful run requires validated timed English
captions, then translates only languages supported by installed Argos models.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTIONS = ROOT / "captions"
DEFAULT_LANGUAGES = "en,ar,es,fr,de,it,pt,ja,ko,ru,tr,nl,pl,id,vi,th,uk,hi,zh"

def valid_vtt(path):
    try:
        from translate_captions import parse_vtt
        cues = parse_vtt(path)
        return len(cues) > 0
    except Exception:
        return False

def run(cmd, timeout):
    print("+", " ".join(str(x) for x in cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=timeout)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", required=True, help="11-character YouTube video ID")
    ap.add_argument("--media-url", default="", help="Optional permitted direct media URL; must be accessible without login")
    ap.add_argument("--languages", default=DEFAULT_LANGUAGES, help="Comma-separated selector language codes")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video_id):
        ap.error("--video-id must be exactly 11 valid YouTube ID characters")
    if args.media_url and not args.media_url.startswith("https://"):
        ap.error("--media-url must use HTTPS")

    vid = args.video_id
    directory = CAPTIONS / vid
    directory.mkdir(parents=True, exist_ok=True)
    english = directory / "en.vtt"
    report = {"video_id": vid, "source": "existing repository track", "english": "missing", "translations": {}, "notes": []}

    if english.exists() and not valid_vtt(english):
        english.unlink()
        report["notes"].append("Removed an invalid English VTT before regeneration.")

    # First try the video's existing public subtitle tracks without downloading media.
    from caption_backfill import fetch_native_tracks
    native = fetch_native_tracks(vid, directory)
    report["native_tracks"] = native
    if english.exists() and valid_vtt(english):
        report["source"] = "existing or native English subtitle track"
    else:
        generator = [sys.executable, str(ROOT / "generate_captions.py")]
        if args.media_url:
            generator += ["--video-url", args.media_url, "--video-id", vid]
            report["source"] = "user-supplied permitted direct media URL"
        else:
            generator += ["--video-url", "https://www.youtube.com/watch?v=" + vid]
            report["source"] = "public YouTube subtitle track or accessible media"
        result = run(generator, timeout=900)
        report["generation_log"] = result.stdout[-5000:]
        if result.returncode != 0 or not english.exists() or not valid_vtt(english):
            report["english"] = "blocked_or_failed"
            report["notes"].append("No valid timed English captions were produced. No transcript was invented; provide a permitted direct media URL if YouTube blocks retrieval.")
            out = ROOT / ("caption-repair-report-" + vid + ".json")
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2

    report["english"] = "validated"
    report["english_cues"] = len(__import__("translate_captions").parse_vtt(english))
    wanted = ",".join(dict.fromkeys(x.strip().lower() for x in args.languages.split(",") if x.strip()))
    trans = run([sys.executable, str(ROOT / "translate_captions.py"),
                 "--source", str(english), "--out-dir", str(directory),
                 "--languages", wanted, "--install-models",
                 "--report", str(directory / "translation-report.json")], timeout=2400)
    report["translation_log"] = trans.stdout[-6000:]
    try:
        translation_report = json.loads((directory / "translation-report.json").read_text(encoding="utf-8"))
        report["translations"] = translation_report.get("results", {})
    except Exception as exc:
        report["notes"].append("Translation report could not be read: " + str(exc))
    report["validated_files"] = {}
    for code in wanted.split(","):
        # zh-CN / zh-TW are not selector options here; zh maps to zh.vtt.
        target = directory / (code + ".vtt")
        if target.exists() and valid_vtt(target):
            report["validated_files"][code] = {"file": str(target.relative_to(ROOT)), "cues": len(__import__("translate_captions").parse_vtt(target))}
        elif code != "en":
            report["validated_files"][code] = {"status": "unavailable_or_invalid"}
    out = ROOT / ("caption-repair-report-" + vid + ".json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = [k for k, v in report["validated_files"].items() if "file" in v]
    print("Validated caption files:", ", ".join(ok) if ok else "none")
    print("Report:", out)
    return 0 if "en" in ok else 2

if __name__ == "__main__":
    raise SystemExit(main())
