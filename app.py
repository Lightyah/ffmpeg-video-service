import os
import uuid
import subprocess
import tempfile
import requests
from flask import Flask, request, jsonify, send_file
from functools import wraps

app = Flask(__name__)

API_KEY = os.environ.get("API_KEY")


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if API_KEY:
            auth_header = request.headers.get("Authorization", "")
            token = auth_header.replace("Bearer ", "").strip()
            if token != API_KEY:
                return jsonify({"error": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated


def download_file(url, dest_path):
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest_path


def get_audio_duration(audio_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", audio_path
        ],
        capture_output=True, text=True
    )
    return float(result.stdout.strip())


def escape_text_for_drawtext(text):
    # Escape characters that break ffmpeg's drawtext filter
    text = text.replace("\\", "\\\\")
    text = text.replace(":", "\\:")
    text = text.replace("'", "\u2019")
    text = text.replace("%", "\\%")
    return text


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "ffmpeg-video-service"})


@app.route("/render-scene", methods=["POST"])
@require_api_key
def render_scene():
    """
    Expects multipart/form-data:
      image  - image file (binary)
      audio  - audio file (binary)
      caption - text field to burn in
      width   - optional text field, default 1080
      height  - optional text field, default 1920
    Returns: mp4 file
    """
    if "image" not in request.files or "audio" not in request.files:
        return jsonify({"error": "image and audio files are required (multipart/form-data)"}), 400

    caption = request.form.get("caption", "")
    width = int(request.form.get("width", 1080))
    height = int(request.form.get("height", 1920))

    work_id = str(uuid.uuid4())
    tmp_dir = tempfile.mkdtemp(prefix=f"scene_{work_id}_")

    try:
        image_path = os.path.join(tmp_dir, "image.jpg")
        audio_path = os.path.join(tmp_dir, "audio.mp3")
        output_path = os.path.join(tmp_dir, "output.mp4")

        request.files["image"].save(image_path)
        request.files["audio"].save(audio_path)

        duration = get_audio_duration(audio_path)
        # Ken Burns: slow zoom in over the duration of the clip
        fps = 25
        total_frames = int(duration * fps)

        zoompan_filter = (
            f"scale=1600:-1,"
            f"zoompan=z='min(zoom+0.0015,1.3)':d={total_frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        )

        safe_caption = escape_text_for_drawtext(caption)
        drawtext_filter = (
            f"drawtext=text='{safe_caption}':"
            f"fontcolor=white:fontsize=54:borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y=h-h/5:line_spacing=10:"
            f"box=1:boxcolor=black@0.35:boxborderw=20"
        )

        vf = f"{zoompan_filter},{drawtext_filter}"

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", image_path,
            "-i", audio_path,
            "-vf", vf,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return jsonify({"error": "ffmpeg failed", "details": result.stderr[-2000:]}), 500

        return send_file(output_path, mimetype="video/mp4", as_attachment=True, download_name="scene.mp4")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/concatenate", methods=["POST"])
@require_api_key
def concatenate():
    """
    Expects multipart/form-data with multiple files under the field name "videos"
    (send each scene video as a separate "videos" part, in order).
    Returns: final concatenated mp4
    """
    files = request.files.getlist("videos")

    if not files or len(files) < 1:
        return jsonify({"error": "at least one file is required under field name 'videos'"}), 400

    work_id = str(uuid.uuid4())
    tmp_dir = tempfile.mkdtemp(prefix=f"concat_{work_id}_")

    try:
        local_paths = []
        for i, file in enumerate(files):
            local_path = os.path.join(tmp_dir, f"part_{i}.mp4")
            file.save(local_path)
            local_paths.append(local_path)

        list_file = os.path.join(tmp_dir, "list.txt")
        with open(list_file, "w") as f:
            for p in local_paths:
                f.write(f"file '{p}'\n")

        output_path = os.path.join(tmp_dir, "final.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Fallback: re-encode if stream copy fails (mismatched codecs/params)
            cmd_reencode = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", list_file,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                output_path
            ]
            result2 = subprocess.run(cmd_reencode, capture_output=True, text=True)
            if result2.returncode != 0:
                return jsonify({"error": "ffmpeg concat failed", "details": result2.stderr[-2000:]}), 500

        return send_file(output_path, mimetype="video/mp4", as_attachment=True, download_name="final.mp4")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
