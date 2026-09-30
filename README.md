# My IPTV

Blitz.cloud IPTV service based on the public iptv-org API.

## What it does

Every update:

1. Downloads iptv-org `streams.json` and `channels.json`.
2. Groups streams by channel.
3. Ranks candidates by quality and labels.
4. Tests the actual stream URL with HTTP GET.
5. Keeps only streams that return usable HLS/video content.
6. Keeps at most 5 working sources per channel.
7. Sorts the surviving sources by quality and response time.
8. Writes playlists atomically, so a failed update does not destroy the previous working playlist.

## Playlists

- `/all.m3u`
- `/china.m3u`
- `/cctv.m3u`
- `/japan.m3u`
- `/korea.m3u`
- `/hongkong.m3u`
- `/taiwan.m3u`

## Environment variables

- `PORT` — supplied automatically by Blitz.
- `UPDATE_HOURS` — default `6`.
- `MAX_PER_CHANNEL` — default `5`.
- `CHECK_WORKERS` — default `32`.
- `CHECK_TIMEOUT` — default `6` seconds.

Example:

`MAX_PER_CHANNEL=5`

`CHECK_WORKERS=32`

`CHECK_TIMEOUT=6`

## Important

The checker tests reachability from the Blitz server. A stream can be reachable from Blitz but geo-blocked from your own network, or vice versa.

The public iptv-org playlists normally keep only the best available option for each channel. This service deliberately uses the iptv-org API's full stream list so it can test multiple candidates and retain up to five working backups.
