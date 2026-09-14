import re
import math
import subprocess
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp
import imageio_ffmpeg

app = Flask(__name__, static_folder="static")

TIKTOK_URL_RE = re.compile(r"tiktok\.com", re.IGNORECASE)
FPS_LINE_RE = re.compile(r"(\d+(?:\.\d+)?)\s+fps")

FFMPEG_BIN = imageio_ffmpeg.get_ffmpeg_exe()


def probe_fps(raw_format):
    """Fall back to reading the real frame rate straight off the video
    when TikTok's own metadata doesn't report one. Only reads enough of
    the file to see the stream header, not the whole clip."""
    url = raw_format.get("url")
    if not url:
        return None

    cmd = [FFMPEG_BIN]
    headers = raw_format.get("http_headers") or {}
    if headers:
        header_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        cmd += ["-headers", header_str]
    cmd += ["-i", url, "-t", "0.2", "-f", "null", "-"]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
    except (subprocess.TimeoutExpired, OSError):
        return None

    match = FPS_LINE_RE.search(proc.stderr)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def human_size(num_bytes):
    if not num_bytes:
        return None
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def format_entry(f):
    width = f.get("width")
    height = f.get("height")
    resolution = f"{width}x{height}" if width and height else None

    filesize = f.get("filesize") or f.get("filesize_approx")
    bitrate_kbps = f.get("tbr")

    return {
        "format_id": f.get("format_id"),
        "ext": f.get("ext"),
        "resolution": resolution,
        "width": width,
        "height": height,
        "fps": f.get("fps"),
        "vcodec": f.get("vcodec") if f.get("vcodec") not in (None, "none") else None,
        "acodec": f.get("acodec") if f.get("acodec") not in (None, "none") else None,
        "bitrate_kbps": round(bitrate_kbps) if bitrate_kbps else None,
        "filesize_bytes": filesize,
        "filesize_human": human_size(filesize) if filesize else None,
        "note": f.get("format_note"),
        "has_watermark_hint": "watermark" in (f.get("format_note") or "").lower(),
    }


@app.route("/api/check")
def check():
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "Paste a TikTok video link first."}), 400
    if not TIKTOK_URL_RE.search(url):
        return jsonify({"error": "That doesn't look like a TikTok link."}), 400

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extractor_args": {"tiktok": {"api_hostname": ["api22-normal-c-useast2a.tiktokv.com"]}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        return jsonify({"error": "Couldn't fetch that video. It may be private, region-locked, or the link is invalid."}), 502
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {e}"}), 500

    raw_video_formats = [f for f in info.get("formats", []) if f.get("vcodec") not in (None, "none")]
    formats = [format_entry(f) for f in raw_video_formats]

    # Pick the "best" as the highest-resolution format with both video+audio, falling back to highest res video-only
    def score(f):
        return (f["width"] or 0) * (f["height"] or 0)

    best = None
    best_raw = None
    if formats:
        best_index = max(range(len(formats)), key=lambda i: score(formats[i]))
        best = formats[best_index]
        best_raw = raw_video_formats[best_index]

    # TikTok doesn't always report fps in its own metadata. Try the
    # video-level field first (free), then probe the actual file (slower).
    if best and not best.get("fps"):
        best["fps"] = info.get("fps")
    if best and not best.get("fps") and best_raw:
        best["fps"] = probe_fps(best_raw)

    duration = info.get("duration")
    result = {
        "title": info.get("title") or info.get("description"),
        "author": info.get("uploader") or info.get("creator"),
        "duration_seconds": duration,
        "thumbnail": info.get("thumbnail"),
        "like_count": info.get("like_count"),
        "view_count": info.get("view_count"),
        "best": best,
        "formats": formats,
    }
    return jsonify(result)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
