import os
import re
import json
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API = "https://iptv-org.github.io/api"
STREAMS_URL = f"{API}/streams.json"
CHANNELS_URL = f"{API}/channels.json"

MAX_PER_CHANNEL = int(os.environ.get("MAX_PER_CHANNEL", "5"))
WORKERS = int(os.environ.get("CHECK_WORKERS", "32"))
TIMEOUT = float(os.environ.get("CHECK_TIMEOUT", "6"))
MAX_BYTES = 65536

COUNTRIES = {
    "china": "CN",
    "japan": "JP",
    "korea": "KR",
    "hongkong": "HK",
    "taiwan": "TW",
}

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) My-IPTV/2.0"
})

def get_json(url):
    r = session.get(url, timeout=(15, 90))
    r.raise_for_status()
    return r.json()

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

def quality_score(q):
    if not q:
        return 0
    m = re.search(r"(\d{3,4})p", str(q).lower())
    return int(m.group(1)) if m else 0

def bad_label_score(labels):
    labels = {str(x).lower() for x in (labels or [])}
    # 不直接淘汰 Geo-blocked，因为“从 Blitz 测不到”并不等于
    # 用户所在网络一定不能看；最终仍以实际检测结果为准。
    score = 0
    if "not 24/7" in labels:
        score += 20
    if "timeshift" in labels:
        score += 10
    if "geo-blocked" in labels:
        score += 5
    return score

def channel_name(ch):
    return ch.get("name") or ch.get("id") or "Unknown"

def make_info(ch, stream):
    name = channel_name(ch)
    title = stream.get("title") or name
    quality = stream.get("quality")
    if quality and quality.lower() not in title.lower():
        title = f"{title} ({quality})"

    attrs = [
        f'tvg-id="{ch.get("id", "")}"',
    ]

    # API 中没有 logo 时也不影响播放。
    if ch.get("logo"):
        attrs.append(f'tvg-logo="{ch["logo"]}"')

    return f'#EXTINF:-1 {" ".join(attrs)},{title}'

def check_stream(stream):
    url = stream.get("url")
    if not url or not url.startswith(("http://", "https://")):
        return None

    headers = {
        "User-Agent": stream.get("user_agent") or session.headers["User-Agent"],
    }
    referrer = stream.get("referrer")
    if referrer:
        headers["Referer"] = referrer

    try:
        # GET 而不是 HEAD：很多 HLS/CDN 对 HEAD 支持很差。
        with requests.get(
            url,
            headers=headers,
            timeout=(3, TIMEOUT),
            stream=True,
            allow_redirects=True,
        ) as r:
            if r.status_code >= 400:
                return None

            data = b""
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    data += chunk
                    if len(data) >= MAX_BYTES:
                        break

            if not data:
                return None

            low = data[:MAX_BYTES].lower()

            # iptv-org 绝大多数直播地址为 HLS。
            # 接受标准 M3U8，也接受少数直接视频流/TS 返回。
            content_type = (r.headers.get("content-type") or "").lower()

            looks_hls = (
                b"#extm3u" in low
                or "mpegurl" in content_type
                or "application/vnd.apple.mpegurl" in content_type
            )

            looks_video = (
                "video/" in content_type
                or "octet-stream" in content_type
            )

            if not (looks_hls or looks_video):
                return None

            return {
                "stream": stream,
                "latency": r.elapsed.total_seconds(),
            }

    except requests.RequestException:
        return None
    except Exception:
        return None

def build_playlist(items):
    lines = ["#EXTM3U"]

    for ch, stream in items:
        lines.append(make_info(ch, stream))

        referrer = stream.get("referrer")
        user_agent = stream.get("user_agent")

        if referrer:
            lines.append(f"#EXTVLCOPT:http-referrer={referrer}")
            lines.append(f"#EXTHTTP:Referer={referrer}")

        if user_agent:
            lines.append(f"#EXTVLCOPT:http-user-agent={user_agent}")
            lines.append(f"#EXTHTTP:User-Agent={user_agent}")

        lines.append(stream["url"])

    return "\n".join(lines) + "\n"

