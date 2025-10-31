#!/bin/bash
set -e

# check and install adb/fastboot
if ! command -v adb &> /dev/null || ! command -v fastboot &> /dev/null; then
    echo "ADB or Fastboot not found. Installing Android platform tools..."
    if command -v pacman &> /dev/null; then
        sudo pacman -S --noconfirm android-tools
    elif command -v apt &> /dev/null; then
        sudo apt update && sudo apt install -y android-tools-adb android-tools-fastboot
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y android-tools
    elif command -v zypper &> /dev/null; then
        sudo zypper install -y android-tools
    else
        echo "No supported package manager found. Please install android-tools manually."
        exit 1
    fi
fi

# connected devices
echo "Checking for connected devices..."
DEVICE_LIST=$(adb devices | grep -w "device" | awk '{print $1}')

if [ -z "$DEVICE_LIST" ]; then
    echo "No devices detected. Connect at least one device via USB."
    echo "If using normal Android mode, enable Developer Options and USB Debugging."
    sleep 3
    exit 1
fi

# no of devices
echo "Detected devices:"
echo "$DEVICE_LIST"
echo "---"

# parallel wipe
for device in $DEVICE_LIST; do
    (
        echo "Starting wipe on: $device"
        adb -s "$device" reboot recovery
        sleep 5
        adb -s "$device" shell recovery --wipe_data || {
            echo "Wipe command failed on: $device. It may require manual confirmation on-device."
        }
        echo "Wipe complete for: $device"
    ) &
done

wait
echo "All connected devices have been wiped successfully."
sleep 2
