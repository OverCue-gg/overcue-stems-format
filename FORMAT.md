# OverCue prepared-stems USB format

Status: current seven-role USB layout, checked against Desktop 2.2.0/2.2.1 and OverCue firmware 0.10.1. The JSON schema string is `overcue-index/1`; a seven-role entry has `three_part: 1`. This document covers prepared media only. It does not specify how stems are separated or how a player mod is installed.

## Directory and track identity

```text
USB root/
  Contents/...                         original exported music, unchanged
  CDJMODS/
    index.json                          published after the bundle files
    stems/<bundle>/
      stems-sidecar-vocal.s16le.pgz
      stems-sidecar-instrumental.s16le.pgz
      stems-sidecar-drums.s16le.pgz
      stems-sidecar-harmonics.s16le.pgz
      stems-sidecar-vocals-drums.s16le.pgz
      stems-sidecar-vocals-harmonics.s16le.pgz
      stems-sidecar-full-mix.s16le.pgz
      overcue-manifest.json             advisory metadata
      stems-*-waveform.EXT / .2EX      optional player-specific analysis
```

The current seven-role writer produces FLAC-paged `.pgz` files (`OVPGZ003`); legacy files use zlib pages (`OVPGZ001`). The extension is unchanged and the file magic selects the decoder; uncompressed `.s16le` copies are **not** required. A bundle name is exactly 16 lowercase hexadecimal characters. Readers must treat index strings as untrusted input and must never let them escape the USB root. `/CDJMODS/index.json` is limited to 4 MiB by current OverCue readers.

The index is UTF-8 JSON. Its relevant shape is:

```json
{
  "schema": "overcue-index/1",
  "keyed_by": "export.pdb",
  "tracks": {
    "123": {
      "bundle": "0123456789abcdef",
      "file_path": "/Contents/Artist/Track.mp3",
      "frames": 960960,
      "three_part": 1,
      "page_bytes": 131072,
      "page_codec": "flac-96k",
      "vocal_sha256": "<SHA-256 of expanded vocal PCM>",
      "vocal_page_table_sha256": "<SHA-256 of vocal header and page table>",
      "instrumental_sha256": "<SHA-256 of expanded instrumental PCM>",
      "instrumental_page_table_sha256": "<SHA-256 of instrumental header and page table>",
      "drums_sha256": "<SHA-256 of expanded drums PCM>",
      "drums_page_table_sha256": "<SHA-256 of drums header and page table>",
      "harmonics_sha256": "<SHA-256 of expanded harmonics PCM>",
      "harmonics_page_table_sha256": "<SHA-256 of harmonics header and page table>",
      "vocals_drums_sha256": "<SHA-256 of expanded vocals-drums PCM>",
      "vocals_drums_page_table_sha256": "<SHA-256 of vocals-drums header and page table>",
      "vocals_harmonics_sha256": "<SHA-256 of expanded vocals-harmonics PCM>",
      "vocals_harmonics_page_table_sha256": "<SHA-256 of vocals-harmonics header and page table>",
      "full_mix_sha256": "<SHA-256 of expanded full-mix PCM>",
      "full_mix_page_table_sha256": "<SHA-256 of full-mix header and page table>"
    }
  },
  "tracks_onelibrary": {}
}
```

Digest placeholders above stand for 64 lowercase hexadecimal characters, not literal values. `frames` counts stereo PCM frames **including** leading silence. Each role expands to exactly `frames * 4` bytes. `page_bytes` is the uncompressed page size; the current seven-role writer uses 131,072 bytes. The seven-role entries use one bundle, frame count, and page size for all roles.

`tracks` keys are decimal Device Library (`export.pdb`) track IDs. `tracks_onelibrary` keys are decimal OneLibrary (`exportLibrary.db`) content IDs. These are separate number spaces: an equal number does not imply an equal song. `file_path` is the exported music path relative to the USB root, with a leading `/`. OverCue joins the two maps by that exact path. A project with a different library can search entries by `file_path` and reject ambiguous matches; if its loaded-track path differs, it must establish a trustworthy mapping. If `source_sha256` is present, checking the original music file against it provides an additional identity check.

`page_codec` is advisory metadata: `flac-96k` for FLAC and `zlib` for legacy pages. Older entries may omit it. Read and validate each file magic rather than selecting a decoder from the extension or metadata. Unsupported magic (including `OVPGZ002`) must be rejected.

Entries can contain `title`, `separation`, `loudness_policy`, and other metadata; the top-level index can contain `updated`. A reader does not need to interpret them to decode the audio. Unknown fields must not change the meaning of the required fields.

## Audio roles

Each file is a complete stereo selection, already prepared at **96,000 frames/second**, signed 16-bit little-endian PCM, interleaved left then right. Do not add the roles together at playback. All seven files have the same frame count and start position.

| Role in filename | Audio selection |
| --- | --- |
| `vocal` | Vocals |
| `instrumental` | Drums plus harmonics; everything except vocals |
| `drums` | Drums |
| `harmonics` | Non-vocal, non-drum instruments |
| `vocals-drums` | Vocals plus drums |
| `vocals-harmonics` | Vocals plus harmonics |
| `full-mix` | Prepared copy of the original full mix |

