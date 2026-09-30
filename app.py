import os
import threading
import time
from flask import Flask, Response, send_from_directory
from updater import update_all

OUTPUT_DIR = "/app/output"
PORT = int(os.environ.get("PORT", "8080"))
UPDATE_HOURS = float(os.environ.get("UPDATE_HOURS", "6"))

app = Flask(__name__)

def background_updater():
    # 首次启动立即更新；以后按 UPDATE_HOURS 周期更新。
    while True:
        try:
            update_all(OUTPUT_DIR)
        except Exception as e:
            print(f"[UPDATE ERROR] {e}", flush=True)
        time.sleep(max(1, int(UPDATE_HOURS * 3600)))

@app.route("/")
def index():
    files = [
        ("all.m3u", "全部：中/日/韩/港/台"),
        ("china.m3u", "中国"),
        ("cctv.m3u", "CCTV"),
        ("japan.m3u", "日本"),
        ("korea.m3u", "韩国"),
        ("hongkong.m3u", "香港"),
        ("taiwan.m3u", "台湾"),
    ]

    rows = "\n".join(
        f'<li><a href="/{name}">{label}</a></li>'
        for name, label in files
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>My IPTV</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 760px; margin: 40px auto; }}
a {{ text-decoration: none; }}
li {{ margin: 12px 0; }}
</style>
</head>
<body>
<h1>My IPTV</h1>
<p>Source: iptv-org</p>
<ul>{rows}</ul>
<p><a href="/health">Health</a></p>
</body>
</html>"""

@app.route("/health")
def health():
    return Response("OK\n", mimetype="text/plain")

@app.route("/<path:filename>")
def playlist(filename):
    if not filename.endswith(".m3u"):
        return Response("Not found\n", status=404, mimetype="text/plain")

    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        return Response(f"Playlist not ready: {filename}\n", status=503, mimetype="text/plain")

    return send_from_directory(
        OUTPUT_DIR,
        filename,
        mimetype="audio/x-mpegurl",
        max_age=0
    )

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 更新放后台线程，避免阻塞 Web 服务。
    thread = threading.Thread(target=background_updater, daemon=True)
    thread.start()

    print(f"[SERVER] Listening on 0.0.0.0:{PORT}", flush=True)
    print(f"[SERVER] Update interval: {UPDATE_HOURS} hours", flush=True)

    app.run(host="0.0.0.0", port=PORT, threaded=True)
