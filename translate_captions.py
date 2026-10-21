#!/usr/bin/env python3
"""Translate existing timed WebVTT captions with locally installed Argos Translate models.

No paid API is used. This tool never invents source captions: it requires a validated
English VTT, preserves cue timing, and records languages for which no installed
translation model exists as unavailable rather than pretending they succeeded.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

TIMING = re.compile(r"^(\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3})(.*)$")

def parse_vtt(path: Path):
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.lstrip().startswith("WEBVTT"):
        raise ValueError(f"{path} is not a WebVTT file")
    blocks = re.split(r"\n\s*\n", raw.strip())
    cues = []
    for block in blocks:
        lines = block.splitlines()
        ti = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if ti is None:
            continue
        match = TIMING.match(lines[ti].strip())
        if not match:
            raise ValueError(f"Invalid WebVTT cue timing: {lines[ti]}")
        text = "\n".join(lines[ti + 1:]).strip()
        if text:
            cues.append((lines[:ti], match.group(1) + match.group(2), text))
    if not cues:
        raise ValueError(f"No timed caption cues found in {path}")
    return cues

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="Path to validated English .vtt")
    ap.add_argument("--out-dir", required=True, help="Output directory for translated .vtt files")
    ap.add_argument("--languages", required=True, help="Comma-separated target language codes, e.g. es,fr,de")
    ap.add_argument("--report", default="caption-translation-report.json")
    ap.add_argument("--install-models", action="store_true", help="Download available open-source Argos English-to-target models before translating.")
    args = ap.parse_args()
    source = Path(args.source)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cues = parse_vtt(source)
    try:
        import argostranslate.translate as translate
    except ImportError as exc:
        raise SystemExit("Install the open-source argostranslate package first.") from exc
    if args.install_models:
        try:
            import argostranslate.package as package
            print("Refreshing Argos open-source package index…")
            package.update_package_index()
            available = package.get_available_packages()
            for raw_code in dict.fromkeys(x.strip().lower() for x in args.languages.split(",") if x.strip()):
                code = raw_code.split("-")[0]
                if code == "en":
                    continue
                installed_codes = {lang.code for lang in translate.get_installed_languages()}
                if code in installed_codes and translate.get_installed_languages():
                    source_lang = next((lang for lang in translate.get_installed_languages() if lang.code == "en"), None)
                    target_lang = next((lang for lang in translate.get_installed_languages() if lang.code == code), None)
                    if source_lang and source_lang.get_translation(target_lang):
                        continue
                match = next((p for p in available if p.from_code == "en" and p.to_code == code), None)
                if match is None:
                    print(f"No direct Argos English-to-{code} model is published; marking unavailable.")
                    continue
                try:
                    print(f"Installing open-source English-to-{code} model…")
                    package.install_from_path(match.download())
                except Exception as exc:
                    print(f"Could not install model {code}: {type(exc).__name__}: {exc}")
        except Exception as exc:
            print(f"Argos package index/model installation problem: {type(exc).__name__}: {exc}")
    installed = translate.get_installed_languages()
    by_code = {lang.code: lang for lang in installed}
    en = by_code.get("en")
    if en is None:
        raise SystemExit("No English Argos language model is installed; no translations were generated.")
    report = {"source": str(source), "source_cues": len(cues), "results": {}}
    for raw_code in dict.fromkeys(x.strip().lower() for x in args.languages.split(",") if x.strip()):
        code = raw_code.split("-")[0]
        if code == "en":
            target_path = out / "en.vtt"
            target_path.write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")
            report["results"][raw_code] = {"status": "ok", "file": str(target_path), "cues": len(cues), "method": "source-copy"}
            continue
        target_path = out / f"{code}.vtt"
        if target_path.is_file():
            try:
                existing_cues = parse_vtt(target_path)
                if existing_cues:
                    report["results"][raw_code] = {"status": "ok", "file": str(target_path), "cues": len(existing_cues), "method": "existing-youtube-track"}
                    continue
            except Exception:
                target_path.unlink(missing_ok=True)
        target_lang = by_code.get(code)
        translation = en.get_translation(target_lang) if target_lang else None
        if translation is None:
            report["results"][raw_code] = {"status": "unavailable", "reason": "No installed English-to-target Argos model"}
            continue
        lines = ["WEBVTT", ""]
        for index, (prefix, timing, phrase) in enumerate(cues, 1):
            # Keep cue IDs/settings and exact timing; translate only visible cue text.
            lines.extend([str(index), timing, translation.translate(phrase), ""])
        target_path = out / f"{code}.vtt"
        target_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Validate the output and cue count before reporting success.
        translated_cues = parse_vtt(target_path)
        if len(translated_cues) != len(cues):
            target_path.unlink(missing_ok=True)
            report["results"][raw_code] = {"status": "failed", "reason": "Cue-count validation failed"}
            continue
        report["results"][raw_code] = {"status": "ok", "file": str(target_path), "cues": len(cues), "method": "argos-local"}
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = sum(item["status"] == "ok" for item in report["results"].values())
    missing = len(report["results"]) - ok
    print(f"Caption translations: {ok} successful; {missing} unavailable/failed. Report: {report_path}")
    if missing:
        print("Not all languages were generated. Install the corresponding open-source language models and rerun.")

if __name__ == "__main__":
    main()
