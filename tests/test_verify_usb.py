import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from verify_usb import ROLES, verify


class VerifyUsbTest(unittest.TestCase):
    def test_synthetic_bank_and_corrupted_page(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = "0123456789abcdef"
            directory = root / "CDJMODS" / "stems" / bundle
            directory.mkdir(parents=True)
            audio = root / "Contents" / "synthetic.wav"
            audio.parent.mkdir()
            audio.write_bytes(b"synthetic original music")
            entry = {
                "bundle": bundle, "file_path": "/Contents/synthetic.wav",
                "frames": 8, "three_part": 1, "page_bytes": 131072,
                "source_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
            }
            for role in ROLES:
                raw = struct.pack("<16h", *range(16))
                compressed = zlib.compress(raw)
                table = (b"OVPGZ001" + struct.pack(">IIQ", 131072, 1, len(raw)) +
                         struct.pack(">QII", 72, len(compressed), len(raw)) +
                         hashlib.sha256(raw).digest())
                key = role.replace("-", "_")
                entry[f"{key}_sha256"] = hashlib.sha256(raw).hexdigest()
                entry[f"{key}_page_table_sha256"] = hashlib.sha256(table).hexdigest()
                (directory / f"stems-sidecar-{role}.s16le.pgz").write_bytes(table + compressed)
            (root / "CDJMODS" / "index.json").write_text(json.dumps({
                "schema": "overcue-index/1", "keyed_by": "export.pdb",
                "tracks": {"1": entry}, "tracks_onelibrary": {"2": entry},
            }))
            self.assertEqual(verify(root, "/Contents/synthetic.wav"), bundle)
            path = directory / "stems-sidecar-vocal.s16le.pgz"
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                verify(root, "/Contents/synthetic.wav")


if __name__ == "__main__":
    unittest.main()
