#!/system/bin/sh
# Goldfish guest only. Wait for the user to accept the legal screen before
# restarting IVI services, because the legal confirmation uses the old Navi binder.
[ "$(getprop ro.kernel.qemu)" = 1 ] || exit 1
BB=/system/bin/busybox
n=0
while [ "$n" -lt 600 ]; do
  [ "$(getprop service.bootanim.exit)" = 1 ] && break
  # Some guest Navi implementations let the launcher appear without updating
  # the boot-animation property. This script is started only after the legal
  # screen was observed; its focus must then move to the launcher/all menus.
  focus=$(dumpsys window windows | $BB grep mCurrentFocus)
  echo "$focus" | $BB grep -Eq 'com\.lge\.ivi\.(launcher|allmenus)/' && break
  n=$((n+1)); sleep 1
done
if [ "$n" -ge 600 ]; then echo 'Legal screen was not left; leaving IVI services unchanged'; exit 1; fi
mount -o remount,rw / 2>/dev/null
$BB mkdir -p /ivilog/dropbox
chmod 0777 /ivilog /ivilog/dropbox
# Korea market is needed for the station service in this OEM build.
setprop misc.configuration.market 1
if ! service check bluetooth_manager | $BB grep -q ': found'; then
  CLASSPATH=/data/local/tmp/emulator-bluetooth-stub.jar app_process /system/bin test.emulator.config.BluetoothManagerStub >/data/local/tmp/bluetooth-stub.log 2>&1 &
fi
n=0
while [ "$n" -lt 30 ]; do
 service check bluetooth_manager | $BB grep -q ': found' && break
 n=$((n+1)); sleep 1
done
service check bluetooth_manager | $BB grep -q ': found' || { echo 'Bluetooth placeholder unavailable'; exit 1; }
# Keep the original micom binder for other transactions, but acknowledge raw
# hardware sends in this VM. Do not start multiple nested proxies.
if ! service call com.lge.ivi.server.Micom 6243147 2>/dev/null | $BB grep -q 4d49434f; then
  CLASSPATH=/data/local/tmp/emulator-micom-send-proxy.jar app_process /system/bin test.emulator.config.MicomSendProxy >/data/local/tmp/micom-proxy.log 2>&1 &
fi
n=0
while [ "$n" -lt 30 ]; do
 service call com.lge.ivi.server.Micom 6243147 2>/dev/null | $BB grep -q 4d49434f && break
 n=$((n+1)); sleep 1
done
service call com.lge.ivi.server.Micom 6243147 2>/dev/null | $BB grep -q 4d49434f || { echo 'Micom proxy unavailable'; exit 1; }
p=$($BB pidof com.lge.ivi.server)
if [ -n "$p" ]; then kill $p; sleep 2; fi
am startservice -n com.lge.ivi.server/.IviServer
sleep 5
service check com.lge.ivi.server.configuration
service check com.lge.ivi.StationManager
echo 'Guest app compatibility setup finished'
