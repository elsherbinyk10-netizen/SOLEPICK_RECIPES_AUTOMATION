#!/usr/bin/env python3
"""Run ElevenLabs dubbing for a user-authorized, publicly reachable direct video URL.

Creates MP4s for review. Does not scrape YouTube/social embeds or publish to Shopify.
"""
import json, os, pathlib, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

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
    req = urllib.request.Request(url, headers={"User-Agent": "SolePickDubbing/1.0"})
    total = 0
    with urllib.request.urlopen(req, timeout=120) as response:
        ctype = (response.headers.get("Content-Type") or "").lower()
        if not (ctype.startswith("video/") or "octet-stream" in ctype):
            raise RuntimeError(f"Source URL did not return a video file (Content-Type: {ctype or 'unknown'}). Use a direct MP4 URL.")
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
    if not targets or len(targets) > 8:
        raise RuntimeError("Provide between 1 and 8 target language codes.")
    OUT.mkdir(parents=True, exist_ok=True)
    source_path = OUT / "source-video.mp4"
    print("Downloading the supplied direct video file. No social-site scraping is performed.", flush=True)
    download_source(source_url, source_path)
    headers = {"xi-api-key": key, "Accept": "application/json"}
    manifest = {"source_language": source_lang, "targets": []}
    for lang in targets:
        print(f"Submitting ElevenLabs dubbing job for {lang}.", flush=True)
        boundary = "----SolePickElevenLabsBoundary7MA4YWxk"
        fields = {
            "source_url": source_url,
            "source_lang": source_lang,
            "target_lang": lang,
            "name": f"SolePick recipe dubbing {lang}",
        }
        chunks = []
        for field, value in fields.items():
            chunks.extend([
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{field}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ])
        chunks.append(f"--{boundary}--\r\n".encode())
        payload = b"".join(chunks)
        raw, _ = http(API + "/dubbing", method="POST",
                      headers={**headers, "Content-Type": f"multipart/form-data; boundary={boundary}"},
                      body=payload, timeout=180)
        result = json.loads(raw.decode("utf-8"))
        job_id = result.get("dubbing_id")
        if not job_id:
            raise RuntimeError(f"ElevenLabs did not return a dubbing_id for {lang}.")
        encoded_id = urllib.parse.quote(job_id, safe="")
        deadline = time.time() + 3600
        while time.time() < deadline:
            raw, _ = http(f"{API}/dubbing/{encoded_id}", headers=headers)
            status_data = json.loads(raw.decode("utf-8"))
            state = str(status_data.get("status", "unknown")).lower()
            print(f"{lang}: {state}", flush=True)
            if state in ("dubbed", "completed", "complete"):
                break
            if state in ("failed", "error", "dubbing_failed"):
                raise RuntimeError(f"ElevenLabs reports dubbing failed for {lang}; inspect its dashboard.")
            time.sleep(15)
        else:
            raise RuntimeError(f"Timed out waiting for ElevenLabs job for {lang}.")
        url = f"{API}/dubbing/{encoded_id}/audio/{urllib.parse.quote(lang, safe='')}"
        result_bytes, ctype = http(url, headers={"xi-api-key": key, "Accept": "*/*"}, timeout=240)
        output_path = OUT / f"solepick-dubbed-{lang}.mp4"
        if ctype.lower().split(";", 1)[0] in ("video/mp4", "video/mpeg", "application/octet-stream") and result_bytes[:4] != b"PK\\x03\\x04":
            # ElevenLabs can return a complete dubbed video, depending on output type.
            output_path.write_bytes(result_bytes)
        else:
            audio_path = OUT / f"audio-{lang}.bin"
            audio_path.write_bytes(result_bytes)
            if audio_path.stat().st_size < 1024:
                raise RuntimeError(f"Returned media for {lang} is unexpectedly small (Content-Type: {ctype}).")
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source_path), "-i", str(audio_path),
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k", "-shortest",
                "-movflags", "+faststart", str(output_path)
            ], check=True)
        if not output_path.exists() or output_path.stat().st_size < 1024:
            raise RuntimeError(f"Output MP4 for {lang} was not created correctly.")
        manifest["targets"].append({"language": lang, "job_id": job_id, "output": output_path.name})
        print(f"Created {output_path}", flush=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / "README.txt").write_text(
        "Review dubbed videos for translation quality, pronunciation, timing, and sync before publishing. "
        "These are temporary workflow artifacts, not public hosting and not automatically connected to Shopify. "
        "Retention: 7 days.\n", encoding="utf-8"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
