#!/system/bin/sh
# Emulator only. Leave an existing camera service untouched; if it disappears,
# start the previously tested placeholder. Android /data here is temporary.
[ "$(getprop ro.kernel.qemu)" = 1 ] || exit 1
while true; do
    if ! /system/bin/service check com.lge.ivi.auxcamera.AuxCameraManager 2>/dev/null | /system/bin/busybox grep -q ': found'; then
        if [ -r /data/local/tmp/emulator-camera-stub.jar ]; then
            CLASSPATH=/data/local/tmp/emulator-camera-stub.jar /system/bin/app_process /system/bin test.emulator.config.CameraStub >>/data/local/tmp/camera-stub.log 2>&1 &
            sleep 3
        fi
    fi
    sleep 5
done
