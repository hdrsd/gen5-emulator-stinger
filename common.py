"""Local configuration and isolated runtime paths; no firmware is distributed."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import socket

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / 'build'
RUNTIME = ROOT / 'runtime'
FILE_KEYS = ('emulator', 'kernel', 'system_image', 'ramdisk_cpio',
             'userdata_image', 'android_jar', 'd8_jar')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def load_config(filename='config.local.json'):
    filename = Path(filename).resolve()
    if not filename.is_file():
        raise ValueError('Copy config.example.json to config.local.json and set your local paths.')
    cfg = json.loads(filename.read_text(encoding='utf-8-sig'))
    for key in FILE_KEYS:
        value = cfg.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Missing path: ' + key)
        path = Path(os.path.expandvars(value)).expanduser()
        cfg[key] = (filename.parent / path).resolve() if not path.is_absolute() else path.resolve()
        if not cfg[key].is_file():
            raise ValueError('File not found for ' + key + ': ' + str(cfg[key]))
        if RUNTIME.resolve() in cfg[key].parents or BUILD.resolve() in cfg[key].parents:
            raise ValueError('Inputs must be outside build/ and runtime/: ' + key)
    for key in ('java', 'javac'):
        value = cfg.get(key, key)
        if not isinstance(value, str):
            raise ValueError('Invalid executable: ' + key)
        resolved = shutil.which(value)
        if not resolved:
            path = (filename.parent / os.path.expandvars(value)).resolve()
            if path.is_file():
                resolved = str(path)
        if not resolved:
            raise ValueError('JDK executable not found: ' + key)
        cfg[key] = resolved
    port = cfg.get('port', 5570)
    if type(port) is not int or port % 2 or not 5554 <= port <= 5682:
        raise ValueError('port must be an even number between 5554 and 5682.')
    cfg['port'] = port
    memory = cfg.get('memory_mb', 512)
    if type(memory) is not int or not 256 <= memory <= 2048:
        raise ValueError('memory_mb must be between 256 and 2048.')
    cfg['memory_mb'] = memory
    if type(cfg.get('interactive', True)) is not bool:
        raise ValueError('interactive must be true or false.')
    cfg.setdefault('interactive', True)
    if not (cfg['emulator'].parent / 'emulator-arm.exe').is_file():
        raise ValueError('Use the complete SDK Tools 25.2.5 Windows directory, including emulator-arm.exe.')
    with cfg['system_image'].open('rb') as f:
        f.seek(1024 + 56)
        if f.read(2) != b'\x53\xef':
            raise ValueError('system_image must be a raw ext filesystem image, not sparse or LGK.')
    return cfg


def check_ports(port):
    for number in (port, port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(('127.0.0.1', number))
            except OSError as exc:
                raise ValueError(f'Port {number} is occupied. Close that emulator or change port.') from exc


def verify_prepared(cfg):
    report_path = BUILD / 'prepared.json'
    if not report_path.is_file():
        raise ValueError('Run prepare.py first.')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if set(report.get('outputs', {})) != {'emulator-ramdisk.cpio.gz', 'helpers.jar'}:
        raise ValueError('Incomplete preparation report; run prepare.py again.')
    for key in ('ramdisk_cpio', 'android_jar', 'd8_jar'):
        if digest(cfg[key]) != report['inputs'][key]:
            raise ValueError('Preparation input changed; run prepare.py again: ' + key)
    for name, sha in report['outputs'].items():
        if name not in ('emulator-ramdisk.cpio.gz', 'helpers.jar') or digest(BUILD / name) != sha:
            raise ValueError('Prepared output changed; run prepare.py again.')
    sources = sorted((ROOT / 'helpers').glob('*.java'))
    current = {p.name: digest(p) for p in sources}
    if current != report['helper_sources']:
        raise ValueError('Helper sources changed; run prepare.py again.')


def emulator_command(cfg):
    return [str(cfg['emulator']), '-avd', 'gen5-stinger', '-engine', 'classic',
            '-force-32bit', '-sysdir', str(RUNTIME), '-datadir', str(RUNTIME),
            '-kernel', str(cfg['kernel']), '-ramdisk', str(BUILD / 'emulator-ramdisk.cpio.gz'),
            '-system', str(RUNTIME / 'system.img'), '-initdata', str(cfg['userdata_image']),
            '-data', str(RUNTIME / 'userdata-qemu.img'), '-no-cache', '-no-audio',
            '-no-snapshot', '-no-boot-anim', '-no-jni', '-show-kernel',
            '-memory', str(cfg['memory_mb']), '-gpu', 'off', '-skin', '800x480',
            '-port', str(cfg['port'])]


def stage_runtime(cfg):
    """Copy inputs, refusing to overwrite a previously modified working image."""
    RUNTIME.mkdir(exist_ok=True)
    image = RUNTIME / 'system.img'
    marker = RUNTIME / 'system-source.json'
    expected = digest(cfg['system_image'])
    if image.exists():
        if digest(image) != expected:
            raise ValueError('runtime/system.img differs from the configured input. Move runtime/ aside to start fresh.')
    else:
        pending = RUNTIME / 'system.img.partial'
        if pending.exists():
            raise ValueError('An incomplete copy exists: runtime/system.img.partial. Remove it after checking it is unused.')
        shutil.copyfile(cfg['system_image'], pending)
        if digest(pending) != expected:
            raise ValueError('System image copy verification failed.')
        pending.rename(image)
    marker.write_text(json.dumps({'sha256': expected}, indent=2) + '\n', encoding='utf-8')
    userdata = RUNTIME / 'userdata-qemu.img'
    if not userdata.exists():
        shutil.copyfile(cfg['userdata_image'], userdata)
    home = RUNTIME / 'home'
    avdroot = home / '.android' / 'avd'
    avd = avdroot / 'gen5-stinger.avd'
    avd.mkdir(parents=True, exist_ok=True)
    (avdroot / 'gen5-stinger.ini').write_text(
        'avd.ini.encoding=UTF-8\npath=' + str(avd) + '\ntarget=android-17\n', encoding='utf-8')
    (avd / 'config.ini').write_text(
        'avd.ini.encoding=UTF-8\nAvdId=gen5-stinger\nabi.type=armeabi-v7a\n'
        'hw.cpu.arch=arm\nhw.ramSize=' + str(cfg['memory_mb']) + '\n'
        'hw.mainKeys=yes\nhw.keyboard=yes\nhw.lcd.width=800\nhw.lcd.height=480\n'
        'hw.lcd.density=160\nhw.initialOrientation=landscape\nskin.name=800x480\n'
        'image.sysdir.1=' + str(RUNTIME) + '\n', encoding='utf-8')
    (RUNTIME / 'build.prop').write_text('ro.product.cpu.abi=armeabi-v7a\nro.build.version.sdk=17\n', encoding='ascii')
    env = dict(os.environ)
    env.update(ANDROID_SDK_HOME=str(home), ANDROID_SDK_ROOT=str(cfg['emulator'].parent.parent),
               ANDROID_EMULATOR_HOME=str(home), ANDROID_AVD_HOME=str(avdroot),
               ANDROID_EMULATOR_WAIT_TIME_BEFORE_KILL='1')
    return env
