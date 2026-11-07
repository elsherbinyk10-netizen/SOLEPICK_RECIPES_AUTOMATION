#!/usr/bin/env python3
"""Generate timed English WebVTT captions without a paid API.

For YouTube, prefer the video's existing English subtitle track (including
YouTube auto-captions) before attempting media download + local Whisper. GitHub
runners can be blocked from downloading YouTube media; in that case provide a
permitted direct media URL or a local media file.
"""
import argparse
import atexit
import base64
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTIONS = ROOT / "captions"
AUDIO_SUFFIXES = {".m4a", ".mp3", ".webm", ".opus", ".wav", ".mp4", ".mkv", ".mov", ".aac", ".ogg"}
_COOKIE_FILE = None


def youtube_cookie_args():
    """Use an optional base64 Netscape cookie jar supplied through GitHub Secrets."""
    global _COOKIE_FILE
    encoded = os.environ.get("YOUTUBE_COOKIES_BASE64", "").strip()
    if not encoded:
        return []
    if _COOKIE_FILE and _COOKIE_FILE.is_file():
        return ["--cookies", str(_COOKIE_FILE)]
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not raw.lstrip().startswith((b"# Netscape HTTP Cookie File", b"# HTTP Cookie File")):
            raise ValueError("not a Netscape-format cookie jar")
    except Exception as exc:
        raise RuntimeError("YOUTUBE_COOKIES_BASE64 must contain a base64-encoded Netscape cookie file.") from exc
    handle = tempfile.NamedTemporaryFile(prefix="solepick-youtube-", suffix=".cookies", delete=False)
    try:
        handle.write(raw)
        handle.close()
        os.chmod(handle.name, 0o600)
        _COOKIE_FILE = Path(handle.name)
    except Exception:
        handle.close()
        Path(handle.name).unlink(missing_ok=True)
        raise
    atexit.register(lambda: _COOKIE_FILE and _COOKIE_FILE.unlink(missing_ok=True))
    print("YouTube access: optional authenticated cookie jar loaded from repository secret.")
    return ["--cookies", str(_COOKIE_FILE)]


def validate_vtt_file(path):
    """Require a WEBVTT header and at least one valid, non-empty timed cue."""
    raw = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.lstrip().startswith("WEBVTT"):
        raise ValueError(f"{path} is missing the WEBVTT header")
    cue_count = 0
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((line for line in lines if "-->" in line), None)
        if not timing:
            continue
        if not re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}", timing):
            raise ValueError(f"Invalid WebVTT timing: {timing}")
        index = lines.index(timing)
        if not any(line and not line.startswith(("NOTE", "STYLE", "REGION")) for line in lines[index + 1:]):
            raise ValueError("WebVTT cue has no caption text")
        cue_count += 1
    if cue_count == 0:
        raise ValueError(f"{path} contains no valid timed caption cues")
    return cue_count


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


def clean_youtube_vtt(source, target):
    """Accept only a non-empty, timed VTT file; never fabricate transcript text."""
    raw = source.read_text(encoding="utf-8-sig", errors="replace")
    if "-->" not in raw:
        return 0
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n").replace("\r", "\n"))
    cues = []
    for block in blocks:
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = lines[timing_index]
        if not re.match(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[.,]\d{3}", timing):
            continue
        text_lines = []
        for line in lines[timing_index + 1:]:
            if line.startswith(("<", "{")) and line.endswith((">", "}")):
                continue
            line = re.sub(r"<[^>]+>", "", line)
            line = re.sub(r"&amp;", "&", line)
            line = re.sub(r"&lt;", "<", line)
            line = re.sub(r"&gt;", ">", line)
            if line and line != "♪":
                text_lines.append(line)
        phrase = re.sub(r"\s+", " ", " ".join(text_lines)).strip()
        if phrase:
            cues.append((timing.replace(",", "."), phrase))
    if not cues:
        return 0
    output = ["WEBVTT", ""]
    for index, (timing, phrase) in enumerate(cues, 1):
        output.extend([str(index), timing, phrase, ""])
    target.write_text("\n".join(output) + "\n", encoding="utf-8")
    return len(cues)


def try_youtube_subtitles(vid, out_dir):
    """Fetch existing human or automatic English subtitles without downloading video."""
    template = str(out_dir / "source.%(ext)s")
    command = [
        sys.executable, "-m", "yt_dlp", "--no-warnings", "--no-progress",
        "--skip-download", "--write-subs", "--write-auto-subs",
        "--sub-langs", "en,en-US,en-GB", "--sub-format", "vtt",
        *youtube_cookie_args(), "--output", template, f"https://www.youtube.com/watch?v={vid}",
    ]
    print("Trying existing YouTube English captions first (no video download).")
    try:
        subprocess.run(command, check=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"Subtitle-track retrieval unavailable: {exc}")
        return 0
    target = out_dir / "en.vtt"
    for source in sorted(out_dir.glob("source*.vtt")):
        if clean_youtube_vtt(source, target):
            for candidate in out_dir.glob("source*"):
                candidate.unlink(missing_ok=True)
            return sum(1 for line in target.read_text(encoding="utf-8").splitlines() if "-->" in line)
    for candidate in out_dir.glob("source*"):
        candidate.unlink(missing_ok=True)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-url", help="YouTube URL/ID or a direct downloadable media URL")
    parser.add_argument("--media-file", help="Local video/audio file")
    parser.add_argument("--video-id", help="YouTube ID used to name the caption output for local/direct media")
    parser.add_argument("--model", default="small.en", choices=["tiny.en", "base.en", "small.en", "medium.en"])
    args = parser.parse_args()
    if not args.video_url and not args.media_file:
        parser.error("Provide --video-url or --media-file.")
    vid = args.video_id or (video_id(args.video_url) if args.video_url else None)
    if not vid:
        parser.error("A valid YouTube URL/ID or --video-id is required to name the caption output.")
    out_dir = CAPTIONS / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "en.vtt"

    # Prefer the video's real subtitle track when available. This bypasses the
    # media-download restriction and still produces real timed captions.
    if args.video_url and video_id(args.video_url) and not args.media_file:
        count = try_youtube_subtitles(vid, out_dir)
        if count:
            (out_dir / "metadata.txt").write_text(
                f"video_id={vid}\nsource={args.video_url}\nlanguage=en\n"
                f"method=youtube-subtitle-track\nsegments={count}\ncaption_file=en.vtt\n",
                encoding="utf-8",
            )
            print(f"CAPTIONS GENERATED: {target.relative_to(ROOT)}; source=YouTube English subtitle track; segments={count}")
            return
        print("No accessible English subtitle track; trying local transcription next.")

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
                *youtube_cookie_args(), "--output", str(out_dir / "audio.%(ext)s"),
                f"https://www.youtube.com/watch?v={vid}",
            ], check=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "YouTube denied subtitle and media access from this runner. No captions were fabricated. "
                "Supply a permitted direct media URL or a local video/audio file."
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
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        validated_count = validate_vtt_file(target)
        if validated_count != count:
            raise ValueError(f"Expected {count} cues but validated {validated_count}")
    except Exception:
        target.unlink(missing_ok=True)
        raise
    (out_dir / "metadata.txt").write_text(
        f"video_id={vid}\nsource={args.video_url or args.media_file}\n"
        f"language={getattr(info, 'language', 'unknown')}\n"
        f"language_probability={getattr(info, 'language_probability', 0):.3f}\n"
        f"method=faster-whisper\nsegments={count}\ncaption_file=en.vtt\n",
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
