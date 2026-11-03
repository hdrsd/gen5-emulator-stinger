"""Launch an isolated, disposable Gen5 Android user-space VM on Windows."""
from pathlib import Path
import argparse,json,os,re,socket,struct,subprocess,time,uuid
from common import ROOT,BUILD,RUNTIME,load_config,verify_prepared,emulator_command,stage_runtime,check_ports

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config',default='config.local.json')
parser.add_argument('--check',action='store_true',help='Validate local dependencies without starting the VM')
parser.add_argument('--dry-run',action='store_true',help='Print the emulator command without copying images or starting processes')
args=parser.parse_args()
try:
    cfg=load_config(args.config)
    if args.check:
        print('Inputs found; raw ext image and classic ARM emulator layout checked.')
        print('Run prepare.py, then launch.py. This check does not prove the firmware can boot.')
        raise SystemExit(0)
    verify_prepared(cfg)
    cmd=emulator_command(cfg)
    if args.dry_run:
        print(subprocess.list2cmdline(cmd))
        raise SystemExit(0)
    if os.name!='nt':raise ValueError('This launcher currently supports Windows only.')
    check_ports(cfg['port'])
    env=stage_runtime(cfg)
except (ValueError,OSError) as exc:
    parser.exit(1,str(exc)+'\n')
root=ROOT;trial=RUNTIME;interactive=cfg['interactive']
log=(trial/'emulator.log').open('wb')
started_at=time.monotonic()
window_startup=subprocess.STARTUPINFO()
window_startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
window_startup.wShowWindow=1
p=subprocess.Popen(cmd,cwd=trial,env=env,stdout=log,stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,startupinfo=window_startup)
print('Emulator process started, PID',p.pid,flush=True)
print('Vehicle hardware is simulated. Keep this console open while using the VM.',flush=True)

def send(s,c,a=0,b=0,data=b''):
    x=int.from_bytes(c.encode(),'little');s.sendall(struct.pack('<6I',x,a,b,len(data),sum(data)&0xffffffff,x^0xffffffff)+data)
def exact(s,n):
    buf=b''
    while len(buf)<n:
        part=s.recv(n-len(buf))
        if not part:raise EOFError()
        buf+=part
    return buf
def recv(s):
    c,a,b,n,ch,magic=struct.unpack('<6I',exact(s,24))
    if magic!=(c^0xffffffff) or n>1048576:raise ValueError('bad ADB packet')
    data=exact(s,n)
    if sum(data)&0xffffffff!=ch:raise ValueError('bad ADB checksum')
    return c.to_bytes(4,'little').decode(),a,b,data
deadline=time.monotonic()+120
s=None
while time.monotonic()<deadline:
    try:
        if p.poll() is not None:raise SystemExit('Emulator launcher exited before diagnostics were available; see runtime/emulator.log.')
        s=socket.create_connection(('127.0.0.1',cfg['port']+1),timeout=2);s.settimeout(4)
        send(s,'CNXN',0x01000000,4096,b'host::\0')
        if recv(s)[0]!='CNXN':raise ValueError('guest not ready')
        send(s,'OPEN',1,0,b'tcp:2323\0')
        kind,remote,local,_=recv(s)
        if kind!='OKAY' or local!=1:raise ValueError('diagnostic service not ready')
        break
    except (OSError,EOFError,ValueError):
        if s:s.close()
        s=None;time.sleep(2)
if s is None:
    print('Window is open or starting, but guest diagnostic channel did not become available.',flush=True)
    raise SystemExit(2)
print('Guest diagnostic channel connected; preparing emulated storage and boot-resume signal.',flush=True)
command=(b'if [ "$(getprop ro.kernel.qemu)" != 1 ]; then echo VM_""ONLY_REFUSED; exit; fi; '
         b'/system/bin/busybox mkdir -p /mnt/shell/emulated/0 /storage/emulated/0; '
         b'mount -o bind /mnt/shell/emulated/0 /storage/emulated/0; '
         b'mount -o bind /storage/emulated/0 /mnt/sdcard; '
         b'i=0; while [ "$i" -lt 40 ]; do '
         b'if /system/bin/busybox grep -q @fbhelper /proc/net/unix; then '
         b'sleep 1; /system/bin/fbhelper ctl resume; echo RESUME_OK; break; fi; '
         b'i=$((i+1)); sleep 2; done; echo VISIBLE_SETUP_""DONE\n')
