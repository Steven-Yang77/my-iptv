from flask import Flask, send_from_directory
import os

app = Flask(__name__)

OUTPUT_DIR = "/app/output"


@app.route("/")
def index():
    return """
    <h1>My IPTV</h1>
    <p><a href="/all.m3u">All IPTV</a></p>
    <p><a href="/cctv.m3u">CCTV</a></p>
    <p><a href="/china.m3u">China</a></p>
    <p><a href="/japan.m3u">Japan</a></p>
    <p><a href="/korea.m3u">Korea</a></p>
    """


@app.route("/<path:filename>")
def files(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)