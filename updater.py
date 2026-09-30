import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

API = "https://iptv-org.github.io/api"
STREAMS_URL = f"{API}/streams.json"
CHANNELS_URL = f"{API}/channels.json"

MAX_PER_CHANNEL = int(os.environ.get("MAX_PER_CHANNEL", "5"))
WORKERS = int(os.environ.get("CHECK_WORKERS", "24"))
TIMEOUT = float(os.environ.get("CHECK_TIMEOUT", "8"))
MAX_BYTES = 131072

COUNTRIES = [
    ("china.m3u", "CN"),
    ("japan.m3u", "JP"),
    ("korea.m3u", "KR"),
    ("hongkong.m3u", "HK"),
    ("taiwan.m3u", "TW"),
]

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 My-IPTV/3.0"})

def get_json(url):
    r = session.get(url, timeout=(15,90))
    r.raise_for_status()
    return r.json()

def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name+".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def qscore(q):
    m = re.search(r"(\d{3,4})p", str(q or "").lower())
    return int(m.group(1)) if m else 0

def penalty(labels):
    s = {str(x).lower() for x in (labels or [])}
    return 100*("not 24/7" in s) + 50*("timeshift" in s) + 20*("geo-blocked" in s)

def c_name(ch):
    return ch.get("name") or ch.get("id") or "Unknown"

def c_sort(ch):
    name = c_name(ch).strip()
    m = re.search(r"cctv[- _]?(\d+)", name.lower())
    if m: return (0, int(m.group(1)), name.lower())
    nums = re.findall(r"\d+", name)
    return (1, int(nums[0]) if nums else 999999, name.lower())

def source_score(s):
    return qscore(s.get("quality")) * 100 - penalty(s.get("labels"))

def read_prefix(r):
    data = b""
    for chunk in r.iter_content(8192):
        if chunk:
            data += chunk
            if len(data) >= MAX_BYTES: break
        if len(data) >= 8192 and b"#EXTM3U" in data: break
    return data

def fetch_segment(url, headers):
    try:
        with requests.get(url, headers=headers, timeout=(3,min(TIMEOUT,8)),
                          stream=True, allow_redirects=True) as r:
            if r.status_code >= 400: return False
            got = 0
            for chunk in r.iter_content(8192):
                if chunk:
                    got += len(chunk)
                    if got >= 1024: return True
            return False
    except Exception:
        return False

def first_segment(text, base):
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return urljoin(base, line)
    return None

def validate(url, headers):
    try:
        with requests.get(url, headers=headers, timeout=(3,TIMEOUT),
                          stream=True, allow_redirects=True) as r:
            if r.status_code >= 400: return None
            latency = r.elapsed.total_seconds()
            data = read_prefix(r)
            if not data: return None
            low = data.lower()
            ct = (r.headers.get("content-type") or "").lower()

            if b"#extm3u" in low or "mpegurl" in ct:
                text = data.decode("utf-8","replace")
                base = r.url

                # Master HLS: test the highest-bandwidth variant.
                if "#EXT-X-STREAM-INF" in text:
                    variants = []
                    lines = text.splitlines()
                    for i,line in enumerate(lines):
                        if line.startswith("#EXT-X-STREAM-INF:"):
                            j=i+1
                            while j<len(lines) and not lines[j].strip(): j+=1
                            if j<len(lines) and not lines[j].startswith("#"):
                                m=re.search(r"BANDWIDTH=(\d+)",line)
                                bw=int(m.group(1)) if m else 0
                                variants.append((bw,urljoin(base,lines[j].strip())))
                    if not variants: return None
                    child=max(variants,key=lambda x:x[0])[1]
                    with requests.get(child,headers=headers,timeout=(3,TIMEOUT),
                                      stream=True,allow_redirects=True) as cr:
                        if cr.status_code >= 400: return None
                        cd=read_prefix(cr)
                        if b"#extm3u" not in cd.lower(): return None
                        seg=first_segment(cd.decode("utf-8","replace"),cr.url)
                    if not seg or not fetch_segment(seg,headers): return None
                    return latency

                seg=first_segment(text,base)
                if not seg or not fetch_segment(seg,headers): return None
                return latency

            if "video/" in ct or "mpeg" in ct or "octet-stream" in ct:
                return latency
            return None
    except Exception:
        return None

