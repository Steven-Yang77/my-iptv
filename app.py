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
    while True:
        try:
            update_all(OUTPUT_DIR)
        except Exception as e:
            print(f"[UPDATE ERROR] {e}", flush=True)
        time.sleep(max(1, int(UPDATE_HOURS * 3600)))

@app.route("/")
def index():
    names = [
        ("all.m3u","全部"),("china.m3u","中国"),("cctv.m3u","CCTV"),
        ("japan.m3u","日本"),("korea.m3u","韩国"),
        ("hongkong.m3u","香港"),("taiwan.m3u","台湾")
    ]
    rows = "".join(f'<li><a href="/{a}">{b}</a></li>' for a,b in names)
    return f"<h1>My IPTV</h1><p>Strict playback check enabled</p><ul>{rows}</ul><p><a href='/health'>Health</a></p>"

@app.route("/health")
def health():
    return Response("OK\n", mimetype="text/plain")

@app.route("/<path:filename>")
def playlist(filename):
    if not filename.endswith(".m3u"):
        return Response("Not found\n", status=404)
    path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        return Response(f"Playlist not ready: {filename}\n", status=503)
    return send_from_directory(OUTPUT_DIR, filename, mimetype="audio/x-mpegurl", max_age=0)

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    threading.Thread(target=background_updater, daemon=True).start()
    print(f"[SERVER] Listening on 0.0.0.0:{PORT}", flush=True)
    app.run(host="0.0.0.0", port=PORT, threaded=True)
