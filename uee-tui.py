import curses
import time
import json
import os
import subprocess
import fcntl  # needed for non-blocking i/o
from pathlib import Path

CONFIG_FILE = Path("uee_config.json")

TITLE_ART = r"""


UUUUUUUU     UUUUUUUU     EEEEEEEEEEEEEEEEEEEEEE     EEEEEEEEEEEEEEEEEEEEEE
U::::::U     U::::::U     E::::::::::::::::::::E     E::::::::::::::::::::E
U::::::U     U::::::U     E::::::::::::::::::::E     E::::::::::::::::::::E
UU:::::U     U:::::UU     EE::::::EEEEEEEEE::::E     EE::::::EEEEEEEEE::::E
 U:::::U     U:::::U        E:::::E       EEEEEE       E:::::E       EEEEEE
 U:::::D     D:::::U        E:::::E                    E:::::E
 U:::::D     D:::::U        E::::::EEEEEEEEEE          E::::::EEEEEEEEEE
 U:::::D     D:::::U        E:::::::::::::::E          E:::::::::::::::E
 U:::::D     D:::::U        E:::::::::::::::E          E:::::::::::::::E
 U:::::D     D:::::U        E::::::EEEEEEEEEE          E::::::EEEEEEEEEE
 U:::::D     D:::::U        E:::::E                    E:::::E
 U::::::U   U::::::U        E:::::E       EEEEEE       E:::::E       EEEEEE
 U:::::::UUU:::::::U      EE::::::EEEEEEEE:::::E     EE::::::EEEEEEEE:::::E
  UU:::::::::::::UU       E::::::::::::::::::::E     E::::::::::::::::::::E
    UU:::::::::UU         E::::::::::::::::::::E     E::::::::::::::::::::E
      UUUUUUUUU           EEEEEEEEEEEEEEEEEEEEEE     EEEEEEEEEEEEEEEEEEEEEE



"""

