#!/usr/bin/env python3
"""Single-shot firmware dump driver for the Sony ILCE-3000.

Runs the updater-mode exploit and, in the `complete` callback (after the payload
`usbshell_loop` boots), issues dump commands over the USB shell — all in one
process, no interactive stdin needed.

Usage (run with sudo):
  dump_fw.py info                       # uname banner
  dump_fw.py shell '<sh command>'       # run one command in camera sh
  dump_fw.py inventory                  # recon batch -> output/inventory.txt
  dump_fw.py recon3                     # partitions + SD probe -> output/recon3.txt
  dump_fw.py bootloader [outdir]        # dump bootloader blocks
  dump_fw.py pull <src> [local]         # read a regular file (binary-safe)
  dump_fw.py dump <device> <size> <out> # stream a raw partition byte-exactly
"""
import sys, os, io, time, posixpath, socket, threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Sony-PMCA-RE')))

from pmca.commands.usb import importDriver, getDevice, getFdat, firmwareUpdateCommandInternal
from pmca.platform.backend.usb import UsbPlatformBackend, usb_transfer_socket, usb_transfer_read
from pmca.usb.sony import SonyUpdaterDevice, SonyExtCmdDevice

MODEL = 'ILCE-3000'
OUTDIR = os.path.join(os.path.dirname(__file__), 'output')

# Partition sizes in bytes (512-byte sectors from /sys/block/nflasha0/nflasha0pN/size)
PART_SECTORS = {
    'nflasha0p1': 8192,   'nflasha0p2': 6144,   'nflasha0p3': 20480,
    'nflasha0p4': 12288,  'nflasha0p5': 81920,  'nflasha0p6': 10240,
    'nflasha0p7': 71680,  'nflasha0p8': 92160,  'nflasha0p10': 5632,
    'nflasha0p12': 2048,
}

# The actual /dev nodes are nflashaN (N=1..31), not nflasha0pN. Device naming:
#   /dev/nflasha = whole nand, /dev/nflashaN = partition N (major 252 minor N).
# /proc/partitions shows them as nflasha0pN but the block node is nflashaN.
DEV_MAP = {k.replace('nflasha0', 'nflasha'): v for k, v in PART_SECTORS.items()}


def run_shell_command(backend, command, timeout=20):
    out, err = run_shell_commands(backend, [command], timeout)
    return out, err


def run_shell_commands(backend, commands, timeout=20):
    left, right = socket.socketpair()
    backend._req(b'SHEL')
    errbox = {}

    def bridge():
        try:
            usb_transfer_socket(backend.transfer, right)
        except Exception as e:
            errbox['err'] = repr(e)
        finally:
            try:
                right.close()
            except Exception:
                pass

    t = threading.Thread(target=bridge, daemon=True)
    t.start()

    def send_cmds():
        left.settimeout(60)
        time.sleep(1.5)
        for c in commands:
            left.sendall((c + '\n').encode())
            time.sleep(0.3)
        left.sendall(('echo __DONE__\n').encode())
        left.shutdown(socket.SHUT_WR)

    st = threading.Thread(target=send_cmds, daemon=True)
    st.start()

    out = b''
    left.settimeout(timeout)
    try:
        while True:
            chunk = left.recv(65536)
            if not chunk:
                break
            out += chunk
    except socket.timeout:
        pass
    finally:
        try:
            left.close()
        except Exception:
            pass

    t.join(timeout=3)
    st.join(timeout=3)
    return out.decode(errors='replace'), errbox.get('err')


