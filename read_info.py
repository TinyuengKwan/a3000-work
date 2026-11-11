#!/usr/bin/env python3
"""Read-only: query ILCE-3000 model code / firmware version via mass-storage extCmd.

No writes, no firmware update. Requires the Sony-PMCA-RE runtime (pyusb + pycryptodomex).
"""
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Sony-PMCA-RE')))

from pmca.commands.usb import importDriver, listDevices, getDevice
from pmca.usb.sony import SonyExtCmdCamera, SonyUpdaterCamera, SonyExtCmdDevice


def main():
    with importDriver('libusb') as driver:
        device = getDevice(driver)
        if not device:
            print('No camera found', file=sys.stderr)
            return 1
        if not isinstance(device, SonyExtCmdDevice):
            print('Wrong device type: %s' % type(device).__name__, file=sys.stderr)
            return 1

        cam = SonyExtCmdCamera(device)
        info = cam.getCameraInfo()
        print('ModelName : %s' % info.modelName)
        print('ModelCode : %s (%d bytes)' % (info.modelCode, len(info.modelCode) // 2))
        print('Serial    : %s' % info.serial)
        print('plist     : %d bytes' % len(info.plist))

        # model code as raw bytes
        raw = bytes.fromhex(info.modelCode)
        print('ModelCode raw bytes : %s' % raw.hex(' '))

        try:
            updater = SonyUpdaterCamera(device)
            updater.init()
            fw_old, fw_new = updater.getFirmwareVersion()
            print('Firmware  : current=%s  update-slot=%s' % (fw_old, fw_new))
        except Exception as e:
            print('Firmware query failed: %r' % e, file=sys.stderr)

        return 0


if __name__ == '__main__':
    sys.exit(main())
