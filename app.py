import re
import math
from flask import Flask, request, jsonify, send_from_directory
import yt_dlp

app = Flask(__name__, static_folder="static")

TIKTOK_URL_RE = re.compile(r"tiktok\.com", re.IGNORECASE)


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

    formats = [format_entry(f) for f in info.get("formats", []) if f.get("vcodec") not in (None, "none")]

    # Pick the "best" as the highest-resolution format with both video+audio, falling back to highest res video-only
    def score(f):
        return (f["width"] or 0) * (f["height"] or 0)

    best = max(formats, key=score) if formats else None

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
