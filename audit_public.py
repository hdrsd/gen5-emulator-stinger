"""Check the Git index against the explicit source-only publication list."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = '''.gitattributes
.gitignore
README.md
audit_public.py
common.py
config.example.json
launch.py
prepare.py
start.cmd
helpers/BluetoothManagerStub.java
helpers/CameraStub.java
helpers/FastbootStub.java
helpers/MicomSendProxy.java
helpers/NaviConfirmProxy.java
helpers/app-service-start.sh
helpers/camera-watchdog.sh
tests/test_prepare.py'''.splitlines()


def audit():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    actual = {name for name in tracked if name}
    if actual != set(PUBLIC_FILES):
        raise ValueError('Index differs from public allowlist: ' + repr(sorted(actual ^ set(PUBLIC_FILES))))
    total = 0
    for name in sorted(actual):
        data = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
        text = data.decode('utf-8')
        if b'\0' in data or len(data) > 65536:
            raise ValueError('Binary or unexpectedly large file: ' + name)
        patterns = (r'(?i)[A-Z]:[/\\]Users[/\\]',
                    r'(?i)[A-Z]:[/\\]hack[/\\]',
                    r'gh[pousr]_[A-Za-z0-9]{20,}',
                    r'github_pat_[A-Za-z0-9_]{20,}',
                    r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')
        if any(re.search(pattern, text) for pattern in patterns):
            raise ValueError('Possible machine path or secret in: ' + name)
        total += len(data)
    print(f'Public index OK: {len(actual)} UTF-8 source files, {total} bytes.')
    print('No firmware, SDK binaries, local configuration, or runtime files are staged.')


if __name__ == '__main__':
    audit()