send(s,'WRTE',1,remote,command)
result=bytearray();deadline=time.monotonic()+90
while time.monotonic()<deadline:
    try:k,a,b,data=recv(s)
    except socket.timeout:continue
    except EOFError:break
    if k=='WRTE':
        result.extend(data);send(s,'OKAY',1,a)
        if b'VISIBLE_SETUP_DONE' in result:break
    elif k=='CLSE':break
try:send(s,'CLSE',1,remote)
except OSError:pass
s.close()
if b'VM_ONLY_REFUSED' in result:
    raise SystemExit('Refused to configure a non-emulator guest.')
if b'VISIBLE_SETUP_DONE' not in result:
    raise SystemExit('Guest setup did not complete; see runtime/emulator.log.')
(trial/'guest-setup.txt').write_bytes(result)
print('Guest setup finished:', 'resume acknowledged' if b'RESUME_OK\r' in result else 'resume acknowledgement not confirmed',flush=True)
resume_seconds=round(time.monotonic()-started_at,1)

def upload_helper(filename, guest_name):
    data=((BUILD/'helpers.jar') if filename.endswith('.jar') else (ROOT/'helpers'/filename)).read_bytes()
    sock=socket.create_connection(('127.0.0.1',cfg['port']+1),timeout=5);sock.settimeout(20)
    send(sock,'CNXN',0x01000000,4096,b'host::\0');assert recv(sock)[0]=='CNXN'
    send(sock,'OPEN',1,0,b'sync:\0');kind,remote,local,_=recv(sock)
    assert kind=='OKAY' and local==1
    def sync_write(payload):
        send(sock,'WRTE',1,remote,payload)
        kind,_,local,_=recv(sock)
        assert kind=='OKAY' and local==1
    path=('/data/local/tmp/'+guest_name+',33206').encode('ascii')
    sync_write(b'SEND'+struct.pack('<I',len(path))+path)
    for offset in range(0,len(data),4000):
        chunk=data[offset:offset+4000]
        sync_write(b'DATA'+struct.pack('<I',len(chunk))+chunk)
    send(sock,'WRTE',1,remote,b'DONE'+struct.pack('<I',int(time.time())))
    while True:
        kind,a,_,payload=recv(sock)
        if kind=='WRTE':
            send(sock,'OKAY',1,a)
            if payload[:4]!=b'OKAY':raise RuntimeError('Guest helper upload failed: '+repr(payload))
            break
    send(sock,'CLSE',1,remote);sock.close()

def root_command(command, timeout=12):
    """Run one idempotent diagnostic command; callers retry after guest ADB restarts."""
    marker=('EMU_'+uuid.uuid4().hex).encode('ascii')
    sock=socket.create_connection(('127.0.0.1',cfg['port']+1),timeout=5);sock.settimeout(3)
    try:
        send(sock,'CNXN',0x01000000,4096,b'host::\0')
        if recv(sock)[0]!='CNXN':raise RuntimeError('Guest ADB not ready')
        send(sock,'OPEN',1,0,b'tcp:2323\0')
        kind,remote,local,_=recv(sock)
        if kind!='OKAY' or local!=1:raise RuntimeError('Guest diagnostic service not ready')
        # Split the marker in the command so terminal echo cannot be mistaken for completion.
        separator=b' ' if command.rstrip().endswith('&') else b'; '
        wire=command.encode('ascii')+separator+b'echo '+marker[:8]+b'""'+marker[8:]+b'\n'
        send(sock,'WRTE',1,remote,wire)
        output=bytearray(); deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:kind,a,_,payload=recv(sock)
            except socket.timeout:continue
            if kind=='WRTE':
                output.extend(payload);send(sock,'OKAY',1,a)
                if marker+b'\r' in output:return bytes(output)
            elif kind=='CLSE':break
        raise RuntimeError('Guest command did not finish')
    finally:sock.close()

