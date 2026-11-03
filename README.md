# gen5-emulator-stinger

Windows에서 Stinger Gen5 Android 사용자 공간을 실행하기 위한 실험용 런처입니다. ARM Goldfish 가상 머신에 사용자가 준비한 시스템 이미지를 연결합니다. Telechips 보드 전체를 에뮬레이션하지 않으므로 실제 헤드유닛의 부팅·USB·CAN 동작을 검증하는 용도로 사용할 수 없습니다.

## 준비물

- Windows 64비트, Python 3.10 이상.
- JDK와 Android SDK의 `android.jar`, D8. 빌드 확인 환경은 JDK 21, Android SDK Platform 34, Build Tools 34.0.0입니다. 생성하는 DEX의 최소 API는 17입니다.
- Windows용 Android SDK Tools 25.2.5의 전체 `tools` 폴더. `emulator.exe`와 `emulator-arm.exe`가 함께 있어야 합니다. 최신 Android Emulator로 교체하는 방식은 지원하지 않습니다.
- ARMv7 Goldfish용 `kernel-qemu-armv7`.
- 호환되는 Gen5 Android 4.2.2 펌웨어의 원본 `SYST.img`와 부트 램디스크. 시스템은 raw ext 이미지, 램디스크는 `newc` CPIO 또는 gzip으로 압축된 CPIO여야 합니다. LGK, Android sparse 이미지, 전체 `boot.img`는 직접 입력할 수 없습니다.
- 초기화용 `userdata.img`. `/data`는 가상 머신에서 tmpfs로 구성되므로 이 이미지에 저장된 데이터는 사용하지 않습니다.
- 첫 실행 시 시스템 이미지와 userdata 사본을 저장할 여유 공간.

펌웨어, 제조사 앱·라이브러리, 커널, SDK 및 실행 바이너리는 포함되어 있지 않습니다. 사용할 권한이 있는 파일을 별도로 준비하세요.

## 설정

저장소 루트에서 PowerShell을 열고 실행합니다.

```powershell
Copy-Item config.example.json config.local.json
```

`config.local.json`의 파일 경로를 본인 환경에 맞게 수정합니다. 상대 경로는 설정 파일의 위치를 기준으로 해석합니다. JSON의 Windows 경로에는 `/` 또는 `\\`를 사용합니다.

| 설정 | 용도 |
| --- | --- |
| `emulator` | 클래식 `emulator.exe` |
| `kernel` | ARMv7 Goldfish 커널 |
| `system_image` | 원본 raw `SYST.img` |
| `ramdisk_cpio` | 수정하지 않은 부트 램디스크 |
| `userdata_image` | 초기화용 userdata 이미지 |
| `android_jar`, `d8_jar` | Java 헬퍼 빌드 의존성 |
| `java`, `javac` | PATH의 명령 이름 또는 JDK 실행 파일 경로 |
| `port` | 사용 중이지 않은 짝수 콘솔 포트. 기본 5570, 다음 포트도 사용 |
| `memory_mb` | 가상 머신 메모리. 기본 512 |
| `interactive` | 누락된 차량 서비스의 UI 호환 처리. 기본 `true` |

입력 파일은 `build/`, `runtime/` 밖에 두세요. `config.local.json`, `inputs/`, `dependencies/`, `build/`, `runtime/`는 Git 추적 대상에서 제외됩니다.

## 실행

```powershell
python launch.py --check
python prepare.py
python launch.py --dry-run
.\start.cmd
```

`--check`는 의존 파일과 이미지 형식을 확인합니다. `prepare.py`는 원본을 수정하지 않고 가상 머신용 램디스크와 헬퍼 JAR을 `build/`에 만듭니다. 지원하지 않는 램디스크 구조는 오류로 중단합니다. `--dry-run`은 준비 결과를 확인하고 실행 명령만 출력합니다.

첫 실행은 시스템 이미지를 `runtime/`에 복사하므로 시간이 걸릴 수 있습니다. 이후 가로 800×480 에뮬레이터 창이 열립니다. 콘솔을 열어 둔 채 초기화가 끝날 때까지 기다리고, 동의 화면이 나타나면 직접 버튼을 누르세요. 런처는 동의를 자동으로 누르지 않습니다.

`python`이 PATH에 없다면 실행 파일을 직접 지정합니다.

```powershell
$env:GEN5_PYTHON = 'C:/Python310/python.exe'
& $env:GEN5_PYTHON prepare.py
.\start.cmd
```

별도의 설정은 `python prepare.py --config 경로`와 `.\start.cmd --config 경로`로 지정할 수 있습니다. 입력 램디스크나 Java 헬퍼를 바꾸면 `prepare.py`를 다시 실행하세요.

## 종료와 재실행

에뮬레이터 창을 먼저 닫고 콘솔이 종료되는 것을 기다린 뒤 `start.cmd`로 다시 실행합니다. 포트 충돌이 있으면 기존 에뮬레이터를 종료하거나 `port`를 변경하세요. 런처는 기존 프로세스를 강제로 종료하지 않습니다.

`/data`, `/cache`, 가상 저장소는 메모리에 있으므로 설치 앱과 설정은 재실행 시 사라집니다. 다른 시스템 이미지로 바꿀 때는 모든 에뮬레이터를 닫고 `runtime/` 폴더를 다른 이름으로 옮겨 새 작업 사본을 만들 수 있습니다. 기존 작업 이미지가 입력과 다르면 자동 덮어쓰기를 하지 않습니다.

## 문제 확인

- 검은 화면, 동의 버튼 비활성화, 앱 종료는 빌드별 차량 서비스 차이로 발생할 수 있습니다. 모든 펌웨어와 앱의 동작을 보장하지 않습니다.
- 실행 로그는 `runtime/emulator.log`, 초기화 결과는 `runtime/guest-config.txt`와 `runtime/launch.json`을 확인하세요.
- `interactive=false`는 추가 UI 호환 처리를 끕니다. 기본 저장소 구성과 카메라 대체 서비스는 계속 적용합니다.
- 가상 머신 안에서만 root 진단 채널과 서비스 대체 코드를 사용합니다. 실제 차량용 플래싱 이미지나 실기기 ADB 활성화 도구가 아닙니다. 생성한 램디스크를 헤드유닛에 설치하지 마세요.
- 소스 검사는 `python -m unittest discover -s tests -v`로 실행합니다. 이 검사는 실제 화면 부팅 성공을 보장하지 않습니다.
