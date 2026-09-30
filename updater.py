import os
import re
import tempfile
from pathlib import Path
import requests

BASE = "https://iptv-org.github.io/iptv"

SOURCES = {
    "china.m3u": f"{BASE}/countries/cn.m3u",
    "japan.m3u": f"{BASE}/countries/jp.m3u",
    "korea.m3u": f"{BASE}/countries/kr.m3u",
    "hongkong.m3u": f"{BASE}/countries/hk.m3u",
    "taiwan.m3u": f"{BASE}/countries/tw.m3u",
}

CCTV_RE = re.compile(
    r"(?:^|[^A-Z0-9])CCTV(?:[- _]?[0-9]{1,2}(?:\+)?|[ _-]5\+)?(?:[^A-Z0-9]|$)",
    re.IGNORECASE
)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 My-IPTV-Updater/1.0"
})

def download(url):
    r = session.get(url, timeout=(15, 90))
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    if not text.lstrip().startswith("#EXTM3U"):
        raise RuntimeError(f"Invalid M3U received from {url}")
    return text.replace("\r\n", "\n").replace("\r", "\n")

def parse_entries(text):
    lines = text.splitlines()
    header = lines[0].strip() if lines else "#EXTM3U"
    entries = []
    i = 1

    while i < len(lines):
        line = lines[i].strip()

        if line.startswith("#EXTINF:"):
            info = line
            j = i + 1

            # 跳过空行和注释，找到真正的播放地址。
            while j < len(lines):
                candidate = lines[j].strip()
                if candidate and not candidate.startswith("#"):
                    entries.append((info, candidate))
                    i = j
                    break
                j += 1
            else:
                i += 1
                continue

        i += 1

    return header, entries

def entry_name(info):
    if "," in info:
        return info.split(",", 1)[1].strip()
    return info

def dedupe(entries):
    seen = set()
    result = []

    for info, url in entries:
        key = (info, url)
        if key in seen:
            continue
        seen.add(key)
        result.append((info, url))

    return result

def make_m3u(header, entries):
    out = [header]
    for info, url in entries:
        out.append(info)
        out.append(url)
    return "\n".join(out) + "\n"

def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def update_all(output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    all_entries = []
    china_entries = []

    print("[UPDATE] Downloading iptv-org playlists...", flush=True)

    for filename, url in SOURCES.items():
        try:
            text = download(url)
            header, entries = parse_entries(text)
            entries = dedupe(entries)

            if not entries:
                raise RuntimeError("No channels found")

            atomic_write(output / filename, make_m3u(header, entries))

            print(
                f"[UPDATE] {filename}: {len(entries)} channels",
                flush=True
            )

            all_entries.extend(entries)

            if filename == "china.m3u":
                china_entries = entries

        except Exception as e:
            # 更新失败时保留旧文件，不把可用列表覆盖掉。
            print(f"[UPDATE] FAILED {filename}: {e}", flush=True)

    # CCTV：只从中国列表中筛选名称含 CCTV 的频道。
    cctv = [
        item for item in china_entries
        if CCTV_RE.search(entry_name(item[0]))
    ]

    if cctv:
        atomic_write(
            output / "cctv.m3u",
            make_m3u("#EXTM3U", dedupe(cctv))
        )
        print(f"[UPDATE] cctv.m3u: {len(cctv)} channels", flush=True)
    else:
        print("[UPDATE] CCTV filter found 0 channels; old file kept.", flush=True)

    if all_entries:
        atomic_write(
            output / "all.m3u",
            make_m3u("#EXTM3U", dedupe(all_entries))
        )
        print(
            f"[UPDATE] all.m3u: {len(dedupe(all_entries))} channels",
            flush=True
        )

    print("[UPDATE] Finished.", flush=True)