# This script is now heavily modified.
# It accepts $1 (DISK), $2 (FS_CHOICE), $3 (PATTERN), $4 (PASSES)
UEE_FORMAT_SCRIPT = """#!/bin/bash
set -e

# colors for output
RED=$(tput setaf 1)
GREEN=$(tput setaf 2)
YELLOW=$(tput setaf 3)
NC=$(tput sgr0) # No Color

# must run as root
if [ "$EUID" -ne 0 ]; then
  echo "${RED}This script must be run as root.${NC}"
  exit 1
fi

# check for args
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
  echo "${RED}Usage: $0 /dev/disk_name filesystem_type pattern passes${NC}"
  echo "Example: $0 /dev/sdb ext4 zeros 1"
  exit 1
fi

DISK="$1"
FS_CHOICE="$2"
PATTERN="$3"
PASSES="$4"

# check for required tools
command -v lsblk >/dev/null 2>&1 || { echo >&2 "${RED}lsblk is required but not installed. Aborting.${NC}"; exit 1; }
command -v parted >/dev/null 2>&1 || { echo >&2 "${RED}parted is required but not installed. Aborting.${NC}"; exit 1; }
command -v partprobe >/dev/null 2>&1 || { echo >&2 "${RED}partprobe is required but not installed. Aborting.${NC}"; exit 1; }
command -v dd >/dev/null 2>&1 || { echo >&2 "${RED}dd is required but not installed. Aborting.${NC}"; exit 1; }
command -v tr >/dev/null 2>&1 || { echo >&2 "${RED}tr is required but not installed. Aborting.${NC}"; exit 1; }


if [ ! -b "$DISK" ]; then
  echo "${RED}Error: '$DISK' is not a valid block device.${NC}"
  exit 1
fi

# unmount all partitions on the selected disk
echo "${YELLOW}Checking for mounted partitions on $DISK...${NC}"
for part in $(lsblk -lno NAME "$DISK" | grep -v "^$(basename "$DISK")$"); do
  PART_PATH="/dev/$part"
  if mountpoint -q "$PART_PATH"; then
    echo "Unmounting $PART_PATH..."
    umount "$PART_PATH"
  fi
done

# -------------------------------------------------
# --- NEW SECURE WIPE BLOCK ---
# -------------------------------------------------
if [ -n "$PATTERN" ] && [ "$PATTERN" != "none" ]; then
    echo
    echo "${YELLOW}--- Starting Secure Wipe ---${NC}"
    echo "  Disk: $DISK"
    echo "  Pattern: $PATTERN"
    echo "  Passes: $PASSES"
    echo

    for (( i=1; i<=$PASSES; i++ )); do
        echo "${GREEN}Pass $i of $PASSES...${NC}"
        case $PATTERN in
            "zeros")
                echo "Writing zeros... (This will take a long time)"
                dd if=/dev/zero of="$DISK" bs=4M status=progress
                ;;
            "ones")
                echo "Writing ones... (This will take a long time)"
                # Create a stream of 0xFF (ones) and pipe it
                tr '\0' '\377' < /dev/zero | dd of="$DISK" bs=4M status=progress
                ;;
            "random")
                echo "Writing random data... (This will take a VERY long time)"
                dd if=/dev/urandom of="$DISK" bs=4M status=progress
                ;;
            *)
                echo "${YELLOW}Unknown pattern '$PATTERN', skipping wipe.${NC}"
                ;;
        esac
        echo "${GREEN}Pass $i complete.${NC}"
    done

    echo "${GREEN}--- Secure Wipe Finished ---${NC}"
else
    echo "${YELLOW}Pattern is 'none', skipping secure wipe.${NC}"
fi
# -------------------------------------------------
# --- END NEW SECURE WIPE BLOCK ---
# -------------------------------------------------


# set tool based on $2
case $FS_CHOICE in
  "ext4")
    TOOL="mkfs.ext4"
    declare -a ARGS=("-L" "DATA")
    ;;
  "fat32")
    TOOL="mkfs.vfat"
    declare -a ARGS=("-F" "32" "-n" "DATA")
    ;;
  "exfat")
    TOOL="mkfs.exfat"
    declare -a ARGS=("-L" "DATA")
    ;;
  "ntfs")
    TOOL="mkfs.ntfs"
    declare -a ARGS=("-L" "DATA" "-f")
    ;;
  *)
    echo "${RED}Invalid filesystem '$FS_CHOICE'. Aborting.${NC}"
    exit 1
    ;;
esac

# check for the specific formatting tool
command -v $TOOL >/dev/null 2>&1 || { echo >&2 "${RED}Tool '$TOOL' for $FS_CHOICE is not installed. Aborting.${NC}"; exit 1; }

echo
echo "${GREEN}--- Starting Partitioning and Formatting ---${NC}"

# create a new gpt partition table
echo "1. Wiping partition table on $DISK..."
parted "$DISK" --script -- mklabel gpt

# create a single partition covering the whole disk
echo "2. Creating new primary partition on $DISK..."
parted "$DISK" --script -- mkpart primary 0% 100%

# tell the kernel to re-read the partition table
echo "3. Reloading partition table..."
partprobe "$DISK"
sleep 2 # give the system a moment to catch up

# find the name of the new partition (e.g., sdb1 or nvme0n1p1)
PARTITION_NAME=$(lsblk -lno NAME "$DISK" | tail -n 1)
PARTITION="/dev/$PARTITION_NAME"

if [ ! -b "$PARTITION" ]; then
    echo "${RED}Error: Could not find new partition $PARTITION.${NC}"
    exit 1
fi

echo "4. Found new partition: $PARTITION"

# format the new partition
echo "5. Formatting $PARTITION as $FS_CHOICE..."
$TOOL "${ARGS[@]}" "$PARTITION"

echo
echo "${GREEN}--- All Done! ---${NC}"
echo "Disk $DISK has been successfully wiped and formatted."
echo "Partition: $PARTITION"
echo "Filesystem: $FS_CHOICE"
"""


DEFAULT_CONFIG = {
    "passes": 1,
    "pattern": "zeros",  # Default pattern
    "verify": False,
    "post_action": "none"
}

# modified script to remove all user 'read' prompts
ANDROID_WIPE_SCRIPT = """#!/bin/bash
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
"""


