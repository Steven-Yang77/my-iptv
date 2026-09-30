# My IPTV v3

Strict IPTV validation for Blitz.cloud.

Each candidate is tested beyond HTTP 200:
- fetch HLS playlist
- if master playlist, fetch a variant
- locate the first media segment
- fetch the first segment
- only then mark the source playable

For each channel, at most 5 verified sources are kept. Sources are ordered by quality, labels, then response latency. Channel order is deterministic.

Environment:
- UPDATE_HOURS=6
- MAX_PER_CHANNEL=5
- CHECK_WORKERS=24
- CHECK_TIMEOUT=8
