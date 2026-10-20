#!/usr/bin/env python3
"""Generate real English WebVTT captions from a YouTube video without an external API."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTIONS = ROOT / "captions"


def video_id(value):
    value = value.strip()
    patterns = [
        r"(?:youtube\.com/watch\?(?:[^#]*&)?v=|youtu\.be/|youtube-nocookie\.com/embed/)([A-Za-z0-9_-]{11})",
        r"^([A-Za-z0-9_-]{11})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    raise ValueError("Provide a valid YouTube URL or 11-character video ID.")


def stamp(seconds):
    ms = max(0, round(float(seconds) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-url", required=True)
    parser.add_argument("--model", default="small.en", choices=["tiny.en", "base.en", "small.en", "medium.en"])
    args = parser.parse_args()
    vid = video_id(args.video_url)
    out_dir = CAPTIONS / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"CAPTION JOB: video={vid}; model={args.model}")
    print("Downloading audio with yt-dlp (no API key).")
    subprocess.run([
        sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-progress",
        "-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a",
        "--output", str(out_dir / "audio.%(ext)s"),
        f"https://www.youtube.com/watch?v={vid}",
    ], check=True)
    audio = next((p for p in out_dir.glob("audio.*") if p.suffix.lower() in {".m4a", ".mp3", ".webm", ".opus", ".wav"}), None)
    if audio is None:
        raise RuntimeError("yt-dlp finished but no audio file was found.")
    from faster_whisper import WhisperModel
    print(f"Transcribing locally with faster-whisper {args.model}; this can take several minutes.")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio), beam_size=5, vad_filter=True)
    lines = ["WEBVTT", ""]
    count = 0
    for segment in segments:
        text = re.sub(r"\s+", " ", str(segment.text or "")).strip()
        if not text:
            continue
        start = max(0.0, float(segment.start))
        end = max(start + 0.15, float(segment.end))
        lines.extend([str(count + 1), f"{stamp(start)} --> {stamp(end)}", text, ""])
        count += 1
    if count == 0:
        raise RuntimeError("No speech segments were detected; refusing to publish an empty caption file.")
    target = out_dir / "en.vtt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "metadata.txt").write_text(
        f"video_id={vid}\nsource=https://www.youtube.com/watch?v={vid}\n"
        f"language=en\nlanguage_probability={getattr(info, 'language_probability', 0):.3f}\n"
        f"segments={count}\ncaption_file=en.vtt\n",
        encoding="utf-8",
    )
    audio.unlink(missing_ok=True)
    print(f"CAPTIONS GENERATED: {target.relative_to(ROOT)}; language={getattr(info, 'language', 'unknown')}; segments={count}")
    print("NOTE: Machine-generated English captions; review names, quantities, and cooking terms.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CAPTION ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