class UEEApp:

    def __init__(self, stdscr):
        self.stdscr = stdscr

        if os.geteuid() != 0:
            self.stdscr.clear()
            self.stdscr.addstr(1, 1, "Error: This application must be run as root (use sudo).")
            self.stdscr.addstr(3, 1, "Press any key to exit.")
            self.stdscr.refresh()
            self.stdscr.nodelay(False)
            self.stdscr.getch()
            raise SystemExit

        self.setup_curses()
        self.height, self.width = self.stdscr.getmaxyx()
        self.state = "main_menu"
        self.selected = 0
        self.drive_idx = 0
        self.message_log = []
        self.config = self.load_config()
        self.process = None
        self.script_output = []
        self.drives = []
        self.pending_fs = None
        self.pending_method = None
        self.scan_drives()

    def setup_curses(self):
        self.stdscr.clear()
        curses.curs_set(0)
        curses.start_color()
        self.stdscr.nodelay(True)

        curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
        self.color_logo = curses.color_pair(1)

        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_GREEN)
        self.color_highlight = curses.color_pair(2)
        self.stdscr.refresh()

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=2)
            self.message_log.append("Config saved to uee_config.json")
        except Exception as e:
            self.message_log.append(f"Failed to save config: {e}")

    def scan_drives(self):
        self.message_log.append("Scanning for drives...")
        self.drives = []
        try:
            cmd = ["lsblk", "-J", "-d", "-o", "NAME,SIZE,MODEL,TYPE"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)

            for item in data.get('blockdevices', []):
                if item.get('type') in ['rom', 'loop']:
                    continue

                name = "/dev/" + item.get('name', 'N/A')
                size = item.get('size', 'N/A')
                model = item.get('model', 'N/A')
                self.drives.append({"name": name, "size": size, "model": model})

            if not self.drives:
                self.message_log.append("No suitable drives found.")
                self.drives.append({"name": "N/A", "size": "", "model": "No drives found"})
        except FileNotFoundError:
            self.message_log.append("Error: 'lsblk' command not found.")
            self.drives.append({"name": "N/A", "size": "", "model": "lsblk not found"})
        except Exception as e:
            self.message_log.append(f"Drive scan failed: {e}")
            self.drives.append({"name": "N/A", "size": "", "model": f"Scan error"})

    def run(self):
        while True:
            self.stdscr.clear()

            if self.state == "run_script":
                self.update_script_output()

            if self.state == "main_menu":
                self.draw_main_menu()
            elif self.state == "basic_menu":
                self.draw_basic_menu()
            elif self.state == "advanced_menu":
                self.draw_advanced_menu()
            elif self.state == "select_drive":
                self.draw_drive_selector()
            elif self.state == "select_fs":
                self.draw_select_fs()
            elif self.state == "confirm":
                self.draw_confirm()
            elif self.state == "confirm_android":
                self.draw_confirm_android()
            elif self.state == "run_script":
                self.draw_run_script()
            else:
                break

            self.stdscr.refresh()
            c = self.stdscr.getch()

            if c == ord('q'):
                if self.process:
                    self.process.kill()
                break
            elif c != -1:
                self.handle_input(c)

            time.sleep(0.01)

    def draw_border(self):
        self.stdscr.border()

    def center_text(self, y, text, attr=0):
        x = max(1, (self.width - len(text)) // 2)
        self.stdscr.addstr(y, x, text, attr)

    def draw_main_menu(self):
        self.draw_border()

        art_lines = TITLE_ART.splitlines()
        starty = 1
        for i, line in enumerate(art_lines):
            if starty + i >= self.height - 6:
                break
            self.stdscr.addstr(starty + i, 2, line[: self.width - 4], self.color_logo)

        menu_y = min(self.height - 7, starty + len(art_lines) + 1)

        current_drive_name = "N/A"
        if self.drives and self.drive_idx < len(self.drives):
            current_drive_name = self.drives[self.drive_idx]["name"]

        options = [
            "Basic Mode",
            "Advanced Mode",
            "Android Mode",
            f"Select Drive (current: {current_drive_name})",
            "View Log",
            "Exit",
        ]

        for idx, opt in enumerate(options):
            y = menu_y + idx
            if idx == self.selected:
                self.stdscr.addstr(y, 4, "-> ")
                self.stdscr.addstr(y, 7, opt, self.color_highlight)
            else:
                self.stdscr.addstr(y, 4, "   " + opt)

        footer = "Use ↑ ↓, Enter. Back w/ Backspace/ESC. q to quit."
        self.stdscr.addstr(self.height - 3, 2, footer)

        base = "v0.1 made by "
        athena = "Athena"
        x_base = self.width - len(base + athena) - 2
        x_base = max(1, x_base)

        if x_base > len(footer) + 3:
            self.stdscr.addstr(self.height - 3, x_base, base, curses.A_DIM)
            self.stdscr.addstr(self.height - 3, x_base + len(base), athena, self.color_logo)

    def draw_basic_menu(self):
        self.draw_border()
        self.center_text(2, "BASIC MODE - Quick Format")
        self.stdscr.addstr(3, 4, "This skips the secure wipe and just formats the drive.")

        options = ["Quick Format (ext4)", "Quick Format (fat32)", "Back"]

        for idx, opt in enumerate(options):
            y = 5 + idx
            if idx == self.selected:
                self.stdscr.addstr(y, 6, "-> ")
                self.stdscr.addstr(y, 9, opt, self.color_highlight)
            else:
                self.stdscr.addstr(y, 6, "   " + opt)

        self.stdscr.addstr(self.height - 3, 2, "This will perform a format-only operation.")

    # draw the advanced configuration editor menu.
    def draw_advanced_menu(self):
        self.draw_border()
        self.center_text(2, "ADVANCED MODE - Secure Erase")
        self.stdscr.addstr(4, 6, "Configure the secure wipe settings, then start.")

        self.stdscr.addstr(6, 6, f"passes : {self.config.get('passes')}")
        self.stdscr.addstr(7, 6, f"pattern: {self.config.get('pattern')}")
        self.stdscr.addstr(8, 6, f"verify : {self.config.get('verify')}")

        options = [
            "Increase passes",
            "Decrease passes",
            "Cycle pattern",
            "Toggle verify",
            "Save config",
            "START ERASE",
            "Back",
        ]

        for idx, opt in enumerate(options):
            y = 10 + idx
            if idx == self.selected:
                self.stdscr.addstr(y, 6, "-> ")
                self.stdscr.addstr(y, 9, opt, self.color_highlight)
            else:
                self.stdscr.addstr(y, 6, "   " + opt)

        self.stdscr.addstr(self.height - 3, 2, "START ERASE will use these settings, then format.")

    def draw_drive_selector(self):
        self.draw_border()
        self.center_text(2, "Select Drive")

        for idx, d in enumerate(self.drives):
            y = 4 + idx
            text = f"{d['name']}   {d['size']}   {d['model']}"
            if idx == self.selected:
                self.stdscr.addstr(y, 6, "-> ")
                self.stdscr.addstr(y, 9, text, self.color_highlight)
            else:
                self.stdscr.addstr(y, 6, "   " + text)

        y = 4 + len(self.drives)
        if self.selected == len(self.drives):
            self.stdscr.addstr(y, 6, "-> ")
            self.stdscr.addstr(y, 9, "Back", self.color_highlight)
        else:
            self.stdscr.addstr(y, 6, "   Back")

        self.stdscr.addstr(self.height - 3, 2, "WARNING: This will permanently destroy data.")

    def draw_select_fs(self):
        self.draw_border()
        self.center_text(2, "Select Filesystem (Final Step)")
        self.stdscr.addstr(3, 4, "Select a filesystem to apply *after* the wipe.")
        options = ["ext4", "fat32", "exfat", "ntfs", "Back"]

        for idx, opt in enumerate(options):
            y = 5 + idx
            if idx == self.selected:
                self.stdscr.addstr(y, 6, "-> ")
                self.stdscr.addstr(y, 9, opt, self.color_highlight)
            else:
                self.stdscr.addstr(y, 6, "   " + opt)

        self.stdscr.addstr(self.height - 3, 2, "This will format the entire disk with one partition.")

    def draw_confirm(self):
        self.draw_border()
        self.center_text(2, "CONFIRM OPERATION")
        drive = self.drives[self.drive_idx]
        method = self.pending_method

        self.stdscr.addstr(4, 6, f"Drive:      {drive['name']}   {drive['size']}   {drive['model']}")
        self.stdscr.addstr(5, 6, f"Method:     {method}")
        self.stdscr.addstr(6, 6, f"Pattern:    {self.config.get('pattern')}")
        self.stdscr.addstr(7, 6, f"Passes:     {self.config.get('passes')}")
        self.stdscr.addstr(8, 6, f"Filesystem: {self.pending_fs}")

        self.stdscr.addstr(10, 6, "Type 'FORMAT' to begin, or Back to cancel.")

        self.stdscr.nodelay(False)
        curses.echo()
        self.stdscr.addstr(12, 6, "> ")
        s = self.stdscr.getstr(12, 8, 20).decode('utf-8')
        curses.noecho()
        self.stdscr.nodelay(True)

        if s.strip() == "FORMAT":
            self.message_log.append(f"Starting operation on {drive['name']}...")
            self.start_format_script()
            self.state = "run_script"
        else:
            self.message_log.append("Operation cancelled.")
            self.state = "main_menu"
            self.selected = 0

    def draw_confirm_android(self):
        self.draw_border()
        self.center_text(2, "CONFIRM ANDROID WIPE")
        self.stdscr.addstr(4, 6, "This will attempt to wipe all data on ALL")
        self.stdscr.addstr(5, 6, "connected devices in ADB mode.")
        self.stdscr.addstr(7, 6, "Type 'CONFIRM' to begin, or Back to cancel.")

        self.stdscr.nodelay(False)
        curses.echo()
        self.stdscr.addstr(9, 6, "> ")
        s = self.stdscr.getstr(9, 8, 20).decode('utf-8')
        curses.noecho()
        self.stdscr.nodelay(True)

        if s.strip() == "CONFIRM":
            self.message_log.append("Starting Android wipe...")
            self.start_android_wipe()
            self.state = "run_script"
        else:
            self.message_log.append("Android wipe cancelled.")
            self.state = "main_menu"
            self.selected = 0

    def draw_run_script(self):
        self.draw_border()

        title = "Running Script..."
        if self.pending_fs:
             title = f"Wiping/Formatting {self.drives[self.drive_idx]['name']}..."
        else:
            title = "Running Android Wipe Script..."

        self.center_text(2, title)

        max_lines = self.height - 6
        start_index = max(0, len(self.script_output) - max_lines)

        y = 4
        for line in self.script_output[start_index:]:
            self.stdscr.addstr(y, 4, line[:self.width - 8])
            y += 1

        if self.process is None:
            self.stdscr.addstr(self.height - 3, 2, "Script finished. Press any key to return.")
        else:
            self.stdscr.addstr(self.height - 3, 2, "Script running... Press 'q' to force quit.")

    def update_script_output(self):
        if self.process is None:
            return

        try:
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    self.script_output.append(line.strip())
                else:
                    break
        except (IOError, TypeError):
            pass

        status = self.process.poll()
        if status is not None:
            if self.pending_fs:
                self.message_log.append(f"Format script finished with code {status}.")
            else:
                self.message_log.append(f"Android script finished with code {status}.")

            self.process.stdout.close()
            self.process = None

    # write and start the format script.
    def start_format_script(self):
        script_name = "uee_format.sh"
        self.script_output = [f"Preparing {script_name}..."]

        drive_name = self.drives[self.drive_idx]['name']
        fs_type = self.pending_fs

        pattern = "none"

        passes = str(self.config.get('passes', 1))

        try:
            with open(script_name, "w") as f:
                f.write(UEE_FORMAT_SCRIPT)
            os.chmod(script_name, 0o755)
            self.script_output.append("Script created.")
        except Exception as e:
            self.script_output.append(f"Failed to create format script: {e}")
            self.process = None
            return

        try:
            cmd = ["/bin/bash", script_name, drive_name, fs_type, pattern, passes]
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            fd = self.process.stdout.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            self.script_output.append(f"Starting: {' '.join(cmd)}")
            self.script_output.append("---")

        except Exception as e:
            self.script_output.append(f"Failed to start script: {e}")
            self.process = None

    def start_android_wipe(self):
        script_name = "android_wipe.sh"
        self.script_output = [f"Preparing {script_name}..."]
        self.pending_fs = None

        try:
            with open(script_name, "w") as f:
                f.write(ANDROID_WIPE_SCRIPT)
            os.chmod(script_name, 0o755)
            self.script_output.append("Script created.")
        except Exception as e:
            self.script_output.append(f"Failed to create wipe script: {e}")
            self.process = None
            return

        try:
            self.process = subprocess.Popen(
                ["/bin/bash", script_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            fd = self.process.stdout.fileno()
            fl = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)

            self.script_output.append(f"Starting: /bin/bash {script_name}")
            self.script_output.append("---")

        except Exception as e:
            self.script_output.append(f"Failed to start script: {e}")
            self.process = None

    def handle_input(self, c):
        if c in (curses.KEY_BACKSPACE, 27):
            if self.state not in ['main_menu', 'run_script']:
                self.state = 'main_menu'
                self.selected = 0
                self.pending_fs = None
                self.pending_method = None
            return

        if self.state == 'main_menu':
            if c == curses.KEY_UP: self.selected = (self.selected - 1) % 6
            elif c == curses.KEY_DOWN: self.selected = (self.selected + 1) % 6
            elif c in (curses.KEY_ENTER, 10, 13):
                if self.selected == 0: self.state = 'basic_menu'
                elif self.selected == 1: self.state = 'advanced_menu'
                elif self.selected == 2: self.state = 'confirm_android'
                elif self.selected == 3:
                    if self.drives[0]['name'] != 'N/A':
                        self.state = 'select_drive'
                    else:
                        self.message_log.append("No drives to select.")
                elif self.selected == 4: self.view_log()
                elif self.selected == 5: raise SystemExit
                self.selected = 0

        elif self.state == 'basic_menu':
            if c == curses.KEY_UP: self.selected = (self.selected - 1) % 3
            elif c == curses.KEY_DOWN: self.selected = (self.selected + 1) % 3
            elif c in (curses.KEY_ENTER, 10, 13):
                # Set config to 'none' for basic mode
                self.config['pattern'] = 'none'
                self.config['passes'] = 1

                if self.selected == 0:
                    self.pending_method = 'Basic Format'
                    self.pending_fs = 'ext4'
                    self.state = 'confirm'
                elif self.selected == 1:
                    self.pending_method = 'Basic Format'
                    self.pending_fs = 'fat32'
                    self.state = 'confirm'
                else: # Back
                    self.state = 'main_menu'
                self.selected = 0

        elif self.state == 'advanced_menu':
            if c == curses.KEY_UP: self.selected = (self.selected - 1) % 7
            elif c == curses.KEY_DOWN: self.selected = (self.selected + 1) % 7
            elif c in (curses.KEY_ENTER, 10, 13):
                if self.selected == 0:
                    self.config['passes'] += 1
                elif self.selected == 1:
                    self.config['passes'] = max(1, self.config['passes'] - 1)
                elif self.selected == 2:
                    patterns = ['zeros', 'ones', 'random']
                    try:
                        cur_idx = patterns.index(self.config['pattern'])
                        self.config['pattern'] = patterns[(cur_idx + 1) % len(patterns)]
                    except ValueError:
                        self.config['pattern'] = 'zeros' # Default if not in list
                elif self.selected == 3:
                    self.config['verify'] = not self.config['verify']
                elif self.selected == 4:
                    self.save_config()
                elif self.selected == 5: # START ERASE
                    self.pending_method = 'Advanced Erase'
                    self.state = 'select_fs' # Go to FS selection
                elif self.selected == 6: # Back
                    self.state = 'main_menu'

                if self.selected != 5: # Don't reset selection on START
                    self.selected = 0

        elif self.state == 'select_fs':
            options = ["ext4", "fat32", "exfat", "ntfs", "Back"]
            if c == curses.KEY_UP: self.selected = (self.selected - 1) % 5
            elif c == curses.KEY_DOWN: self.selected = (self.selected + 1) % 5
            elif c in (curses.KEY_ENTER, 10, 13):
                if self.selected < 4:
                    self.pending_fs = options[self.selected]
                    self.state = 'confirm'
                else: # Back
                    # If we came from advanced, go back there
                    if self.pending_method == 'Advanced Erase':
                        self.state = 'advanced_menu'
                    else: # Otherwise (e.g. from basic), go to main
                        self.state = 'main_menu'
                self.selected = 0

        elif self.state == 'select_drive':
            count = len(self.drives) + 1
            if c == curses.KEY_UP: self.selected = (self.selected - 1) % count
            elif c == curses.KEY_DOWN: self.selected = (self.selected + 1) % count
            elif c in (curses.KEY_ENTER, 10, 13):
                if self.selected < len(self.drives):
                    self.drive_idx = self.selected
                    self.message_log.append(f"Selected drive {self.drives[self.drive_idx]['name']}")
                self.state = 'main_menu'
                self.selected = 0

        elif self.state == 'run_script':
            if self.process is None and c != -1:
                self.pending_fs = None
                self.pending_method = None
                self.script_output = []
                self.state = 'main_menu'
                self.selected = 0

    def view_log(self):
        self.stdscr.clear()
        self.draw_border()
        self.center_text(2, "UEE - Log")
        y = 4
        if not self.message_log:
            self.stdscr.addstr(y, 4, "(no log messages)")
        else:
            start_index = max(0, len(self.message_log) - (self.height - 8))
            for line in self.message_log[start_index:]:
                self.stdscr.addstr(y, 4, line[: self.width - 8])
                y += 1

        self.stdscr.addstr(self.height - 3, 2, "Press any key to go back")
        self.stdscr.nodelay(False)
        self.stdscr.getch()
        self.stdscr.nodelay(True)

        self.state = 'main_menu'
        self.selected = 0


def main(stdscr):
    app = UEEApp(stdscr)
    try:
        app.run()
    except SystemExit:
        pass
    except Exception as e:
        curses.endwin()
        print("An unexpected error occurred:")
        print(e)
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    try:
        curses.wrapper(main)
    except SystemExit:
        pass
    except KeyboardInterrupt:
        pass
