"""Build VM-only artifacts from user-supplied inputs; never modify those inputs."""
from pathlib import Path, PurePosixPath
import argparse
import gzip
import json
import re
import shutil
import stat
import subprocess
import tempfile
import zipfile
from common import ROOT, BUILD, digest, load_config


def read_newc(data):
    records = []
    names = set()
    offset = 0
    while offset + 110 <= len(data):
        header = data[offset:offset + 110]
        if header[:6] not in (b'070701', b'070702'):
            raise ValueError('Expected newc/crc cpio archive.')
        try:
            fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        except ValueError as exc:
            raise ValueError('Invalid cpio header.') from exc
        name_size, file_size = fields[11], fields[6]
        if name_size < 1 or name_size > 4096:
            raise ValueError('Invalid cpio name length.')
        end = offset + 110 + name_size
        raw_name = data[offset + 110:end]
        if len(raw_name) != name_size or raw_name[-1:] != b'\0' or b'\0' in raw_name[:-1]:
            raise ValueError('Invalid cpio entry name.')
        name = raw_name[:-1].decode('utf-8')
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('Unsafe cpio path.')
        normalized = name.removeprefix('./')
        if normalized in names:
            raise ValueError('Duplicate cpio entry: ' + normalized)
        names.add(normalized)
        start = (end + 3) & ~3
        payload = data[start:start + file_size]
        if len(payload) != file_size:
            raise ValueError('Truncated cpio payload.')
        if header[:6] == b'070702' and fields[12] != sum(payload) & 0xffffffff:
            raise ValueError('CPIO payload checksum mismatch.')
        records.append((header, raw_name, payload))
        offset = (start + file_size + 3) & ~3
        if normalized == 'TRAILER!!!':
            if file_size or any(data[offset:]):
                raise ValueError('Unexpected data after cpio trailer.')
            return records
    raise ValueError('Missing cpio trailer.')


def write_newc(records):
    output = bytearray()
    for header, name, payload in records:
        header = bytearray(header)
        header[54:62] = f'{len(payload):08x}'.encode()
        if header[:6] == b'070702':
            header[102:110] = f'{sum(payload) & 0xffffffff:08x}'.encode()
        output.extend(header)
        output.extend(name)
        output.extend(b'\0' * (-len(output) % 4))
        output.extend(payload)
        output.extend(b'\0' * (-len(output) % 4))
    output.extend(b'\0' * (-len(output) % 512))
    return bytes(output)


def patch_init(payload):
    text = payload.decode('utf-8')
    if 'emu-diagnostic' in text or 'GEN5-EMULATOR' in text:
        raise ValueError('Supply an unmodified ramdisk, not an already patched one.')
    blocks = list(re.finditer(r'(?m)^on fs\s*\n', text))
    if len(blocks) != 1:
        raise ValueError('Unsupported init.rc: expected exactly one on fs section.')
    lines = text.splitlines(keepends=True)
    removed = []
    kept = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 4 and parts[:2] == ['mount', 'yaffs2'] and parts[2] in ('mtd@system', 'mtd@userdata', 'mtd@cache'):
            removed.append(parts[2])
        else:
            kept.append(line)
    if sorted(removed) != ['mtd@cache', 'mtd@system', 'mtd@system', 'mtd@userdata']:
        raise ValueError('Unsupported init.rc filesystem layout; original was left unchanged.')
    text = ''.join(kept)
    mounts = ('    wait /dev/block/mmcblk0 15\n'
              '    mount ext4 /dev/block/mmcblk0 /system ro\n'
              '    mount tmpfs tmpfs /data mode=0771,uid=1000,gid=1000\n'
              '    mount tmpfs tmpfs /cache mode=0770,uid=1000,gid=2001\n')
    text = re.sub(r'(?m)^on fs\s*\n', lambda m: m.group(0) + mounts, text, count=1)
    text += '''
# GEN5-EMULATOR: disposable Goldfish guest storage and loopback diagnostics.
on init
    mkdir /mnt/shell/emulated 0700 shell shell
    mount tmpfs tmpfs /mnt/shell/emulated mode=0771,uid=2000,gid=2000
    mkdir /storage/emulated 0755 root root
    mount tmpfs tmpfs /storage/emulated mode=0755,uid=0,gid=0
    mkdir /storage/sdcard1 0777 root root
    mount tmpfs tmpfs /storage/sdcard1 mode=0777,uid=0,gid=0
    export EMULATED_STORAGE_SOURCE /mnt/shell/emulated
    export EMULATED_STORAGE_TARGET /storage/emulated

on property:sys.usb.config=iap2,ncm
    start adbd
on property:sys.usb.config=mtp,adb
    start adbd
on property:sys.boot_completed=1
    start adbd

service emu-diagnostic /system/bin/busybox telnetd -F -b 127.0.0.1 -p 2323 -l /system/bin/sh
    class main
    user root
    group root
'''
    return text.encode('utf-8')