def stream_raw_bytes(backend, shell_cmd, nbytes, timeout=180):
    """Run one shell command and capture exactly nbytes of raw (binary) output.

    Binary-safe. Issues a warm-up echo to flush the shell banner, then the real
    command; reads exactly nbytes and stops (leaves write side open so `sh` does
    not see EOF mid-stream)."""
    left, right = socket.socketpair()
    backend._req(b'SHEL')
    errbox = {}

    def bridge():
        try:
            usb_transfer_socket(backend.transfer, right)
        except Exception as e:
            errbox['err'] = repr(e)
        finally:
            try:
                right.close()
            except Exception:
                pass

    t = threading.Thread(target=bridge, daemon=True)
    t.start()

    # warm-up: consume banner + first prompt
    time.sleep(1.2)
    left.settimeout(12)
    left.sendall(b'echo __READY__\n')
    try:
        banner = b''
        while b'__READY__' not in banner:
            c = left.recv(4096)
            if not c:
                break
            banner += c
    except socket.timeout:
        pass

    # send the streaming command (keep write side open)
    left.sendall((shell_cmd + '\n').encode())

    data = bytearray()
    left.settimeout(90)
    try:
        while len(data) < nbytes:
            chunk = left.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
    except socket.timeout:
        pass
    finally:
        try:
            left.close()
        except Exception:
            pass
    t.join(timeout=3)
    return bytes(data[:nbytes]), errbox.get('err')


def dump_bootloader(backend, outdir):
    os.makedirs(outdir, exist_ok=True)
    n = backend._req(b'BLDR')
    print('[bootloader] %d blocks' % n)
    for i in range(n):
        f = io.BytesIO()
        usb_transfer_read(backend.transfer, f)
        data = f.getvalue()
        path = os.path.join(outdir, 'boot%d.bin' % (i + 1))
        with open(path, 'wb') as out:
            out.write(data)
        print('[bootloader] saved %s (%d bytes)' % (path, len(data)))
    return n


def dump_partition(backend, dev, outpath, explicit_size=None):
    """Dump a raw NAND partition byte-exactly via `cat` + socket, verify md5.

    `dev` may be given as either /dev node name (nflasha12) or /proc name
    (nflasha0p12); both are normalized to the /proc/partitions key.
    """
    norm = dev
    if norm.startswith('nflasha') and 'p' not in norm:
        # nflashaN -> nflasha0pN
        num = norm[len('nflasha'):]
        norm = 'nflasha0p' + num
    sectors = PART_SECTORS.get(norm)
    if sectors is None and explicit_size is not None:
        sectors = explicit_size // 512
    if sectors is None:
        print('[dump] unknown device %s (known: %s)' % (dev, list(PART_SECTORS)))
        return
    size_bytes = sectors * 512

    # camera-side md5 (md5sum works on stdin, not directly on block devices)
    out, _ = run_shell_command(backend, 'cat /dev/%s | md5sum' % dev)
    md5line = out.strip().split('\n')[-1]
    print('[camera md5 %s] %s' % (dev, md5line))

    # raw bytes
    raw, err = stream_raw_bytes(backend, 'cat /dev/%s' % dev, size_bytes, timeout=120)
    os.makedirs(os.path.dirname(outpath) or '.', exist_ok=True)
    with open(outpath, 'wb') as f:
        f.write(raw)
    print('[dump] saved %s (%d bytes, expected %d)' % (outpath, len(raw), size_bytes))
    if err:
        print('[dump] BRIDGE ERR: %s' % err)
    return raw


