#!/bin/bash
sleep 15

while true; do
    WIFI_STATE=$(nmcli -t -f DEVICE,STATE device status | grep "^wlan0" | cut -d: -f2)
    ACTIVE=$(nmcli connection show --active | grep -q "Hotspot" && echo "hotspot" || echo "none")

    if [ "$WIFI_STATE" = "connected" ] && [ "$ACTIVE" != "hotspot" ]; then
        # Connected to real WiFi, all good
        sleep 10
        continue
    fi

    if [ "$ACTIVE" != "hotspot" ]; then
        # Not connected to anything, start hotspot
        nmcli dev wifi hotspot ifname wlan0 ssid "pHModule-Setup" password "setup1234" band bg channel 6
    fi

    sleep 10
done
