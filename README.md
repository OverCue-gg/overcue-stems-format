# OverCue Stems USB Format

This repository documents the USB files written by OverCue Desktop for prepared stems. A project for another player can read the same files and use its own controls and audio path. The format does not require OverCue firmware or a particular stem separation model.

Start with [FORMAT.md](FORMAT.md). It specifies track lookup through `index.json` and the bounded `index-v2`, the audio roles, the FLAC `OVPGZ003` and legacy zlib `OVPGZ001` page containers, the experimental 44.1 kHz CDJ-2000 profiles, and the checks a reader should perform. [verify_usb.py](verify_usb.py) is a small Python example that checks a prepared track without changing the USB:

```sh
python3 verify_usb.py "/Volumes/DJ USB" "/Contents/Artist/Track.mp3"
python3 -m unittest discover -s tests
```

Python 3 is required. FLAC validation also requires `ffmpeg` on `PATH`; zlib and WAV validation use only the Python standard library. The tests generate synthetic audio locally; they do not need a prepared USB. FLAC tests are skipped if ffmpeg is unavailable. The validator starts one decoder process per page; it is an offline verification example, not a real-time playback implementation. When the USB has `index-v2`, it also checks that the track's records there match `index.json`.

## What changed

**Desktop 2.2.40 (Mac) / 2.2.41 (Windows), firmware 0.14.0: bounded stems index.** The app now also writes `/CDJMODS/index-v2`, a compact binary index that lets a player read one track's entry instead of the whole `index.json`. With firmware 0.14.0 a USB's stem library is no longer capped by the 4 MiB of `index.json` older firmware reads; the app lets it grow to 256 MiB and warns when older players can no longer load it. USBs prepared earlier offer **Upgrade stems index**, which converts existing stems without processing them again; **Repair stems index** rebuilds an interrupted or damaged one. Audio files are unchanged. See [Bounded index](FORMAT.md#bounded-index-index-v2).

**Same release: ffmpeg-encoded MP3 timing (`native-mp3-header/2`).** MP3s whose Info tag names an ffmpeg encoder (`Lavc`/`Lavf`), such as recent Beatport downloads, no longer get the extra metadata-frame delay that made their stems play about 26 ms behind the full mix and grid. Stem waveforms now follow the same timeline as the stem audio. Affected banks show **Needs realignment** and are corrected in place without separating again. See [source timing](FORMAT.md#source-timing-and-regeneration).

**Desktop 2.2.24 (Mac) / 2.2.25 (Windows), firmware 0.13.1: four-file banks.** New CDJ-3000 banks store only vocal, drums, harmonics and full mix (`three_part: 2`); the player mixes the instrumental and vocal pairs from them. Seven-file banks (`three_part: 1`) stay valid, and **Remove unused files** converts them. See [audio roles](FORMAT.md#audio-roles).

**Experimental CDJ-2000 profiles.** Desktop can prepare 44.1 kHz stems as `OVPGZ004` FLAC pages (CDJ-2000NXS2) or plain WAV roles (CDJ-2000/2000NXS) for a separate player reader. Their hardware compatibility and timing are not qualified by OverCue.

**Earlier.** Desktop 2.2.0 (Mac) / 2.2.1 (Windows) introduced lossless FLAC pages, which need OverCue firmware 0.10.0 or newer on every player; zlib stems still work. Desktop 2.2.5 (Mac) / 2.2.6 (Windows) corrected the timeline of MP3s whose initial metadata frame was skipped during decoding (`native-mp3-header/1`).

Updating the app does not rewrite prepared media, and the byte-level validator checks file integrity, not alignment with a player's native full-mix playback.

## Using the files on other hardware

Use the exact media path shown in `/CDJMODS/index.json`. A player with different library IDs can match that path to its loaded track. If its paths differ, the integration must establish an equally reliable mapping before enabling stems. `index-v2` is keyed by Rekordbox library IDs only.

OverCue Desktop currently prepares USBs containing a Rekordbox `PIONEER/rekordbox/export.pdb` export. Other hardware can consume the resulting `/CDJMODS` data when it can access that USB and identify the matching loaded song; preparing an arbitrary non-Rekordbox USB is not yet an app feature.

This is an open description of the format OverCue currently writes, not a claim that every player already supports it. Hardware integrations must independently validate timing, audio quality, and safe fallback on their own devices. Contributions and compatibility reports are welcome through GitHub issues and pull requests.

Only synthetic test media belongs in this repository. Do not submit music, prepared user USBs, model files, firmware, device dumps, keys, or credentials.

Licensed under [MIT](LICENSE).
