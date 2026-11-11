#!/usr/bin/env python3
"""Confirm candidate model 0x31030024 for ILCE-3000.

Re-send checkGuard for 0x31030024 and its neighbors, capturing the FULL status
list, to distinguish 'Invalid model' (0x140) from 'Low battery' (0x100) and to
see exactly where validation stops.
"""
import sys, os, io, struct, zlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Sony-PMCA-RE')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'a7c2-tools', 'src', 'desktopapp', 'vendor')))

from fwtool.sony import fdat, constants
from pmca.commands.usb import importDriver, getDevice
from pmca.usb.sony import SonyUpdaterCamera, SonyExtCmdDevice

PMCA = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Sony-PMCA-RE'))
DAT_PATH = os.path.join(PMCA, 'updatershell', 'fdat', 'CXD4132.dat')


def build_fdat(model, payload):
    crypter = fdat.AesCrypter(constants.key_cxd4132)
    ref_enc = open(os.path.join(PMCA, 'updatershell', 'fdat', 'CXD4132', 'NEX-3N.hdr'), 'rb').read()
    ref_dec = bytearray(crypter.decryptBlock(ref_enc))
    struct.pack_into('<I', ref_dec, 40, model)
    csum = zlib.crc32(bytes(ref_dec[12:48])) & 0xffffffff
    struct.pack_into('<I', ref_dec, 12, csum)
    new_enc = crypter.encryptBlock(bytes(ref_dec))
    return new_enc + payload


def main():
    payload = open(DAT_PATH, 'rb').read()
    with importDriver('libusb') as driver:
        device = getDevice(driver)
        if not isinstance(device, SonyExtCmdDevice):
            print('Wrong device', file=sys.stderr)
            return 1
        upd = SonyUpdaterCamera(device)

        for model in [0x31030022, 0x31030023, 0x31030024, 0x31030025, 0x31030026, 0x32030024]:
            fd = build_fdat(model, payload)
            # check battery state via getState first
            try:
                st = upd.getState()
                print('getState=%d (before checkGuard)' % st)
            except Exception as e:
                print('getState -> %r' % str(e))
            try:
                upd.init()
                upd.checkGuard(io.BytesIO(fd), len(fd))
                print('model=0x%08x -> ACCEPTED' % model)
            except Exception as e:
                print('model=0x%08x -> %r' % (model, str(e)))
        return 0


if __name__ == '__main__':
    sys.exit(main())