def patch_properties(payload):
    properties = {'ro.secure': '0', 'ro.board.platform': 'goldfish',
                  'misc.configuration.ivimodel': '2', 'misc.configuration.iviplatform': '2',
                  'misc.configuration.market': '2'}
    lines = [line for line in payload.decode('utf-8').splitlines()
             if line.partition('=')[0].strip() not in properties]
    lines.append('# GEN5-EMULATOR: virtual guest only')
    lines.extend(key + '=' + value for key, value in properties.items())
    return ('\n'.join(lines) + '\n').encode('utf-8')


def build_ramdisk(raw):
    if raw.startswith(b'\x1f\x8b'):
        raw = gzip.decompress(raw)
    records = read_newc(raw)
    changed = set()
    for i, (header, name, payload) in enumerate(records):
        path = name[:-1].decode().removeprefix('./')
        if path in ('init.rc', 'default.prop'):
            if not stat.S_ISREG(int(header[14:22], 16)):
                raise ValueError('Expected regular file: ' + path)
            data = patch_init(payload) if path == 'init.rc' else patch_properties(payload)
            records[i] = (header, name, data)
            changed.add(path)
    if changed != {'init.rc', 'default.prop'}:
        raise ValueError('Required ramdisk files are missing.')
    result = write_newc(records)
    read_newc(result)
    return gzip.compress(result, mtime=0)


def prepare(cfg):
    BUILD.mkdir(exist_ok=True)
    inputs = {key: digest(cfg[key]) for key in ('ramdisk_cpio', 'android_jar', 'd8_jar')}
    sources = sorted((ROOT / 'helpers').glob('*.java'))
    if len(sources) != 5:
        raise ValueError('Expected the five source-only helper classes.')
    ramdisk = build_ramdisk(cfg['ramdisk_cpio'].read_bytes())
    with tempfile.TemporaryDirectory(prefix='compile-', dir=BUILD) as work:
        work = Path(work)
        classes, dex = work / 'classes', work / 'dex'
        classes.mkdir(); dex.mkdir()
        # Compile against a disposable copy so JDK archive handling cannot
        # require write access to the user's SDK installation.
        android_jar = work / 'android.jar'
        shutil.copyfile(cfg['android_jar'], android_jar)
        subprocess.run([cfg['javac'], '-encoding', 'UTF-8', '-source', '8', '-target', '8',
                        '-bootclasspath', str(android_jar), '-d', str(classes),
                        *map(str, sources)], check=True)
        compiled = sorted(classes.rglob('*.class'))
        subprocess.run([cfg['java'], '-cp', str(cfg['d8_jar']), 'com.android.tools.r8.D8',
                        '--min-api', '17', '--lib', str(android_jar), '--output', str(dex),
                        *map(str, compiled)], check=True)
        with zipfile.ZipFile(BUILD / 'helpers.jar', 'w', zipfile.ZIP_DEFLATED) as jar:
            jar.write(dex / 'classes.dex', 'classes.dex')
    (BUILD / 'emulator-ramdisk.cpio.gz').write_bytes(ramdisk)
    report = {'inputs': inputs, 'helper_sources': {p.name: digest(p) for p in sources},
              'outputs': {name: digest(BUILD / name) for name in ('helpers.jar', 'emulator-ramdisk.cpio.gz')}}
    (BUILD / 'prepared.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('Prepared VM-only ramdisk and helper JAR in build/. Input files were not modified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='config.local.json')
    args = parser.parse_args()
    try:
        prepare(load_config(args.config))
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + '\n')
