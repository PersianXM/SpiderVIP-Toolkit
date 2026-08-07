#!/bin/sh

# remove shm for netflix running
rm -rf /dev/shm

cp -rf /usr/local/js-parser/parse-url /tmp/

# --- background services with light supervision (ISSUE-002) ---
start_services() {
        if [ -e /usr/bin/satipclient ] && ! pidof satipclient >/dev/null 2>&1 ; then
                /usr/bin/satipclient &
        fi
        if ! pidof app_console >/dev/null 2>&1 ; then
                /usr/bin/app_console "/tmp/console_server_fifo" "/tmp/console_resp_fifo" &
        fi
        if ! pidof streamrelay >/dev/null 2>&1 ; then
                /usr/bin/streamrelay &
        fi
        if [ -e /home/gx/local/user_script ]; then
                /home/gx/local/user_script &
        fi
        # --- Engineering Debug Status Bar (dbgbar) : non-invasive OSD overlay ---
        # Draws onto /dev/fb1 (hifb1) only; never touches the main UI on fb0.
        # Light supervision: respawn if it ever exits. Zero overhead when the
        # config has enabled=0 (the daemon exits immediately in that case).
        if [ -x /usr/local/dbgbar/dbgbar ] && ! pidof dbgbar >/dev/null 2>&1 ; then
                /usr/local/dbgbar/dbgbar &
        fi
}


# --- main supervision loop: UI always recovers instead of black screen (ISSUE-001) ---
while true ; do
        start_services

        if [ -e /data/enable_debug ];then
                cp -rf /data/bianbiang.log /data/bianbiang_last.log
                /usr/bin/bianbiang > /data/bianbiang.log
                ret=$?
                dmesg > /data/kernel.log
                sync
        else
                /usr/bin/bianbiang
                ret=$?
        fi

        # bianbiang exit codes:
        # 1 - halt
        # 2 - reboot
        # 3 - restart enigma
        # 43- enter ofgwrite
        # >128 signal
        case $ret in
                1)
                        /sbin/halt
                        ;;
                2)
                        if [ -f /proc/stb/fp/force_restart ]; then
                                echo 1 > /proc/stb/fp/force_restart
                        fi
                        /sbin/reboot
                        ;;
                3|42|45)
                        # restart enigma / internal restart -> respawn UI
                        sleep 1
                        continue
                        ;;
                4)
                        /sbin/reboot
                        ;;
                16)
                        echo "rescue" > /proc/stb/fp/boot_mode
                        /sbin/reboot
                        ;;
                43)
                        /usr/bin/ofgwrite
                        init 1
                        ;;
                44)
                        # little hack but it will be fixed soon in drivers
                        /usr/lib/enigma2/python/Plugins/SystemPlugins/MICOMUpgrade/bin/fbclear
                        /usr/bin/showiframe /usr/lib/enigma2/python/Plugins/SystemPlugins/MICOMUpgrade/wait.mvi
                        echo fpupload >/proc/vfd && sleep 3 && dd bs=256k if=/tmp/micom.bin of=/dev/mcu
                        /usr/bin/showiframe /usr/lib/enigma2/python/Plugins/SystemPlugins/MICOMUpgrade/reboot.mvi
                        # Wait forever for the user to power off
                        while(true) ; do sleep 60 ; done
                        ;;
                46)
                        /usr/bin/ofgwrite dump
                        init 1
                        ;;
                47)
                        /usr/bin/ofgwrite expert
                        init 1
                        ;;
                *)
                        # cleanup orphan USB mount points (ISSUE-005: fixed copy-paste bug)
                        if [ -e /tmp/UD0 ];then umount /tmp/UD0 ; rm /tmp/UD0 ; fi
                        if [ -e /tmp/UD1 ];then umount /tmp/UD1 ; rm /tmp/UD1 ; fi
                        if [ -e /tmp/UD2 ];then umount /tmp/UD2 ; rm /tmp/UD2 ; fi
                        if [ -e /tmp/UD3 ];then umount /tmp/UD3 ; rm /tmp/UD3 ; fi
                        rm -f /tmp/.listen.camd.socket.ignore
                        # unexpected exit / crash / OOM-kill -> respawn UI (no permanent black screen)
                        sleep 2
                        continue
                        ;;
        esac
        break
done
