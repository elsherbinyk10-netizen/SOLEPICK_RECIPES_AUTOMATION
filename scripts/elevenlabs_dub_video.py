#!/usr/bin/env python3
"""Run ElevenLabs dubbing for a user-authorized, publicly reachable direct video URL.

This creates local MP4s for review. It does not publish media to Shopify or download
videos from YouTube/social embeds. Input URL must point directly to a video file.
"""
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.elevenlabs.io/v1"
OUT = pathlib.Path("dubbed-output")
MAX_BYTES = 1_000_000_000


def http(url, *, method="GET", headers=None, body=None, timeout=120):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"HTTP {exc.code} from service: {detail}") from None


def download_source(url, path):
    request = urllib.request.Request(url, headers={"User-Agent": "SolePickDubbing/1.0"})
    total = 0
    with urllib.request.urlopen(request, timeout=120) as response:
        content_type = (response.headers.get("Content-Type") or "").lower()
        if not (content_type.startswith("video/") or "octet-stream" in content_type):
            raise RuntimeError(f"Source URL did not return a video file (Content-Type: {content_type or 'unknown'}). Use a direct MP4 URL.")
        with path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BYTES:
                    raise RuntimeError("Source video exceeds the 1 GB safety limit.")
                handle.write(chunk)
    if total < 1024:
        raise RuntimeError("Downloaded source video is empty or too small.")


def main():
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    source_url = os.environ.get("SOURCE_VIDEO_URL", "").strip()
    source_lang = os.environ.get("SOURCE_LANGUAGE", "en").strip()
    targets = list(dict.fromkeys(x.strip() for x in os.environ.get("TARGET_LANGUAGES", "ar,es,fr").split(",") if x.strip()))
    if not key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY Actions secret.")
    parsed = urllib.parse.urlparse(source_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("SOURCE_VIDEO_URL must be a public HTTPS direct video URL.")
    if not targets:
        raise RuntimeError("TARGET_LANGUAGES must include at least one language code.")
    if len(targets) > 8:
        raise RuntimeError("Limit one run to 8 target languages.")
    OUT.mkdir(parents=True, exist_ok=True)
    source_path = OUT / "source-video.mp4"
    print("Downloading the supplied direct video file (no social-site scraping).", flush=True)
    download_source(source_url, source_path)
    headers = {"xi-api-key": key, "Accept": "application/json"}
    manifest = {"source_url": source_url, "source_language": source_lang, "targets": []}
    for lang in targets:
        print(f"Submitting ElevenLabs dubbing job for {lang}.", flush=True)
        payload = json.dumps({
            "url": source_url,
            "source_lang": source_lang,
            "target_lang": lang,
            "name": f"SolePick recipe dubbing {lang}"
        }).encode()
        raw, _ = http(API + "/dubbing", method="POST",
                      headers={**headers, "Content-Type": "application/json"},
                      body=payload, timeout=180)
        result = json.loads(raw.decode("utf-8"))
        job_id = result.get("dubbing_id")
        if not job_id:
            raise RuntimeError(f"ElevenLabs did not return a dubbing_id for {lang}.")
        encoded_id = urllib.parse.quote(job_id, safe="")
        deadline = time.time() + 3600
        while time.time() < deadline:
            raw, _ = http(f"{API}/dubbing/{encoded_id}", headers=headers)
            state_data = json.loads(raw.decode("utf-8"))
            state = str(state_data.get("status", "unknown")).lower()
            print(f"{lang}: {state}", flush=True)
            if state in ("dubbed", "completed", "complete"):
                break
            if state in ("failed", "error", "dubbing_failed"):
                raise RuntimeError(f"ElevenLabs reports dubbing failed for {lang}; inspect its dashboard.")
            time.sleep(15)
        else:
            raise RuntimeError(f"Timed out waiting for ElevenLabs job for {lang}.")
        audio_url = f"{API}/dubbing/{encoded_id}/audio/{urllib.parse.quote(lang, safe='')}"
        audio, content_type = http(audio_url, headers={"xi-api-key": key, "Accept": "*/*"}, timeout=240)
        audio_path = OUT / f"audio-{lang}.mp3"
        audio_path.write_bytes(audio)
        if len(audio) < 1024:
            raise RuntimeError(f"Returned audio for {lang} is unexpectedly small (Content-Type: {content_type}).")
        output_path = OUT / f"solepick-dubbed-{lang}.mp4"
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source_path), "-i", str(audio_path),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(output_path)
        ]
        subprocess.run(cmd, check=True)
        manifest["targets"].append({"language": lang, "job_id": job_id, "output": output_path.name})
        print(f"Created {output_path}", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / "README.txt").write_text(
        "Review every dubbed MP4 for translation quality, voice, timing, and audio/video sync before publishing. "
        "Files are temporary workflow artifacts, not a public media host and not automatically connected to Shopify. "
        "Workflow artifact retention is 7 days.\n",
        encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
