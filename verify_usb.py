#!/usr/bin/env python3
"""Read-only reference validator for a prepared OverCue USB bank."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import zlib


ROLES = (
    "vocal", "instrumental", "drums", "harmonics",
    "vocals-drums", "vocals-harmonics", "full-mix",
)
ISOLATED_ROLES = ("vocal", "drums", "harmonics", "full-mix")  # three_part: 2
PAGE_BYTES = 131_072
MAX_PAGES = 4096
INDEX_MAX = 256 * 1024 * 1024
LEGACY_INDEX_MAX = 4 * 1024 * 1024
# Paged container magic accepted for each prepared sample rate.
MAGIC = {96000: (b"OVPGZ001", b"OVPGZ003"), 44100: (b"OVPGZ004",)}
V2_MARKER = b"OCSIDX02"
V2_BUCKET = b"OCSIBK02"
V2_RECORD_MAX = 8192


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(entry, key):
    value = entry.get(key)
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            f"invalid {key}")
    return value


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON member")
        result[key] = value
    return result


def wav_header(pcm_bytes):
    return struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + pcm_bytes, b"WAVE",
                       b"fmt ", 16, 1, 2, 44100, 176400, 4, 16, b"data", pcm_bytes)


def decode_page(compressed, magic, expected_bytes):
    if magic == b"OVPGZ001":
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(compressed, expected_bytes + 1)
        except zlib.error as error:
            raise ValueError("invalid zlib page") from error
        require(decoder.eof and not decoder.unconsumed_tail and
                not decoder.unused_data and len(raw) == expected_bytes,
                "invalid zlib page length or trailing data")
        return raw

    rate = 44100 if magic == b"OVPGZ004" else 96000
    # Validate STREAMINFO before invoking a decoder; never resample or remix.
    require(len(compressed) >= 42 and compressed[:4] == b"fLaC" and
            compressed[4] & 0x7f == 0 and compressed[5:8] == b"\x00\x00\x22",
            "invalid FLAC STREAMINFO")
    info = int.from_bytes(compressed[18:26], "big")
    require(info >> 44 == rate and (info >> 41) & 7 == 1 and
            (info >> 36) & 31 == 15 and
            info & ((1 << 36) - 1) == expected_bytes // 4,
            f"FLAC must be {rate} Hz, stereo, 16-bit with exact page frame count")
    try:
        result = subprocess.run([
            "ffmpeg", "-v", "error", "-nostdin", "-xerror", "-err_detect", "crccheck+explode",
            "-f", "flac", "-i", "pipe:0", "-map", "0:a:0",
            "-c:a", "pcm_s16le", "-f", "s16le",
            "-fs", str(expected_bytes + 4), "pipe:1",
        ], input=compressed, capture_output=True, timeout=15)
    except FileNotFoundError as error:
        raise ValueError("FLAC validation requires ffmpeg on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("FLAC page decoder timed out") from error
    # -fs bounds output (with at most one decoded packet of overshoot).
    require(result.returncode == 0 and len(result.stdout) == expected_bytes,
            "invalid FLAC page or decoded length")
    return result.stdout


def check_wav(path, entry, role, raw_bytes):
    key = role.replace("-", "_")
    with path.open("rb") as source:
        header = source.read(44)
        require(header == wav_header(raw_bytes) and
                source.seek(0, 2) == 44 + raw_bytes,
                f"{role}: not a canonical 44.1 kHz stereo 16-bit WAV of {raw_bytes} bytes")
        require(hashlib.sha256(header).hexdigest() ==
                digest(entry, f"{key}_page_table_sha256"),
                f"{role}: header checksum mismatch")
        source.seek(44)
        full_hash = hashlib.sha256()
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            full_hash.update(chunk)
    require(full_hash.hexdigest() == digest(entry, f"{key}_sha256"),
            f"{role}: full PCM checksum mismatch")


def check_role(path, entry, role, raw_bytes, rate=96000):
    key = role.replace("-", "_")
    with path.open("rb") as source:
        size = source.seek(0, 2)
        source.seek(0)
        header = source.read(24)
        require(len(header) == 24 and header[:8] in MAGIC[rate],
                f"{role}: invalid header for {rate} Hz")
        page_bytes, count, total = struct.unpack(">IIQ", header[8:])
        require(page_bytes == PAGE_BYTES and total == raw_bytes and
                0 < count <= MAX_PAGES and count == (total + page_bytes - 1) // page_bytes,
                f"{role}: invalid size or page count")
        table_end = 24 + count * 48
        table = source.read(count * 48)
        require(len(table) == count * 48 and size >= table_end,
                f"{role}: truncated table")
        require(hashlib.sha256(header + table).hexdigest() ==
                digest(entry, f"{key}_page_table_sha256"),
                f"{role}: table checksum mismatch")

        full_hash = hashlib.sha256()
        next_offset = table_end
        for number in range(count):
            offset, compressed_bytes, expanded_bytes = struct.unpack_from(
                ">QII", table, number * 48)
            expected_bytes = min(page_bytes, total - number * page_bytes)
            limit = page_bytes * 2 if header[:8] == b"OVPGZ001" else expected_bytes + 65536
            require(offset == next_offset and 0 < compressed_bytes <= limit and
                    expanded_bytes == expected_bytes and
                    compressed_bytes <= size - offset,
                    f"{role}: invalid page {number} bounds")
            source.seek(offset)
            compressed = source.read(compressed_bytes)
            raw = decode_page(compressed, header[:8], expected_bytes)
            require(hashlib.sha256(raw).digest() == table[number * 48 + 16:number * 48 + 48],
                    f"{role}: page {number} checksum mismatch")
            full_hash.update(raw)
            next_offset += compressed_bytes
        require(next_offset == size, f"{role}: trailing data")
        require(full_hash.hexdigest() == digest(entry, f"{key}_sha256"),
                f"{role}: full PCM checksum mismatch")


def namespaces(index):
    """Return {1: Device Library (export.pdb) map, 2: OneLibrary map}."""
    keying = index.get("keyed_by")
    require(keying in (None, "export.pdb", "exportLibrary.db"), "unknown keyed_by")
    if keying == "exportLibrary.db":
        require(not ("tracks" in index and "tracks_onelibrary" in index),
                "ambiguous OneLibrary maps")
        return {1: {}, 2: index.get("tracks_onelibrary", index.get("tracks", {}))}
    return {1: index.get("tracks", {}), 2: index.get("tracks_onelibrary", {})}


def v2_record(lib, key, entry):
    """The exact index-v2 record bytes a publisher derives from an index.json entry."""
    keep = {k: v for k, v in entry.items()
            if k in ("bundle", "frames", "three_part", "page_bytes") or k.endswith("_sha256")}
    envelope = {"schema": "overcue-index/1",
                "keyed_by": "export.pdb" if lib == 1 else "exportLibrary.db",
                "tracks": {key: keep}}
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def check_index_v2(directory, lib, key):
    """Return the validated index-v2 record for one track, or None if it has none."""
    require(not directory.is_symlink(), "symbolic link in index-v2 path")
    current = (directory / "current").read_bytes()
    require(len(current) == 64 and current[:8] == V2_MARKER and any(current[8:24]) and
            current[24:28] == struct.pack(">I", 1) and
            int.from_bytes(current[28:32], "big") <= 24 and
            hashlib.sha256(current[:32]).digest() == current[32:],
            "index-v2: invalid current marker")
    generation, bits = current[8:24], int.from_bytes(current[28:32], "big")
    track = int(key)
    bucket = ((track * 2654435761) & 0xffffffff) >> (32 - bits) if bits else 0
    namespace = directory / generation.hex() / str(lib)
    require(namespace.is_dir(), "index-v2: missing generation or namespace")
    path = namespace
    for part in (f"{bucket >> 16:02X}", f"{(bucket >> 8) & 255:02X}", f"{bucket & 255:02X}.IDX"):
        path = path / part
        require(not path.is_symlink(), "symbolic link in index-v2 path")
    if not path.exists():
        return None
    data = path.read_bytes()
    require(len(data) >= 96 and data[:8] == V2_BUCKET and data[8:24] == generation and
            not any(data[72:96]), "index-v2: invalid bucket header")
    got_lib, got_bucket, count, size = struct.unpack(">IIII", data[24:40])
    rows = data[96:96 + count * 48]
    require(got_lib == lib and got_bucket == bucket and 1 <= count <= 256 and
            size == len(data) and len(rows) == count * 48 and
            hashlib.sha256(data[:40] + rows).digest() == data[40:72],
            "index-v2: invalid bucket table")
    found, end, previous = None, 96 + count * 48, 0
    for number in range(count):
        row_key, offset, length, flags = struct.unpack_from(">IIII", rows, number * 48)
        record = data[offset:offset + length]
        require(previous < row_key and offset == end and 0 < length <= V2_RECORD_MAX and
                flags == 1 and len(record) == length and
                hashlib.sha256(record).digest() == rows[number * 48 + 16:number * 48 + 48],
                f"index-v2: invalid record {number}")
        if row_key == track:
            found = record
        end, previous = end + length, row_key
    require(end == len(data), "index-v2: unreferenced bucket bytes")
    return found


def verify(root, media_path):
    root = Path(root)
    mods = root / "CDJMODS"
    stems = mods / "stems"
    index_path = mods / "index.json"
    require(not any(path.is_symlink() for path in (mods, stems, index_path)),
            "symbolic link in CDJMODS path")
    require(index_path.stat().st_size <= INDEX_MAX, "index exceeds 256 MiB")
    index = json.loads(index_path.read_bytes(), object_pairs_hook=unique)
    require(isinstance(index, dict), "index is not an object")
    require(index.get("schema") == "overcue-index/1", "unknown index schema")
    maps = namespaces(index)
    require(all(isinstance(table, dict) for table in maps.values()), "invalid track map")
    require(all(isinstance(entry, dict) for table in maps.values() for entry in table.values()),
            "invalid track entry")
    matches = [(lib, key, entry) for lib, table in maps.items()
               for key, entry in table.items()
               if entry.get("file_path") == media_path]
    # Namespaces can differ in advisory fields; their binding metadata must agree.
    require(matches and len({v2_record(1, "1", entry) for _, _, entry in matches}) == 1,
            "track missing or ambiguous")
    entry = matches[0][2]
    bundle = entry.get("bundle")
    frames = entry.get("frames")
    rate = entry.get("sample_rate", 96000)
    wav = entry.get("page_codec") == "wav-44k1"
    require(isinstance(bundle, str) and re.fullmatch(r"[0-9a-f]{16}", bundle),
            "invalid bundle name")
    require(type(frames) is int and 0 < frames <= MAX_PAGES * PAGE_BYTES // 4 and
            entry.get("three_part") in (1, 2) and entry.get("page_bytes") == PAGE_BYTES and
            rate in MAGIC and (not wav or rate == 44100),
            "unsupported audio layout")
    if "source_sha256" in entry:
        parts = media_path.split("/")
        require(len(parts) > 1 and parts[0] == "" and
                all(part not in ("", ".", "..") for part in parts[1:]),
                "invalid source path")
        source = root
        for part in parts[1:]:
            source = source / part
            require(not source.is_symlink(), "symbolic link in source path")
        source_hash = hashlib.sha256()
        with source.open("rb") as audio:
            for chunk in iter(lambda: audio.read(1024 * 1024), b""):
                source_hash.update(chunk)
        require(source_hash.hexdigest() == digest(entry, "source_sha256"),
                "source checksum mismatch")
    directory = stems / bundle
    require(not directory.is_symlink(), "symbolic link in bundle path")
    for role in ROLES if entry["three_part"] == 1 else ISOLATED_ROLES:
        path = directory / f"stems-sidecar-{role}.s16le.{'wav' if wav else 'pgz'}"
        require(not path.is_symlink(), f"{role}: symbolic link")
        if wav:
            check_wav(path, entry, role, frames * 4)
        else:
            check_role(path, entry, role, frames * 4, rate)
    v2 = mods / "index-v2"
    if v2.exists():
        for lib, key, entry in matches:
            require(check_index_v2(v2, lib, key) == v2_record(lib, key, entry),
                    f"index-v2 disagrees with index.json for namespace {lib} track {key}; "
                    "use Repair stems index")
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usb_root", type=Path)
    parser.add_argument("media_path", help="exact file_path from CDJMODS/index.json")
    args = parser.parse_args()
    try:
        bundle = verify(args.usb_root, args.media_path)
    except (OSError, ValueError, KeyError, TypeError, zlib.error) as error:
        parser.exit(1, f"verification failed: {error}\n")
    mods = args.usb_root / "CDJMODS"
    print(f"verified bundle {bundle}" +
          (" and its index-v2 records" if (mods / "index-v2").exists() else ""))
    if (mods / "index.json").stat().st_size > LEGACY_INDEX_MAX:
        print("note: index.json exceeds 4 MiB; only index-v2 readers can load this USB's stems")