def check(s):
    url=s.get("url")
    if not url or not url.startswith(("http://","https://")): return None
    h={"User-Agent":s.get("user_agent") or session.headers["User-Agent"]}
    if s.get("referrer"): h["Referer"]=s["referrer"]
    latency=validate(url,h)
    if latency is None: return None
    return s,latency

def info(ch,s):
    title=s.get("title") or c_name(ch)
    q=s.get("quality")
    if q and q.lower() not in title.lower(): title=f"{title} ({q})"
    attrs=[f'tvg-id="{ch.get("id","")}"']
    if ch.get("logo"): attrs.append(f'tvg-logo="{ch["logo"]}"')
    return f'#EXTINF:-1 {" ".join(attrs)},{title}'

def playlist(items):
    out=["#EXTM3U"]
    for ch,s in items:
        out.append(info(ch,s))
        if s.get("referrer"): out.append(f"#EXTVLCOPT:http-referrer={s['referrer']}")
        if s.get("user_agent"): out.append(f"#EXTVLCOPT:http-user-agent={s['user_agent']}")
        out.append(s["url"])
    return "\n".join(out)+"\n"

def candidates():
    streams=get_json(STREAMS_URL)
    channels=get_json(CHANNELS_URL)
    cmap={c.get("id"):c for c in channels if c.get("id")}
    groups={}
    for s in streams:
        cid=s.get("channel")
        ch=cmap.get(cid)
        if not cid or not ch or not s.get("url"): continue
        groups.setdefault(cid,{"channel":ch,"country":str(ch.get("country") or "").upper(),"streams":[]})["streams"].append(s)
    for d in groups.values():
        d["streams"].sort(key=lambda s:(source_score(s),str(s.get("url",""))),reverse=True)
    return groups

def check_country(groups, country):
    targets=[d for d in groups.values() if d["country"]==country]
    tasks=[]
    for d in targets:
        # More than 5 so failed candidates can be replaced.
        tasks += [(d["channel"],s) for s in d["streams"][:MAX_PER_CHANNEL+5]]

    alive={}
    print(f"[CHECK] {country}: {len(targets)} channels, {len(tasks)} candidates",flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        fmap={ex.submit(check,s):(ch,s) for ch,s in tasks}
        for n,f in enumerate(as_completed(fmap),1):
            result=f.result()
            if result:
                ch,s=fmap[f]
                alive.setdefault(ch.get("id"),[]).append((ch,s,result[1]))
            if n%100==0 or n==len(tasks):
                print(f"[CHECK] {country}: {n}/{len(tasks)}",flush=True)

    targets.sort(key=lambda d:c_sort(d["channel"]))
    selected=[]
    for d in targets:
        found=alive.get(d["channel"].get("id"),[])
        found.sort(key=lambda x:(source_score(x[1]),-x[2],str(x[1].get("url",""))),reverse=True)
        seen=set()
        for ch,s,lat in found:
            if s["url"] in seen: continue
            seen.add(s["url"])
            selected.append((ch,s))
            if sum(1 for x,y in selected if x.get("id")==ch.get("id")) >= MAX_PER_CHANNEL:
                break
    return selected

def update_all(output_dir):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    groups=candidates()
    all_items=[]

    for filename,country in COUNTRIES:
        try:
            items=check_country(groups,country)
            if items:
                atomic_write(out/filename,playlist(items))
                all_items += items
                print(f"[RESULT] {filename}: {len(items)} verified sources",flush=True)
            else:
                print(f"[RESULT] {filename}: none verified; old file kept",flush=True)
        except Exception as e:
            print(f"[RESULT] FAILED {filename}: {e}; old file kept",flush=True)

    cctv=[(ch,s) for ch,s in all_items if re.search(r"\bCCTV\b",c_name(ch),re.I)
           or str(ch.get("id","")).upper().startswith("CCTV")
           or "中国中央电视台" in c_name(ch)]
    if cctv: atomic_write(out/"cctv.m3u",playlist(cctv))
    if all_items: atomic_write(out/"all.m3u",playlist(all_items))
    print("[UPDATE] Finished.",flush=True)