def dump_partition_chunked(backend, dev, outpath, chunk_bytes=4 * 1024 * 1024, size_bytes=None):
    """Dump a partition/device in small chunks via dd -> tmpfs -> PULL (binary-safe).

    Each chunk is `dd`-ed to /tmp/c (tmpfs) then PULLed with the proven
    usb_transfer_read framing, avoiding the fragile large SHEL socket stream.
    Per-chunk md5 is computed on the camera (md5sum /tmp/c) and matched locally
    for integrity, so we never stream a huge partition through the shell.

    If size_bytes is None, it is looked up from PART_SECTORS by device name.
    """
    norm = dev
    if norm.startswith('nflasha') and 'p' not in norm:
        norm = 'nflasha0p' + norm[len('nflasha'):]
    if size_bytes is None:
        sectors = PART_SECTORS.get(norm)
        if sectors is None:
            print('[dump] unknown device %s' % dev)
            return
        size_bytes = sectors * 512

    os.makedirs(os.path.dirname(outpath) or '.', exist_ok=True)
    total = 0
    offset = 0
    idx = 0
    chunk_md5s = []

    # Resume support: if outpath already has data, skip that many full chunks.
    if os.path.exists(outpath):
        existing = os.path.getsize(outpath)
        if existing > 0 and existing < size_bytes:
            offset = (existing // chunk_bytes) * chunk_bytes
            print('[dump] resuming from offset %d (existing %d bytes)' % (offset, existing))

    with open(outpath, 'r+b' if offset else 'wb') as f:
        if offset:
            f.seek(offset)
        while offset < size_bytes:
            n = min(chunk_bytes, size_bytes - offset)
            skip_blocks = offset // 8192  # dd bs=8192
            count_blocks = (n + 8191) // 8192
            cmd = 'dd if=/dev/%s of=/tmp/c bs=8192 skip=%d count=%d 2>/dev/null; echo chunk_rc=$?' % (
                dev, skip_blocks, count_blocks)
            run_shell_command(backend, cmd)
            # camera md5 of this chunk
            o, _ = run_shell_command(backend, 'md5sum /tmp/c')
            cm = o.strip().split('\n')[-1].split()[0]
            # PULL the chunk
            got = pull_to_bytes(backend, '/tmp/c')
            run_shell_command(backend, 'rm -f /tmp/c')

            # local md5
            import hashlib
            lm = hashlib.md5(got).hexdigest()
            match = (cm and lm == cm)
            chunk_md5s.append((idx, lm, cm, match))

            f.write(got)
            offset += len(got)
            total += len(got)
            idx += 1
            print('[dump %s] chunk %d: +%d bytes (off %d/%d) md5=%s camera=%s %s' % (
                dev, idx, len(got), offset, size_bytes, lm, cm, 'OK' if match else 'MISMATCH'))
            if len(got) < n:
                print('[dump %s] short chunk (%d < %d), stopping' % (dev, len(got), n))
                break

    print('[dump] saved %s (%d bytes, expected %d)' % (outpath, total, size_bytes))
    return total


def pull_to_bytes(backend, path):
    """PULL a file and return its bytes."""
    f = io.BytesIO()
    size = backend._req(b'PULL', path.encode('latin1'))
    usb_transfer_read(backend.transfer, f)
    return f.getvalue()


def do(backend, argv):
    action = argv[0] if argv else 'info'
    if action == 'info':
        out, err = run_shell_command(backend, 'uname -a; echo; cat /proc/version')
        print('=== camera shell ===')
        print(out, end='')
        if err:
            print('BRIDGE ERR: %s' % err)
    elif action == 'shell':
        out, err = run_shell_command(backend, ' '.join(argv[1:]))
        print(out, end='')
        if err:
            print('BRIDGE ERR: %s' % err, file=sys.stderr)
    elif action == 'bootloader':
        dump_bootloader(backend, argv[1] if len(argv) > 1 else OUTDIR)
    elif action == 'pull':
        src = argv[1]
        dst = argv[2] if len(argv) > 2 else os.path.join(OUTDIR, posixpath.basename(src))
        os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
        with open(dst, 'wb') as f:
            backend.readFile(src, f)
        print('[pull] saved %s' % dst)
    elif action == 'inventory':
        cmds = [
            'uname -a',
            'cat /proc/version',
            'cat /proc/partitions',
            'cat /proc/mounts',
            'ls -la /dev | grep -E "nflash|mmcc|sda|loop" ',
        ]
        out, err = run_shell_commands(backend, cmds, timeout=25)
        print(out, end='')
        if err:
            print('BRIDGE ERR: %s' % err, file=sys.stderr)
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, 'inventory.txt'), 'w') as f:
            f.write(out)
        print('\n[saved output/inventory.txt]')
    elif action == 'recon3':
        cmds = [
            'ls /sys/block',
            'for d in /sys/block/*/size; do echo -n "$d: "; cat $d 2>/dev/null; done',
            'ls -la /dev/mmcc* /dev/sd* 2>/dev/null',
            'cat /proc/partitions',
        ]
        out, err = run_shell_commands(backend, cmds, timeout=25)
        print(out, end='')
        if err:
            print('BRIDGE ERR: %s' % err, file=sys.stderr)
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, 'recon3.txt'), 'w') as f:
            f.write(out)
        print('\n[saved output/recon3.txt]')
    elif action == 'dump':
        dev = argv[1]
        outpath = argv[2] if len(argv) > 2 else os.path.join(OUTDIR, dev + '.img')
        dump_partition(backend, dev, outpath)
    elif action == 'dumpbig':
        dev = argv[1]
        outpath = argv[2] if len(argv) > 2 else os.path.join(OUTDIR, dev + '.img')
        dump_partition_chunked(backend, dev, outpath)
    elif action == 'dumpwhole':
        # dump the entire /dev/nflasha (261888 x 1KiB blocks = 268173312 bytes)
        outpath = argv[1] if len(argv) > 1 else os.path.join(OUTDIR, 'nflasha-whole.img')
        dump_partition_chunked(backend, 'nflasha', outpath, size_bytes=261888 * 1024)
    elif action == 'dumpall':
        # dump every known partition in this one session
        os.makedirs(OUTDIR, exist_ok=True)
        manifest = []
        for pname in sorted(PART_SECTORS):
            node = 'nflasha' + pname[len('nflasha0p'):]  # nflasha0p1 -> nflasha1
            outpath = os.path.join(OUTDIR, pname + '.img')
            dump_partition(backend, node, outpath)
            if os.path.exists(outpath):
                import hashlib
                md5 = hashlib.md5(open(outpath, 'rb').read()).hexdigest()
                manifest.append('%s %d %s' % (pname, os.path.getsize(outpath), md5))
        with open(os.path.join(OUTDIR, 'manifest.txt'), 'w') as f:
            f.write('\n'.join(manifest) + '\n')
        print('=== manifest ===')
        print('\n'.join(manifest))
    elif action == 'diagdev':
        # diagnose block device readability
        cmds = [
            'ls -la /dev/nflasha /dev/nflasha12 /dev/nflasha1 2>&1',
            'echo === dd test ===',
            'dd if=/dev/nflasha12 of=/tmp/x.bin bs=512 count=4 2>&1; echo "dd rc=$?"',
            'ls -la /tmp/x.bin 2>&1',
            'md5sum /tmp/x.bin 2>&1',
            'echo === cat test ===',
            'cat /dev/nflasha12 2>&1 | wc -c',
            'echo === block size ===',
            'cat /sys/block/nflasha0/nflasha0p12/size 2>&1; echo',
            'cat /sys/class/block/nflasha0p12/size 2>&1; echo',
        ]
        out, err = run_shell_commands(backend, cmds, timeout=30)
        print(out, end='')
        if err:
            print('BRIDGE ERR: %s' % err, file=sys.stderr)
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, 'diagdev.txt'), 'w') as f:
            f.write(out)
        print('\n[saved output/diagdev.txt]')
    elif action == 'memprobe':
        cmds = [
            'cat /proc/meminfo',
            'df',
            'cat /proc/mounts',
            'ls -la /tmp /ramdsk /var /dev/shm /run 2>&1',
            'df /tmp /ramdsk /var 2>&1',
            'mount',
        ]
        out, err = run_shell_commands(backend, cmds, timeout=25)
        print(out, end='')
        if err:
            print('BRIDGE ERR: %s' % err, file=sys.stderr)
        os.makedirs(OUTDIR, exist_ok=True)
        with open(os.path.join(OUTDIR, 'memprobe.txt'), 'w') as f:
            f.write(out)
        print('\n[saved output/memprobe.txt]')
    else:
        print('unknown action: %s' % action)


def main(argv):
    fdat_bytes = getFdat(MODEL)
    if not fdat_bytes:
        print('Error: no fdat for %s' % MODEL, file=sys.stderr)
        return 1

    with importDriver('libusb') as driver:
        device = getDevice(driver)
        if not device:
            print('No camera found', file=sys.stderr)
            return 1

        def complete(dev):
            print('Payload running; opening USB shell...')
            backend = UsbPlatformBackend(dev)
            backend.start()
            try:
                do(backend, argv)
            finally:
                try:
                    backend.stop()
                except Exception as e:
                    print('[teardown] backend.stop() error (dumps already saved): %r' % e)

        firmwareUpdateCommandInternal(driver, device, io.BytesIO(fdat_bytes), 0, len(fdat_bytes), complete)

    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
