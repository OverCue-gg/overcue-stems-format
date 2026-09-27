#!/usr/bin/env python3
"""Read-only reference validator for a current seven-role OverCue USB bank."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib


ROLES = (
    "vocal", "instrumental", "drums", "harmonics",
    "vocals-drums", "vocals-harmonics", "full-mix",
)
PAGE_BYTES = 131_072
MAX_PAGES = 4096


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(entry, key):
    value = entry.get(key)
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value),
            f"invalid {key}")
    return value


def check_role(path, entry, role, raw_bytes):
    key = role.replace("-", "_")
    with path.open("rb") as source:
        size = source.seek(0, 2)
        source.seek(0)
        header = source.read(24)
        require(len(header) == 24 and header[:8] == b"OVPGZ001",
                f"{role}: invalid header")
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
            require(offset == next_offset and 0 < compressed_bytes <= page_bytes * 2 and
                    expanded_bytes == expected_bytes and
                    compressed_bytes <= size - offset,
                    f"{role}: invalid page {number} bounds")
            source.seek(offset)
            compressed = source.read(compressed_bytes)
            decoder = zlib.decompressobj()
            try:
                raw = decoder.decompress(compressed, expected_bytes + 1)
            except zlib.error as error:
                raise ValueError(f"{role}: invalid page {number} data") from error
            require(decoder.eof and not decoder.unconsumed_tail and
                    not decoder.unused_data and len(raw) == expected_bytes,
                    f"{role}: invalid page {number} data")
            require(hashlib.sha256(raw).digest() == table[number * 48 + 16:number * 48 + 48],
                    f"{role}: page {number} checksum mismatch")
            full_hash.update(raw)
            next_offset += compressed_bytes
        require(next_offset == size, f"{role}: trailing data")
        require(full_hash.hexdigest() == digest(entry, f"{key}_sha256"),
                f"{role}: full PCM checksum mismatch")


def verify(root, media_path):
    root = Path(root)
    mods = root / "CDJMODS"
    stems = mods / "stems"
    index_path = mods / "index.json"
    require(not any(path.is_symlink() for path in (mods, stems, index_path)),
            "symbolic link in CDJMODS path")
    require(index_path.stat().st_size <= 4 * 1024 * 1024, "index exceeds 4 MiB")
    index = json.loads(index_path.read_bytes())
    require(isinstance(index, dict), "index is not an object")
    require(index.get("schema") == "overcue-index/1", "unknown index schema")
    maps = [index.get(name, {}) for name in ("tracks", "tracks_onelibrary")]
    require(all(isinstance(table, dict) for table in maps), "invalid track map")
    require(all(isinstance(entry, dict) for table in maps for entry in table.values()),
            "invalid track entry")
    matches = [entry for table in maps
               for entry in table.values()
               if entry.get("file_path") == media_path]
    require(matches and all(entry == matches[0] for entry in matches),
            "track missing or ambiguous")
    entry = matches[0]
    bundle = entry.get("bundle")
    frames = entry.get("frames")
    require(isinstance(bundle, str) and re.fullmatch(r"[0-9a-f]{16}", bundle),
            "invalid bundle name")
    require(type(frames) is int and 0 < frames <= MAX_PAGES * PAGE_BYTES // 4 and
            entry.get("three_part") == 1 and entry.get("page_bytes") == PAGE_BYTES,
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
    for role in ROLES:
        path = directory / f"stems-sidecar-{role}.s16le.pgz"
        require(not path.is_symlink(), f"{role}: symbolic link")
        check_role(path, entry, role, frames * 4)
    return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("usb_root", type=Path)
    parser.add_argument("media_path", help="exact file_path from CDJMODS/index.json")
    args = parser.parse_args()
    try:
        print(f"verified seven roles in bundle {verify(args.usb_root, args.media_path)}")
    except (OSError, ValueError, KeyError, TypeError, zlib.error) as error:
        parser.exit(1, f"verification failed: {error}\n")