The writer resamples, applies a common headroom gain and any downward loudness trims, and prepends silence to account for source encoder delay. It then pads roles to equal length. These processing choices affect the bytes and are already reflected in the indexed hashes; a reader must play the stored PCM rather than reconstructing combinations. `overcue-manifest.json` records `runtime.latency_pad_frames`, the source codec/rate, and per-role metadata for diagnostics. The pad describes the writer's source timing, **not** a universal player latency offset. A hardware implementation must align the 96 kHz sidecars with its own full-mix decode and test seeks, loops, tempo changes, and fallback before claiming audio compatibility.

Newly generated bundles use the first 16 lowercase hexadecimal characters of
SHA-256 of this UTF-8 string:

```text
three-part/2:<codec>:<seven PCM digests joined by colons>:<seven table digests joined by colons>
```

`<codec>` is `flac-96k` or `zlib`; both digest lists use the role order above.
The old writer used `three-part/1:` followed by the seven PCM digests only.
Repacking/reuse may choose a fresh opaque bundle ID instead. Readers must not
recompute or require either naming formula: validate the 16-hex shape and indexed
hashes. A changed compression must be published in a new directory so an active
bank is never overwritten.

## Page containers: `OVPGZ003` and `OVPGZ001`

All integers in the header and page table are **big-endian**. Offsets are absolute byte offsets from the start of the `.pgz` file. `OVPGZ003` contains one complete, independent **FLAC** stream per page, including its own `fLaC` marker and metadata. `OVPGZ001` contains one independent **zlib** stream per page. Both are lossless and share the same header/table structure. A `.pgz` file is not directly playable as a conventional FLAC file.

| Header offset | Size | Field |
| ---: | ---: | --- |
| 0 | 8 | ASCII `OVPGZ003` (FLAC) or `OVPGZ001` (zlib) |
| 8 | 4 | Uncompressed bytes per page (`page_bytes`) |
| 12 | 4 | Page count |
| 16 | 8 | Total uncompressed bytes (`frames * 4`) |

The header is 24 bytes. Immediately after it are `page_count` entries of 48 bytes each:

| Entry offset | Size | Field |
| ---: | ---: | --- |
| 0 | 8 | Compressed payload offset |
| 8 | 4 | Compressed payload length |
| 12 | 4 | Expanded page length |
| 16 | 32 | Raw binary SHA-256 of the expanded page |

The index's `<role>_page_table_sha256` is SHA-256 of the exact first `24 + 48 * page_count` **file bytes**, in lowercase hex. The index's `<role>_sha256` is SHA-256 of all expanded PCM bytes, in playback order. Page count is `ceil(total_uncompressed_bytes / page_bytes)`; all but the final page expand to `page_bytes`. The current writer places compressed page payloads consecutively after the table. Current OverCue readers accept at most 4,096 pages per role. At 128 KiB pages and 96 kHz stereo PCM, this caps a role at about 23 minutes.

For FLAC, require the first metadata block to be STREAMINFO (type 0, length 34).
Its rate must be 96,000 Hz, channels 2, bits per sample 16, and total samples must
be the page's expanded length divided by 4. Decode to interleaved signed 16-bit
little-endian stereo with no resampling, gain, or channel conversion. Validate
exact output length and the indexed SHA-256 even when the decoder checks FLAC's
own checksums. Full pages contain 32,768 stereo frames; the last page may be shorter.
The current writer uses fixed-block FLAC and keeps STREAMINFO block-size bounds
at the configured fixed size, even for a short final frame.

FLAC compressed page lengths must be positive and at most expanded page length
plus 65,536 bytes. For legacy zlib, the bound is twice `page_bytes`. Offsets must
start immediately after the table, be contiguous, stay inside the file and end
exactly at EOF. The reference validator bounds decoded FLAC output and execution
time, and checks the same table, page and complete PCM hashes for both codecs.

A reader should validate schema, selected track identity, bundle name, frame count, page count, offsets and lengths, table hash, expanded page length and hash, and the complete role hash before exposing that audio. A real-time reader can verify the table up front and pages as it fetches them; it must use the ordinary full mix until required pages are ready. Invalid, missing, or incomplete stems must leave normal playback available. The included read-only [validator](verify_usb.py) shows the byte-level checks with synthetic tests.

## Writing and compatibility

OverCue Desktop 2.2.0 (Mac) and 2.2.1 (Windows) use FLAC for new stems and
"Repack existing". OverCue firmware 0.10.0 and newer reads both container versions;
0.9.7 and earlier cannot read FLAC stems. Update every player, including linked
players, before using newly prepared or repacked stems. This is the OverCue
sidecar reader's compatibility requirement, separate from native song-file support.

Repacking changes compression only: frame counts, page geometry and expanded PCM
hashes remain unchanged. Header/table hashes change, because the magic, compressed
lengths and offsets change. Write the new bank completely, verify it, then replace
the index atomically. Never relabel zlib as FLAC without encoding the payloads.

OverCue writes only under `/CDJMODS`; it does not alter the exported song, Rekordbox database, or analysis files. A writer should finish and verify every referenced file, then publish `index.json` last through a sibling temporary file and rename. A partially written bundle that is absent from the index must be ignored. Do not derive cross-library matches from numeric IDs alone.

This format describes USB data interchange. It does not grant support for any specific hardware, disclose a stem generation model, define a firmware patch, or specify the optional Rekordbox waveform file internals. A third-party reader can ignore the waveform files and create its own display from the decoded PCM.
