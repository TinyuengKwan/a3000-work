#!/usr/bin/env python3
"""Build a byte-correct ILCE-3000 FDAT using fwtool writeFdat/encryptFdat.

Steps:
1. Decrypt the shipped CXD4132 payload (NEX-3N.hdr + CXD4132.dat) to get the
   cramfs filesystem containing libupdaterbody.so.
2. Rebuild the FDAT with model=0x31030024 using fdat.writeFdat + encryptFdat,
   so ALL checksums (header CRC32 + block wrappers) are correct.
3. Split into the 48-byte header and the payload, matching pack.py's layout,
   and write ILCE-3000.hdr + a verified payload.
"""
import sys, os, io

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'a7c2-tools', 'src', 'desktopapp', 'vendor')))

from fwtool.sony import fdat, constants

PMCA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Sony-PMCA-RE'))
FDAT_DIR = os.path.join(PMCA, 'updatershell', 'fdat', 'CXD4132')

MODEL = 0x31030024
REGION = 0
HEADER_SIZE = 0x30  # 48


def main():
    # 1) decrypt shipped NEX-3N FDAT to extract the cramfs
    crypter = fdat.AesCrypter(constants.key_cxd4132)
    ref_full = (open(os.path.join(FDAT_DIR, 'NEX-3N.hdr'), 'rb').read()
                + open(os.path.join(FDAT_DIR, '..', 'CXD4132.dat'), 'rb').read())
    ref_dec = crypter.decrypt(io.BytesIO(ref_full)).read()
    ref = fdat.readFdat(io.BytesIO(ref_dec))
    ref.fs.seek(0)
    fsdata = ref.fs.read()
    print('extracted cramfs: %d bytes' % len(fsdata))

    # 2) rebuild FDAT with new model
    out = io.BytesIO()
    fdat.writeFdat(fdat.FdatFile(
        model=MODEL, region=REGION, version='9.99',
        isAccessory=False, firmware=io.BytesIO(), fs=io.BytesIO(fsdata),
    ), out)

    enc = fdat.encryptFdat(out, 'CXD4132').read()
    print('encrypted FDAT: %d bytes' % len(enc))

    # 3) split header (48) + payload
    hdr = enc[:HEADER_SIZE]
    payload = enc[HEADER_SIZE:]

    hdr_path = os.path.join(FDAT_DIR, 'ILCE-3000.hdr')
    with open(hdr_path, 'wb') as f:
        f.write(hdr)
    print('wrote %s (%d bytes)' % (hdr_path, len(hdr)))

    # Verify: the payload should match the shipped CXD4132.dat (same FS,
    # same encryption since model only affects the header block).
    shipped_payload = open(os.path.join(FDAT_DIR, '..', 'CXD4132.dat'), 'rb').read()
    print('payload matches shipped CXD4132.dat: %s' % (payload == shipped_payload))

    # Round-trip verify our header: decrypt+unpack the full FDAT
    verify = crypter.decrypt(io.BytesIO(enc)).read()
    vf = fdat.readFdat(io.BytesIO(verify))
    print('round-trip: model=0x%08x region=%d version=%s (expect model=0x%08x)'
          % (vf.model, vf.region, vf.version, MODEL))
    assert vf.model == MODEL
    assert vf.region == REGION
    assert vf.version == '9.99'
    print('OK')


if __name__ == '__main__':
    sys.exit(main())