boot_ok=False;camera_ok=False;camera_mock_started=False;bootanim_stopped=False
milestones={'resume_seconds':resume_seconds}
setup_log=bytearray();deadline=time.monotonic()+150
uploaded=False
while time.monotonic()<deadline and not (boot_ok and camera_ok and bootanim_stopped):
    try:
        if not uploaded:
            upload_helper('camera-stub.jar','emulator-camera-stub.jar')
            uploaded=True
        if not camera_ok:
            result2=root_command('service check com.lge.ivi.auxcamera.AuxCameraManager')
            if b': found' not in result2:
                root_command('CLASSPATH=/data/local/tmp/emulator-camera-stub.jar app_process /system/bin test.emulator.config.CameraStub >/data/local/tmp/camera-stub.log 2>&1 &')
                camera_log=root_command('cat /data/local/tmp/camera-stub.log')
                camera_mock_started=b'EMULATOR CAMERA PLACEHOLDER REGISTERED' in camera_log
            result2=root_command('service check com.lge.ivi.auxcamera.AuxCameraManager')
            camera_ok=b': found' in result2
            if camera_ok:
                camera_log=root_command('cat /data/local/tmp/camera-stub.log')
                camera_mock_started=b'EMULATOR CAMERA PLACEHOLDER REGISTERED' in camera_log
                milestones['camera_seconds']=round(time.monotonic()-started_at,1)
        if not boot_ok:
            result2=root_command('getprop sys.boot_completed')
            boot_ok=b'\r\n1\r' in result2 or b'\n1\r' in result2
            if boot_ok:milestones['boot_seconds']=round(time.monotonic()-started_at,1)
        if boot_ok and not bootanim_stopped:
            root_command('setprop service.bootanim.exit 1; stop bootanim')
            result2=root_command('getprop init.svc.bootanim')
            bootanim_stopped=b'\r\nstopped\r' in result2 or b'\nstopped\r' in result2
            if bootanim_stopped:milestones['bootanim_stopped_seconds']=round(time.monotonic()-started_at,1)
    except (OSError,EOFError,AssertionError,RuntimeError,ValueError) as exc:
        setup_log.extend((str(exc)+'\n').encode('utf8',errors='replace'))
    if not (boot_ok and camera_ok and bootanim_stopped):time.sleep(2)
(trial/'guest-config.txt').write_bytes(setup_log)
print('Guest boot:', 'complete' if boot_ok else 'not confirmed',flush=True)
print('Guest camera service:', 'available' if camera_ok else 'not confirmed',flush=True)
if camera_mock_started:print('Guest camera service uses an emulator placeholder.',flush=True)
print('Guest boot animation:', 'stopped' if bootanim_stopped else 'not confirmed',flush=True)
camera_watchdog_ok=False
if camera_ok:
    for attempt in range(4):
        try:
            upload_helper('camera-watchdog.sh','emulator-camera-watchdog.sh')
            root_command('p=$(/system/bin/busybox cat /data/local/tmp/emulator-camera-watchdog.pid 2>/dev/null); '
                         'if [ -z "$p" ] || ! kill -0 "$p" 2>/dev/null; then '
                         '/system/bin/busybox nohup /system/bin/sh /data/local/tmp/emulator-camera-watchdog.sh >/data/local/tmp/camera-watchdog.log 2>&1 & '
                         'echo $! >/data/local/tmp/emulator-camera-watchdog.pid; fi')
            check=root_command('p=$(/system/bin/busybox cat /data/local/tmp/emulator-camera-watchdog.pid 2>/dev/null); '
                               'if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then echo WATCHDOG_""RUNNING; fi')
            camera_watchdog_ok=b'WATCHDOG_RUNNING\r' in check
            if camera_watchdog_ok:break
        except (OSError,EOFError,AssertionError,RuntimeError,ValueError) as exc:
            setup_log.extend(('camera watchdog: '+str(exc)+'\n').encode('utf8',errors='replace'))
        time.sleep(2)
    print('Guest camera-service monitor:', 'running' if camera_watchdog_ok else 'not confirmed',flush=True)
