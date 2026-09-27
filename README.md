# OverCue Stems USB Format

This repository documents the USB files written by OverCue Desktop for prepared stems. A project for another player can read the same files and use its own controls and audio path. The format does not require OverCue firmware or a particular stem separation model.

Start with [FORMAT.md](FORMAT.md). It specifies track lookup, the seven audio roles, the `OVPGZ001` page container, and the checks a reader should perform. [verify_usb.py](verify_usb.py) is a small Python standard-library example that checks a prepared track without changing the USB:

```sh
python3 verify_usb.py "/Volumes/DJ USB" "/Contents/Artist/Track.mp3"
python3 -m unittest discover -s tests
```

Use the exact media path shown in `/CDJMODS/index.json`. A player with different library IDs can match that path to its loaded track. If its paths differ, the integration must establish an equally reliable mapping before enabling stems.

OverCue Desktop currently prepares USBs containing a Rekordbox `PIONEER/rekordbox/export.pdb` export. Other hardware can consume the resulting `/CDJMODS` data when it can access that USB and identify the matching loaded song; preparing an arbitrary non-Rekordbox USB is not yet an app feature.

This is an open description of the format OverCue currently writes, not a claim that every player already supports it. Hardware integrations must independently validate timing, audio quality, and safe fallback on their own devices. Contributions and compatibility reports are welcome through GitHub issues and pull requests.

Only synthetic test media belongs in this repository. Do not submit music, prepared user USBs, model files, firmware, device dumps, keys, or credentials.

Licensed under [MIT](LICENSE).
