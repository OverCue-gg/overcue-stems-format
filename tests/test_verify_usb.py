import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from verify_usb import (ISOLATED_ROLES, PAGE_BYTES, ROLES, decode_page,
                        v2_record, verify, wav_header)


def encode_flac(raw, rate=96000):
    # A seekable output lets ffmpeg finalize STREAMINFO's exact sample count.
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'page.flac'
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-f', 's16le',
            '-ar', str(rate), '-ac', '2', '-i', 'pipe:0',
            '-c:a', 'flac', str(path),
        ], input=raw, capture_output=True, check=True, timeout=15)
        return path.read_bytes()


def make_bank(root, magic, roles=ROLES, rate=96000):
    bundle = '0123456789abcdef'
    directory = root / 'CDJMODS' / 'stems' / bundle
    directory.mkdir(parents=True)
    audio = root / 'Contents' / 'synthetic.wav'
    audio.parent.mkdir()
    audio.write_bytes(b'synthetic original music')
    raw = struct.pack('<h', -1234) * ((PAGE_BYTES + 400) // 2)
    entry = {
        'bundle': bundle, 'file_path': '/Contents/synthetic.wav',
        'frames': len(raw) // 4, 'three_part': 1 if roles == ROLES else 2,
        'page_bytes': PAGE_BYTES,
        'source_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
    }
    if rate != 96000:
        entry.update(sample_rate=rate, preparation_profile='cdj2000-44k1/1',
                     page_codec='wav-44k1' if magic == b'RIFF' else 'flac-44k1')
    if magic == b'RIFF':
        table, payload, suffix = wav_header(len(raw)), raw, 'wav'
    else:
        pages = [raw[i:i + PAGE_BYTES] for i in range(0, len(raw), PAGE_BYTES)]
        encoded = [zlib.compress(p) if magic == b'OVPGZ001' else encode_flac(p, rate)
                   for p in pages]
        table = magic + struct.pack('>IIQ', PAGE_BYTES, len(pages), len(raw))
        offset = 24 + len(pages) * 48
        for page, compressed in zip(pages, encoded):
            table += (struct.pack('>QII', offset, len(compressed), len(page)) +
                      hashlib.sha256(page).digest())
            offset += len(compressed)
        payload, suffix = b''.join(encoded), 'pgz'
    for role in roles:
        key = role.replace('-', '_')
        entry[f'{key}_sha256'] = hashlib.sha256(raw).hexdigest()
        entry[f'{key}_page_table_sha256'] = hashlib.sha256(table).hexdigest()
        (directory / f'stems-sidecar-{role}.s16le.{suffix}').write_bytes(table + payload)
    # The namespaces may differ in advisory fields such as the source stamp.
    stamped = dict(entry, source_size=24, source_modified_ns=1)
    (root / 'CDJMODS' / 'index.json').write_text(json.dumps({
        'schema': 'overcue-index/1', 'keyed_by': 'export.pdb',
        'tracks': {'1': stamped}, 'tracks_onelibrary': {'2': entry},
    }))
    return bundle, directory


def write_index_v2(root):
    """Publish index-v2 from index.json the way OverCue Desktop does (bits = 0)."""
    index = json.loads((root / 'CDJMODS' / 'index.json').read_bytes())
    generation = bytes(range(1, 17))
    v2 = root / 'CDJMODS' / 'index-v2'
    for lib, name in ((1, 'tracks'), (2, 'tracks_onelibrary')):
        bucket = v2 / generation.hex() / str(lib) / '00' / '00'
        bucket.mkdir(parents=True)
        values = sorted((int(k), v2_record(lib, k, e)) for k, e in index[name].items())
        start = 96 + 48 * len(values)
        rows, records = b'', b''
        for key, data in values:
            rows += (struct.pack('>IIII', key, start + len(records), len(data), 1) +
                     hashlib.sha256(data).digest())
            records += data
        head = b'OCSIBK02' + generation + struct.pack(
            '>IIII', lib, 0, len(values), start + len(records))
        (bucket / '00.IDX').write_bytes(
            head + hashlib.sha256(head + rows).digest() + bytes(24) + rows + records)
    marker = b'OCSIDX02' + generation + struct.pack('>II', 1, 0)
    (v2 / 'current').write_bytes(marker + hashlib.sha256(marker).digest())
    return v2 / generation.hex() / '1' / '00' / '00' / '00.IDX'


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

    def test_isolated_bank(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle, directory = make_bank(root, b'OVPGZ001', ISOLATED_ROLES)
            self.assertEqual(verify(root, '/Contents/synthetic.wav'), bundle)
            (directory / 'stems-sidecar-drums.s16le.pgz').unlink()
            with self.assertRaises(OSError):
                verify(root, '/Contents/synthetic.wav')

    def test_wav_bank(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle, directory = make_bank(root, b'RIFF', rate=44100)
            self.assertEqual(verify(root, '/Contents/synthetic.wav'), bundle)
            path = directory / 'stems-sidecar-vocal.s16le.wav'
            good = path.read_bytes()
            bad_pcm = bytearray(good)
            bad_pcm[-1] ^= 1
            for bad in [good[:24] + struct.pack('<I', 48000) + good[28:],
                        good + b'\0\0\0\0', bad_pcm]:
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    verify(root, '/Contents/synthetic.wav')

    def test_index_v2(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle, _ = make_bank(root, b'OVPGZ001', ISOLATED_ROLES)
            bucket = write_index_v2(root)
            self.assertEqual(verify(root, '/Contents/synthetic.wav'), bundle)
            index_path = root / 'CDJMODS' / 'index.json'
            good_index, good_bucket = index_path.read_bytes(), bucket.read_bytes()
            stale = json.loads(good_index)
            stale['tracks']['1']['frames'] -= 1
            corrupt = bytearray(good_bucket)
            corrupt[-2] ^= 1
            for index, data in [(json.dumps(stale).encode(), good_bucket),
                                (good_index, bytes(corrupt)),
                                (good_index, good_bucket + b'x')]:
                index_path.write_bytes(index)
                bucket.write_bytes(data)
                with self.assertRaises(ValueError):
                    verify(root, '/Contents/synthetic.wav')
            bucket.write_bytes(good_bucket)
            (root / 'CDJMODS' / 'index-v2' / 'current').write_bytes(b'OCSIDX02' + bytes(56))
            with self.assertRaises(ValueError):
                verify(root, '/Contents/synthetic.wav')

    def test_zlib_bank(self):
        self.check_bank(b'OVPGZ001')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required for FLAC checks')
    def test_flac_bank(self):
        self.check_bank(b'OVPGZ003')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg required for FLAC checks')
    def test_flac_44k1_bank(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle, directory = make_bank(root, b'OVPGZ004', rate=44100)
            self.assertEqual(verify(root, '/Contents/synthetic.wav'), bundle)
            # A 96 kHz container magic is never accepted for a 44.1 kHz entry.
            path = directory / 'stems-sidecar-vocal.s16le.pgz'
            path.write_bytes(b'OVPGZ003' + path.read_bytes()[8:])
            with self.assertRaises(ValueError):
                verify(root, '/Contents/synthetic.wav')

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
