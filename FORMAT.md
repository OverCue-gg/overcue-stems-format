# OverCue prepared-stems USB format

Status: current layout, checked against Desktop 2.2.40 (Mac) / 2.2.41 (Windows) and OverCue firmware 0.14.0. The JSON schema string is `overcue-index/1`. New CDJ-3000 entries have `three_part: 2` (four audio files); older seven-file entries have `three_part: 1` and remain valid. `/CDJMODS/index-v2` is a bounded binary lookup derived from `index.json`; see [Bounded index](#bounded-index-index-v2). The timing corrections below were confirmed on a CDJ-3000 for the reported files; they do not qualify every source or hardware implementation. This document covers prepared media only. It does not specify how stems are separated or how a player mod is installed.

## Directory and track identity

```text
USB root/
  Contents/...                         original exported music, unchanged
  CDJMODS/
    index.json                          complete inventory, published after the bundle files
    index-v2/                           bounded lookup derived from index.json
      current                           active generation marker, replaced last
      <generation>/1/AA/BB/CC.IDX       Device Library (export.pdb) buckets
      <generation>/2/AA/BB/CC.IDX       OneLibrary (exportLibrary.db) buckets
    stems/<bundle>/
      stems-sidecar-vocal.s16le.pgz
      stems-sidecar-drums.s16le.pgz
      stems-sidecar-harmonics.s16le.pgz
      stems-sidecar-full-mix.s16le.pgz
      stems-sidecar-instrumental.s16le.pgz       three_part: 1 only
      stems-sidecar-vocals-drums.s16le.pgz       three_part: 1 only
      stems-sidecar-vocals-harmonics.s16le.pgz   three_part: 1 only
      overcue-manifest.json             advisory metadata
      stems-*-waveform.EXT / .2EX      optional player-specific analysis
```

The current CDJ-3000 writer produces FLAC-paged `.pgz` files (`OVPGZ003`); legacy files use zlib pages (`OVPGZ001`). The extension is unchanged and the file magic selects the decoder; uncompressed `.s16le` copies are **not** required. The experimental CDJ-2000 profiles use `OVPGZ004` pages or plain `.wav` roles; see [below](#experimental-cdj-2000-profiles-cdj2000-44k11). A bundle name is exactly 16 lowercase hexadecimal characters. Readers must treat index strings as untrusted input and must never let them escape the USB root.

OverCue firmware before 0.14.0 reads at most 4 MiB of `/CDJMODS/index.json`. Desktop 2.2.40 (Mac) / 2.2.41 (Windows) allow it to grow to 256 MiB and never truncate it to fit; a larger index is readable only through `index-v2`, and the app tells the user when older firmware can no longer read a USB's stems.

The index is UTF-8 JSON without duplicate object members. Its relevant shape is:

```json
{
  "schema": "overcue-index/1",
  "keyed_by": "export.pdb",
  "tracks": {
    "123": {
      "bundle": "0123456789abcdef",
      "file_path": "/Contents/Artist/Track.mp3",
      "frames": 960960,
      "three_part": 2,
      "page_bytes": 131072,
      "page_codec": "flac-96k",
      "source_timing_policy": "native-mp3-header/2",
      "source_sha256": "<SHA-256 of the original music file>",
      "source_size": 7340032,
      "source_modified_ns": 1793318400000000000,
      "vocal_sha256": "<SHA-256 of expanded vocal PCM>",
      "vocal_page_table_sha256": "<SHA-256 of vocal header and page table>",
      "drums_sha256": "<SHA-256 of expanded drums PCM>",
      "drums_page_table_sha256": "<SHA-256 of drums header and page table>",
      "harmonics_sha256": "<SHA-256 of expanded harmonics PCM>",
      "harmonics_page_table_sha256": "<SHA-256 of harmonics header and page table>",
      "full_mix_sha256": "<SHA-256 of expanded full-mix PCM>",
      "full_mix_page_table_sha256": "<SHA-256 of full-mix header and page table>"
    }
  },
  "tracks_onelibrary": {}
}
```

Digest placeholders above stand for 64 lowercase hexadecimal characters, not literal values. A `three_part: 1` entry additionally carries `instrumental_sha256`, `vocals_drums_sha256`, `vocals_harmonics_sha256` and their `<role>_page_table_sha256` digests; a `three_part: 2` entry has none of them. `frames` counts stereo PCM frames **including** leading silence. Each role expands to exactly `frames * 4` bytes. `page_bytes` is the uncompressed page size; current writers use 131,072 bytes. All roles of an entry share one bundle, frame count, and page size.

`tracks` keys are decimal Device Library (`export.pdb`) track IDs. `tracks_onelibrary` keys are decimal OneLibrary (`exportLibrary.db`) content IDs. These are separate number spaces: an equal number does not imply an equal song. (An index with `keyed_by: "exportLibrary.db"` and only a `tracks` map is an older OneLibrary-keyed form; treat that `tracks` map as OneLibrary.) `file_path` is the exported music path relative to the USB root, with a leading `/`. OverCue joins the two maps by that exact path. A project with a different library can search entries by `file_path` and reject ambiguous matches; if its loaded-track path differs, it must establish a trustworthy mapping. If `source_sha256` is present, checking the original music file against it provides an additional identity check.

`source_size` and `source_modified_ns` record the original file's size and modification time (nanoseconds since the Unix epoch) when `source_sha256` was taken. Desktop uses them to avoid re-reading unchanged sources; they are not an identity check. Compare only binding fields when checking that a song's Device Library and OneLibrary entries agree.

`page_codec` is advisory metadata: `flac-96k` for FLAC and `zlib` for legacy pages. Older entries may omit it. Read and validate each file magic rather than selecting a decoder from the extension or metadata. Unsupported magic (including `OVPGZ002`) must be rejected.

Entries can contain `title`, `separation`, `loudness_policy`, and other metadata; the top-level index can contain `updated`. A reader does not need to interpret them to decode the audio. Unknown fields must not change the meaning of the required fields.

## Audio roles

Each file is a complete stereo selection, already prepared at **96,000 frames/second** (the CDJ-3000 profile), signed 16-bit little-endian PCM, interleaved left then right. All files of a bank have the same frame count and start position.

| Role in filename | Audio selection | Stored |
| --- | --- | --- |
| `vocal` | Vocals | always |
| `drums` | Drums | always |
| `harmonics` | Non-vocal, non-drum instruments | always |
| `full-mix` | Prepared copy of the original full mix | always |
| `instrumental` | Drums plus harmonics; everything except vocals | `three_part: 1` only |
| `vocals-drums` | Vocals plus drums | `three_part: 1` only |
| `vocals-harmonics` | Vocals plus harmonics | `three_part: 1` only |

A `three_part: 2` bank stores only the four isolated roles. A reader that plays a pair forms it by adding the two isolated roles sample by sample at their stored levels (drums plus harmonics for `instrumental`), saturating to 16 bits; no further gain is applied. The writer still computes the pairs to choose the common headroom, so these sums are already accounted for. OverCue firmware 0.13.1 and later forms the pairs this way for both layouts and does not read pair files. Do not mix `full-mix` with the stems.

The writer resamples, applies a common headroom gain and any downward loudness trims, and prepends silence to restore source time omitted during decoding (see below). It then pads roles to equal length. These processing choices affect the bytes and are already reflected in the indexed hashes; a reader plays the stored PCM and does not reapply them. `overcue-manifest.json` records `runtime.latency_pad_frames`, the source codec/rate, and per-role metadata for diagnostics. The pad describes the writer's source timing, **not** a universal player latency offset. A hardware implementation must align the sidecars with its own full-mix decode and test seeks, loops, tempo changes, and fallback before claiming audio compatibility.

### Source timing and regeneration

Each new entry records `source_timing_policy`, repeated in the manifest as `runtime.source_timing_policy`. It is metadata, not a new index schema or page-container version. Readers can ignore it for byte decoding; a missing or unknown value does not establish whether a bank matches the native player's source timeline. `runtime.latency_pad_frames` counts the total leading silence in **output-rate stereo frames**, not source-rate frames or milliseconds.

| Policy | Written by | Leading silence restored before the decoded audio |
| --- | --- | --- |
| `native-mp3-header/2` | Desktop 2.2.40 (Mac) / 2.2.41 (Windows) and later, CDJ-3000 profile | Declared encoder delay trimmed by the decoder, plus a skipped initial Info/Xing/VBRI MPEG frame **unless** that frame's LAME extension names an ffmpeg encoder (`Lavc`/`Lavf`) |
| `native-mp3-header/1` | Desktop 2.2.5 (Mac) / 2.2.6 (Windows) until `/2` | Declared encoder delay plus the skipped metadata frame for every tagged MP3 |
| `decoded-timeline/1` | Experimental CDJ-2000 profiles | None; `latency_pad_frames` is 0 |

The decoder used by Desktop (Symphonia) omits an MP3's initial metadata frame. rekordbox retains that frame on the analysis timeline of LAME-tagged files, but analyses ffmpeg-tagged files (for example recent Beatport downloads) from the declared delay alone. The beat grid follows that analysis timeline, so `/1` banks of ffmpeg-tagged MP3s play one MPEG frame (1,152 source frames, about 26 ms at 44.1 kHz) behind the full mix and grid. Neither policy adds an assumed delay to untagged audio that already retains its leading samples. The same leading silence is applied to every role, including the prepared full mix. Since `/2`, Desktop also draws stem waveform files from the same padded timeline as the stem audio; earlier writers drew them early by the pad.

Desktop shows `/1` banks of affected MP3s as **Needs realignment**. **Realign stems** removes the extra frame from every role of ffmpeg-tagged files, moves the detailed stem waveforms onto the audio's timeline, and republishes the index without separating again. Banks older than `/1` whose source is affected show **Needs regeneration**; select them and use **Regenerate & Package on USB**. Unaffected source formats and untagged MP3s do not need either action solely because the field is absent or older. If the app cannot inspect a source, it does not trust the old bank for reuse. Updating the app alone does not rewrite prepared media, and compression-only repacking keeps the old timeline.

Equal role lengths and passing hashes establish bank consistency, not native full-mix alignment. The reference validator checks the indexed bytes; it does not measure playback timing or decide whether a bank needs realignment or regeneration. Physical confirmation covers a CDJ-3000 only; another player can place the same files differently on its own timeline, so third-party hardware must compare its own native source decode with the prepared timeline. The policy is not a universal latency adjustment to apply again at playback.

The bundle name is opaque. Writers derive it from the bank's digests or choose a fresh ID when repacking or reusing; readers must not recompute or require any naming formula, only validate the 16-hex shape and indexed hashes. A writer that changes a bank's bytes (compression, layout or timing) publishes the result in a new directory so an active bank is never overwritten.

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

## Experimental CDJ-2000 profiles: `cdj2000-44k1/1`

Desktop's Settings can prepare stems for the CDJ-2000NXS2 (44.1 kHz FLAC, Desktop 2.2.10 Mac / 2.2.11 Windows and later) or the CDJ-2000/2000NXS (44.1 kHz WAV, Desktop 2.2.34 Mac / 2.2.35 Windows and later). These profiles are experimental: they need a matching reader on the player, and hardware compatibility and native timing are not qualified by OverCue. Both store all seven roles (`three_part: 1`) at **44,100 Hz**, two channels, signed 16-bit little-endian PCM, with the same filenames, page size, loudness processing and hash fields as above. Entries add `sample_rate: 44100` and `preparation_profile: "cdj2000-44k1/1"`; the manifest schema is `overcue-stems/5`. Entries without `sample_rate` are the 96 kHz profile. The profiles use `source_timing_policy: "decoded-timeline/1"` and add no leading silence.

- **FLAC, `page_codec: "flac-44k1"`:** the `.pgz` container above with magic **`OVPGZ004`**. STREAMINFO and decoded audio must report 44,100 Hz. Never accept `OVPGZ004` for a 96 kHz entry, or `OVPGZ003`/`OVPGZ001` for a 44.1 kHz entry. One page is 32,768 frames (about 743 ms); the 4,096-page limit allows about 50.7 minutes.
- **WAV, `page_codec: "wav-44k1"`:** each role is `stems-sidecar-<role>.s16le.wav`, exactly the canonical 44-byte header (`RIFF` size `36 + data`, `WAVE`, a 16-byte PCM `fmt ` chunk: format 1, 2 channels, 44,100 Hz, 176,400 bytes/s, block align 4, 16 bits; then `data` and its length) followed by the PCM to end of file, with no other chunks. `<role>_sha256` is the PCM digest; `<role>_page_table_sha256` is SHA-256 of the 44-byte header. A bank holds only `.wav` or only `.pgz` roles.

## Bounded index: `index-v2`

`/CDJMODS/index-v2` lets a reader find one track's binding without loading the whole `index.json`. It is derived entirely from `index.json`, which stays the complete inventory and the index older readers use. OverCue firmware 0.14.0 reads it; earlier firmware ignores it. Desktop 2.2.40 (Mac) / 2.2.41 (Windows) rebuild it with every index change and offer **Upgrade stems index** for USBs that do not have it yet and **Repair stems index** for an interrupted or damaged one. Audio files and their formats are unchanged.

All integers are unsigned big-endian. Namespace `1` is Device Library (`export.pdb`) and `2` is OneLibrary (`exportLibrary.db`).

`index-v2/current` is exactly 64 bytes:

| Offset | Size | Field |
| ---: | ---: | --- |
| 0 | 8 | ASCII `OCSIDX02` |
| 8 | 16 | Generation, nonzero |
| 24 | 4 | Format flags, exactly 1 |
| 28 | 4 | Bucket bits, 0 through 24 |
| 32 | 32 | SHA-256 of bytes 0–31 |

A track's bucket is the high `bits` bits of `(track_id * 2654435761) mod 2^32`, or 0 when `bits` is 0. Its file is `index-v2/<generation as 32 lowercase hex>/<namespace>/AA/BB/CC.IDX`, where `AA`, `BB`, `CC` are the three bytes of the bucket number in uppercase hex. Both namespace directories exist, even when empty. A missing bucket file means that bucket has no entries. Writers choose `bits` so that no bucket has more than 256 rows (OverCue aims for about 128).

A bucket file starts with a 96-byte header:

| Offset | Size | Field |
| ---: | ---: | --- |
| 0 | 8 | ASCII `OCSIBK02` |
| 8 | 16 | Generation, equal to `current` |
| 24 | 4 | Namespace |
| 28 | 4 | Bucket number |
| 32 | 4 | Row count, 1–256 |
| 36 | 4 | Exact file size |
| 40 | 32 | SHA-256 of header bytes 0–39 followed by the complete row table |
| 72 | 24 | Zero |

Rows of 48 bytes follow, in strictly increasing nonzero track-ID order: track ID (4), absolute record offset (4), record length (4, 1–8,192), flags (4, exactly 1) and the record's SHA-256 (32). Records follow the table contiguously, without padding, and end exactly at the file size.

A record is compact UTF-8 JSON (no spaces, non-ASCII escaped) holding that one track's binding fields, copied from `index.json` in their original order: `bundle`, `frames`, `three_part`, `page_bytes` and every field ending in `_sha256`. Titles, paths, the source stamp and processing history are left out. For example:

```json
{"schema":"overcue-index/1","keyed_by":"export.pdb","tracks":{"123":{"bundle":"0123456789abcdef","frames":960960,"three_part":2,"page_bytes":131072,"source_sha256":"…","vocal_sha256":"…","vocal_page_table_sha256":"…"}}}
```

`keyed_by` is `export.pdb` in namespace 1 and `exportLibrary.db` in namespace 2. Because there is no `file_path`, a reader looks a track up by its library ID, then validates the bank through the record's hashes exactly as for an `index.json` entry. A reader should check the marker, the header identity and digest, row order and bounds, and the record digest, and re-read `current` afterwards to make sure the generation did not change while it was reading. A present but incomplete or corrupt `index-v2` must fail closed and not fall back to `index.json`; only a missing `index-v2` directory means the USB is legacy-only.

**Publishing.** A writer builds a complete new generation directory, flushes and reads it back, then replaces `current` last through a temporary file and rename. On a first install it builds the complete tree in a sibling staging directory and renames that to `index-v2` only at the end, so an interrupted first install leaves the USB legacy-only. When `index.json` also changes, Desktop writes `CDJMODS/index-v2-pending` before replacing `index.json` and removes it after activating the new generation; a later publication or Repair rebuilds v2 while that marker exists. It keeps the previous generation for readers that may still hold it and never modifies a live generation. Any change to `index.json` bindings, or a library export that changes track IDs, requires a new generation; v2 cannot detect an externally edited `index.json` on its own.

## Writing and compatibility

| Media | Desktop that writes it | OverCue firmware that reads it |
| --- | --- | --- |
| Seven-role FLAC pages (`OVPGZ003`) | 2.2.0 (Mac) / 2.2.1 (Windows) | 0.10.0 and later |
| Four-file banks (`three_part: 2`) | 2.2.24 (Mac) / 2.2.25 (Windows) | 0.13.1 and later |
| `index-v2`, `index.json` over 4 MiB | 2.2.40 (Mac) / 2.2.41 (Windows) | 0.14.0 and later |

Update every player, including linked players, before using newly prepared, repacked or cleaned-up stems. Firmware 0.9.7 and earlier cannot read FLAC pages. Firmware older than 0.13.1 refuses a `three_part: 2` entry for that track only: it plays the original mix, and other tracks keep their stems. On a USB with seven-role banks, Desktop's **Remove unused files** rewrites those entries to `three_part: 2` first, then deletes the pair audio. These are the OverCue sidecar reader's requirements, separate from native song-file support.

Repacking changes compression only: frame counts, page geometry and expanded PCM hashes remain unchanged. Header/table hashes change, because the magic, compressed lengths and offsets change. Write the new bank completely, verify it, then replace the index atomically. Never relabel zlib as FLAC without encoding the payloads. Repacking never changes the sample rate; the two CDJ-2000 variants can be repacked into each other.

OverCue writes only under `/CDJMODS`; it does not alter the exported song, Rekordbox database, or analysis files. A writer should finish and verify every referenced file, then publish `index.json` through a sibling temporary file and rename, followed by `index-v2` as above. A partially written bundle that is absent from the index must be ignored. Do not derive cross-library matches from numeric IDs alone.

This format describes USB data interchange. It does not grant support for any specific hardware, disclose a stem generation model, define a firmware patch, or specify the optional Rekordbox waveform file internals. A third-party reader can ignore the waveform files and create its own display from the decoded PCM.