fastboot_mock_ok=False;navi_proxy_ok=False;systemui_restarted=False;legal_buttons_enabled=False
if interactive:
    print('Interactive compatibility mode: emulating missing IVI fastboot readiness. This does not validate real hardware.',flush=True)
    interactive_uploaded=False;deadline=time.monotonic()+90
    while time.monotonic()<deadline and not systemui_restarted:
        try:
            if not interactive_uploaded:
                upload_helper('fastboot-stub.jar','emulator-fastboot-stub.jar')
                upload_helper('navi-confirm-proxy.jar','emulator-navi-confirm-proxy.jar')
                interactive_uploaded=True
            log_check=root_command('cat /data/local/tmp/fastboot-stub.log')
            if b'EXPERIMENTAL FASTBOOT PLACEHOLDER REGISTERED' not in log_check:
                root_command('CLASSPATH=/data/local/tmp/emulator-fastboot-stub.jar app_process /system/bin test.emulator.config.FastbootStub >/data/local/tmp/fastboot-stub.log 2>&1 &')
                time.sleep(2)
                log_check=root_command('cat /data/local/tmp/fastboot-stub.log')
            check=root_command('service call com.lge.ivi.server.Fastboot 7')
            fastboot_mock_ok=(b'EXPERIMENTAL FASTBOOT PLACEHOLDER REGISTERED' in log_check and b'Parcel(00000000 00000001' in check)
            if fastboot_mock_ok and not navi_proxy_ok:
                navi_log=root_command('cat /data/local/tmp/navi-confirm-proxy.log')
                if b'EXPERIMENTAL NAVI CONFIRM PROXY REGISTERED' not in navi_log:
                    root_command('CLASSPATH=/data/local/tmp/emulator-navi-confirm-proxy.jar app_process /system/bin test.emulator.config.NaviConfirmProxy >/data/local/tmp/navi-confirm-proxy.log 2>&1 &')
                    time.sleep(2)
                    navi_log=root_command('cat /data/local/tmp/navi-confirm-proxy.log')
                # Probe our private transaction rather than invoking the actual
                # consent transaction, which must only occur after a user tap.
                navi_check=root_command('service call com.lge.ivi.navi.NaviManager 6243147')
                navi_proxy_ok=(b'EXPERIMENTAL NAVI CONFIRM PROXY REGISTERED' in navi_log and b'parcel(00000000 4e415649' in navi_check.lower())
            if fastboot_mock_ok and navi_proxy_ok:
                # Existing SystemUI holds the real Binder reference; restarting only the
                # virtual guest's process makes it reconnect to the explicitly simulated service.
                # Preserve the legal screen: stock SystemUI skips it when the
                # boot-animation exit property is already 1 at process startup.
                root_command('setprop service.bootanim.exit 0; p=$(/system/bin/busybox pidof com.android.ivisystemui); if [ -n "$p" ]; then kill -9 $p; fi')
                systemui_restarted=True
        except (OSError,EOFError,AssertionError,RuntimeError,ValueError) as exc:
            setup_log.extend(('interactive: '+str(exc)+'\n').encode('utf8',errors='replace'))
        if not systemui_restarted:time.sleep(2)
    print('Interactive fastboot placeholder:', 'available' if fastboot_mock_ok else 'not confirmed',flush=True)
    print('Interactive navigation-confirm proxy:', 'available' if navi_proxy_ok else 'not confirmed',flush=True)
    print('Virtual SystemUI restart:', 'requested' if systemui_restarted else 'not confirmed',flush=True)
    if systemui_restarted:
        deadline=time.monotonic()+60
        while time.monotonic()<deadline and not legal_buttons_enabled:
            try:
                focus=root_command('dumpsys window windows | /system/bin/busybox grep mCurrentFocus')
                if b'Legal Screen' in focus:
                    # The virtual modem cannot emit the normal provisioning-ready event.
                    # Do not wait for every unrelated ordered receiver to finish;
                    # some vehicle services are absent in this virtual machine.
                    root_command('am broadcast -a com.lge.ivi.uvo.service.ProvisioningMgr.action.START >/data/local/tmp/provision-ready.log 2>&1 &')
                    dump=root_command('uiautomator dump /data/local/tmp/stinger-legal-check.xml >/dev/null; cat /data/local/tmp/stinger-legal-check.xml',timeout=20)
                    buttons=re.findall(rb'<node[^>]*class="android\.widget\.Button"[^>]*>',dump)
                    legal_buttons_enabled=len(buttons)>=2 and all(b'enabled="true"' in button for button in buttons[:2])
            except (OSError,EOFError,AssertionError,RuntimeError,ValueError) as exc:
                setup_log.extend(('legal screen: '+str(exc)+'\n').encode('utf8',errors='replace'))
            if not legal_buttons_enabled:time.sleep(2)
        print('Legal screen buttons:', 'enabled' if legal_buttons_enabled else 'not confirmed',flush=True)
