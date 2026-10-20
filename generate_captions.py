#!/usr/bin/env python3
"""Generate timed English WebVTT captions from a video, without a paid API.

Preferred input is a local video/audio file or a direct audio URL. YouTube URLs
are attempted as a convenience, but GitHub-hosted runners may be blocked by
YouTube anti-bot checks. In that case upload the media file to the workflow run
or use a permitted direct media URL.
"""
import argparse
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTIONS = ROOT / "captions"
AUDIO_SUFFIXES = {".m4a", ".mp3", ".webm", ".opus", ".wav", ".mp4", ".mkv", ".mov", ".aac", ".ogg"}


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
    return None


def stamp(seconds):
    ms = max(0, round(float(seconds) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-url", help="YouTube URL, video ID, or direct media URL")
    parser.add_argument("--media-file", help="Local video/audio file, preferred for YouTube-blocked environments")
    parser.add_argument("--video-id", help="YouTube ID used for the output caption folder when media-file is supplied")
    parser.add_argument("--model", default="small.en", choices=["tiny.en", "base.en", "small.en", "medium.en"])
    args = parser.parse_args()
    if not args.video_url and not args.media_file:
        parser.error("Provide --video-url or --media-file.")
    vid = args.video_id or (video_id(args.video_url) if args.video_url else None)
    if not vid:
        parser.error("A valid YouTube URL/ID or --video-id is required to name the caption output.")
    out_dir = CAPTIONS / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = None

    if args.media_file:
        source = Path(args.media_file).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Media file does not exist: {source}")
        audio = out_dir / ("audio" + source.suffix.lower())
        if source != audio.resolve():
            audio.write_bytes(source.read_bytes())
        print(f"Using supplied media file: {source.name}")
    elif args.video_url and not video_id(args.video_url):
        suffix = Path(args.video_url.split("?", 1)[0]).suffix.lower()
        if suffix not in AUDIO_SUFFIXES:
            suffix = ".media"
        audio = out_dir / ("audio" + suffix)
        print("Downloading direct media URL; no API key required.")
        request = urllib.request.Request(args.video_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=90) as response, audio.open("wb") as dest:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                dest.write(chunk)
    else:
        print("Attempting YouTube audio download (no API key).")
        try:
            subprocess.run([
                sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-progress",
                "-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a",
                "--output", str(out_dir / "audio.%(ext)s"),
                f"https://www.youtube.com/watch?v={vid}",
            ], check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                "YouTube blocked the runner or denied media access. No captions were fabricated. "
                "Rerun with --media-file for an uploaded video/audio file, or supply a permitted direct media URL."
            ) from exc
        audio = next((p for p in out_dir.glob("audio.*") if p.suffix.lower() in AUDIO_SUFFIXES), None)
    if audio is None or not audio.is_file() or audio.stat().st_size == 0:
        raise RuntimeError("No usable audio/video file was available for transcription.")

    from faster_whisper import WhisperModel
    print(f"Transcribing locally with faster-whisper {args.model}; this can take several minutes.")
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio), beam_size=5, vad_filter=True)
    lines = ["WEBVTT", ""]
    count = 0
    for segment in segments:
        phrase = re.sub(r"\s+", " ", str(segment.text or "")).strip()
        if not phrase:
            continue
        start = max(0.0, float(segment.start))
        end = max(start + 0.15, float(segment.end))
        lines.extend([str(count + 1), f"{stamp(start)} --> {stamp(end)}", phrase, ""])
        count += 1
    if count == 0:
        raise RuntimeError("No speech segments were detected; refusing to publish an empty caption file.")
    target = out_dir / "en.vtt"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "metadata.txt").write_text(
        f"video_id={vid}\nsource={args.video_url or args.media_file}\n"
        f"language={getattr(info, 'language', 'unknown')}\n"
        f"language_probability={getattr(info, 'language_probability', 0):.3f}\n"
        f"segments={count}\ncaption_file=en.vtt\n",
        encoding="utf-8",
    )
    if audio and audio.parent == out_dir and audio.name.startswith("audio"):
        audio.unlink(missing_ok=True)
    print(f"CAPTIONS GENERATED: {target.relative_to(ROOT)}; language={getattr(info, 'language', 'unknown')}; segments={count}")
    print("Machine-generated captions need review for ingredient names, quantities, and cooking terms.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"CAPTION ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
