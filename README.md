# My IPTV

A small IPTV playlist service for blitz.cloud.

## Features

- Downloads public playlists from iptv-org
- Updates automatically every 6 hours
- Keeps the previous playlist if an upstream download fails
- Generates:
  - all.m3u
  - china.m3u
  - cctv.m3u
  - japan.m3u
  - korea.m3u
  - hongkong.m3u
  - taiwan.m3u
- Uses the PORT environment variable supplied by the hosting platform

## Blitz

Deploy this repository from GitHub using the Dockerfile.

The image exposes port 8080.

After deployment:

- `/`
- `/health`
- `/all.m3u`
- `/cctv.m3u`
- `/china.m3u`
- `/japan.m3u`
- `/korea.m3u`
- `/hongkong.m3u`
- `/taiwan.m3u`

Optional environment variable:

`UPDATE_HOURS=6`

The iptv-org public playlists are generated from the project's channel data and published automatically.