# The simulated app services start only after the user has confirmed the legal
# screen. Restarting IviServer before confirmation would invalidate its Navi binder.
app_compat_started=False
if boot_ok and (not interactive or legal_buttons_enabled):
    try:
        upload_helper('bluetooth-stub.jar','emulator-bluetooth-stub.jar')
        upload_helper('micom-send-proxy.jar','emulator-micom-send-proxy.jar')
        upload_helper('app-service-start.sh','emulator-app-service-start.sh')
        root_command('/system/bin/busybox nohup /system/bin/sh /data/local/tmp/emulator-app-service-start.sh >/data/local/tmp/app-service-start.log 2>&1 &')
        app_compat_started=True
    except (OSError,EOFError,AssertionError,RuntimeError,ValueError) as exc:
        setup_log.extend(('app compatibility: '+str(exc)+'\n').encode('utf8',errors='replace'))
    print('Guest app compatibility setup:', 'waiting for confirmation or starting' if app_compat_started else 'not confirmed',flush=True)
(trial/'guest-config.txt').write_bytes(setup_log)
print('Setup finished. The emulator window can be closed normally.',flush=True)
(trial/'launch.json').write_text(json.dumps({'launcher_pid':p.pid,'adb_port':cfg['port']+1,'console_port':cfg['port'],'command':cmd,'resume_acknowledged':b'RESUME_OK\r' in result,'boot_completed':boot_ok,'camera_service_available':camera_ok,'camera_mock_started':camera_mock_started,'camera_watchdog_running':camera_watchdog_ok,'boot_animation_stopped':bootanim_stopped,'interactive_mode':interactive,'fastboot_mock_available':fastboot_mock_ok,'navi_confirm_proxy_available':navi_proxy_ok,'systemui_restart_requested':systemui_restarted,'legal_buttons_enabled':legal_buttons_enabled,'milestones':milestones,'note':'Isolated Goldfish emulation; root diagnostics, resume, Kia properties, optional camera fallback, and optional fastboot, provisioning, and navigation-confirm simulation are guest-only.'},indent=2)+'\n',encoding='utf8')
ready = boot_ok and camera_ok and bootanim_stopped and (not interactive or (fastboot_mock_ok and navi_proxy_ok and systemui_restarted and legal_buttons_enabled))
if not ready:
    print('Some compatibility stages are incomplete. See runtime/guest-config.txt.',flush=True)

print('Leave this console open until the emulator is closed.',flush=True)
code=p.wait()
log.close()
raise SystemExit(code or (0 if ready else 2))