def prepare_candidates():
    print("[UPDATE] Downloading iptv-org API...", flush=True)

    streams = get_json(STREAMS_URL)
    channels = get_json(CHANNELS_URL)

    channel_map = {x.get("id"): x for x in channels if x.get("id")}

    # 只保留有 channel 且 URL 有效的 stream。
    grouped = {}

    for s in streams:
        cid = s.get("channel")
        url = s.get("url")
        if not cid or not url:
            continue

        ch = channel_map.get(cid)
        if not ch:
            continue

        country = str(ch.get("country") or "").upper()
        grouped.setdefault(cid, {
            "channel": ch,
            "country": country,
            "streams": []
        })["streams"].append(s)

    # 候选顺序：
    # 1. 更高分辨率
    # 2. 没有 Not 24/7 / timeshift 等标签
    # 3. 有明确 quality
    for data in grouped.values():
        data["streams"].sort(
            key=lambda s: (
                quality_score(s.get("quality")),
                -bad_label_score(s.get("labels")),
                bool(s.get("quality")),
            ),
            reverse=True,
        )

    return grouped

def check_country(grouped, country_code):
    targets = [
        x for x in grouped.values()
        if x["country"] == country_code
    ]

    # 每个频道最多先检测 MAX_PER_CHANNEL + 2 个候选。
    # 如果其中有 Down，继续往后补，直到凑够 MAX_PER_CHANNEL。
    tasks = []
    for data in targets:
        candidates = data["streams"]
        for s in candidates[:MAX_PER_CHANNEL + 2]:
            tasks.append((data["channel"], s))

    alive = {}
    total = len(tasks)

    print(
        f"[CHECK] {country_code}: {len(targets)} channels, "
        f"{total} candidate streams",
        flush=True
    )

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        future_map = {
            pool.submit(check_stream, s): (ch, s)
            for ch, s in tasks
        }

        done = 0
        for future in as_completed(future_map):
            done += 1
            result = future.result()

            if result:
                ch, original = future_map[future]
                cid = ch.get("id")

                alive.setdefault(cid, []).append(
                    (ch, result["stream"], result["latency"])
                )

            if done % 100 == 0 or done == total:
                print(
                    f"[CHECK] {country_code}: {done}/{total}",
                    flush=True
                )

    selected = []

    for data in targets:
        cid = data["channel"].get("id")
        found = alive.get(cid, [])

        # “最好”的实际排序：
        # 清晰度优先，其次标签，最后实际响应速度。
        found.sort(
            key=lambda x: (
                quality_score(x[1].get("quality")),
                -bad_label_score(x[1].get("labels")),
                -x[2],
            ),
            reverse=True,
        )

        # URL 去重
        seen = set()
        count = 0

        for ch, stream, latency in found:
            url = stream.get("url")
            if url in seen:
                continue
            seen.add(url)

            selected.append((ch, stream))
            count += 1

            if count >= MAX_PER_CHANNEL:
                break

    return selected

def update_all(output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    grouped = prepare_candidates()

    all_items = []

    for filename, country_code in [
        ("china.m3u", "CN"),
        ("japan.m3u", "JP"),
        ("korea.m3u", "KR"),
        ("hongkong.m3u", "HK"),
        ("taiwan.m3u", "TW"),
    ]:
        try:
            items = check_country(grouped, country_code)

            if items:
                atomic_write(
                    output / filename,
                    build_playlist(items)
                )

                all_items.extend(items)

                channels_count = len({
                    ch.get("id") for ch, _ in items
                })

                print(
                    f"[RESULT] {filename}: "
                    f"{channels_count} channels / {len(items)} live sources",
                    flush=True
                )
            else:
                print(
                    f"[RESULT] {filename}: no live sources; old file kept",
                    flush=True
                )

        except Exception as e:
            print(
                f"[RESULT] FAILED {filename}: {e}; old file kept",
                flush=True
            )

    # CCTV：从中国检测后的结果里筛选。
    cctv = []
    for ch, stream in all_items:
        name = channel_name(ch)
        cid = str(ch.get("id") or "")
        if (
            re.search(r"\bCCTV\b", name, re.I)
            or cid.upper().startswith("CCTV")
            or "中国中央电视台" in name
        ):
            cctv.append((ch, stream))

    if cctv:
        atomic_write(output / "cctv.m3u", build_playlist(cctv))
        print(f"[RESULT] cctv.m3u: {len(cctv)} live sources", flush=True)

    if all_items:
        atomic_write(
            output / "all.m3u",
            build_playlist(all_items)
        )
        print(
            f"[RESULT] all.m3u: {len(all_items)} live sources",
            flush=True
        )

    print("[UPDATE] Finished.", flush=True)
