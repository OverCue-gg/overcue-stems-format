import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from verify_usb import PAGE_BYTES, ROLES, decode_page, verify


def encode_flac(raw):
    # A seekable output lets ffmpeg finalize STREAMINFO's exact sample count.
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'page.flac'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-f', 's16le',
            '-ar', '96000', '-ac', '2', '-i', 'pipe:0',
            '-c:a', 'flac', str(path),
        ], input=raw, capture_output=True, check=True, timeout=15)
        return path.read_bytes()


def make_bank(root, magic):
    bundle = '0123456789abcdef'
    directory = root / 'CDJMODS' / 'stems' / bundle
    directory.mkdir(parents=True)
    audio = root / 'Contents' / 'synthetic.wav'
    audio.parent.mkdir()
    audio.write_bytes(b'synthetic original music')
    raw = struct.pack('<h', -1234) * ((PAGE_BYTES + 400) // 2)
    entry = {
        'bundle': bundle, 'file_path': '/Contents/synthetic.wav',
        'frames': len(raw) // 4, 'three_part': 1, 'page_bytes': PAGE_BYTES,
        'source_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
    }
    pages = [raw[i:i + PAGE_BYTES] for i in range(0, len(raw), PAGE_BYTES)]
    encoded = [encode_flac(p) if magic == b'OVPGZ003' else zlib.compress(p)
               for p in pages]
    table = magic + struct.pack('>IIQ', PAGE_BYTES, len(pages), len(raw))
    offset = 24 + len(pages) * 48
    for page, compressed in zip(pages, encoded):
        table += (struct.pack('>QII', offset, len(compressed), len(page)) +
                  hashlib.sha256(page).digest())
        offset += len(compressed)
    for role in ROLES:
        key = role.replace('-', '_')
        entry[f'{key}_sha256'] = hashlib.sha256(raw).hexdigest()
        entry[f'{key}_page_table_sha256'] = hashlib.sha256(table).hexdigest()
        (directory / f'stems-sidecar-{role}.s16le.pgz').write_bytes(
            table + b''.join(encoded))
    (root / 'CDJMODS' / 'index.json').write_text(json.dumps({
        'schema': 'overcue-index/1', 'keyed_by': 'export.pdb',
        'tracks': {'1': entry}, 'tracks_onelibrary': {'2': entry},
    }))
    return bundle, directory


class VerifyUsbTest(unittest.TestCase):
    def check_bank(self, magic):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle, directory = make_bank(root, magic)
            self.assertEqual(verify(root, '/Contents/synthetic.wav'), bundle)
            path = directory / 'stems-sidecar-vocal.s16le.pgz'
            good = path.read_bytes()
            # Include invalid geometry, unknown magic, table tampering, truncation,
            # trailing data and corrupt compressed audio for both codecs.
            bad_payload = bytearray(good)
            bad_payload[-1] ^= 1
            bad_table = bytearray(good)
            bad_table[40] ^= 1
            for bad in [b'OVPGZ002' + good[8:], good[:20], good[:-1],
                        good + b'extra', bad_table, bad_payload]:
                with self.subTest(magic=magic, length=len(bad)):
                    path.write_bytes(bad)
                    with self.assertRaises(ValueError):
                        verify(root, '/Contents/synthetic.wav')

    def test_zlib_bank(self):
        self.check_bank(b'OVPGZ001')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required for FLAC checks')
    def test_flac_bank(self):
        self.check_bank(b'OVPGZ003')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required for FLAC checks')
    def test_flac_streaminfo_and_length(self):
        for frames in [1, 15, 4097]:
            raw = struct.pack('<hh', -32768, 32767) * frames
            encoded = encode_flac(raw)
            self.assertEqual(decode_page(encoded, b'OVPGZ003', len(raw)), raw)
            for byte in [0, 5, 18, 20, 21, 25]:
                bad = bytearray(encoded)
                bad[byte] ^= 1
                with self.assertRaises(ValueError):
                    decode_page(bad, b'OVPGZ003', len(raw))
        # A lying sample count cannot hide an overlong decoded page.
        bad = bytearray(encode_flac(b'\0' * 400))
        info = int.from_bytes(bad[18:26], 'big')
        bad[18:26] = ((info & ~((1 << 36) - 1)) | 1).to_bytes(8, 'big')
        with self.assertRaises(ValueError):
            decode_page(bad, b'OVPGZ003', 4)


if __name__ == '__main__':
    unittest.main()
