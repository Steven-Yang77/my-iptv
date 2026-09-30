import os
import requests

OUTPUT_DIR = "/app/output"

BASE_URL = "https://iptv-org.github.io/iptv"

FILES = {
    "china.m3u": f"{BASE_URL}/countries/cn.m3u",
    "japan.m3u": f"{BASE_URL}/countries/jp.m3u",
    "korea.m3u": f"{BASE_URL}/countries/kr.m3u",
}


def download(filename, url):
    print(f"Downloading {filename}...")

    r = requests.get(url, timeout=60)
    r.raise_for_status()

    path = os.path.join(OUTPUT_DIR, filename)

    with open(path, "wb") as f:
        f.write(r.content)

    print(f"Saved {path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for filename, url in FILES.items():
        try:
            download(filename, url)
        except Exception as e:
            print(f"Failed: {filename}: {e}")


if __name__ == "__main__":
    main()