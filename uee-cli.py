import click
import json
import os
import subprocess
import stat
import tempfile
from pathlib import Path

CONFIG_FILE = Path("uee_config.json")

UEE_FORMAT_SCRIPT = """#!/bin/bash
set -e

RED=$(tput setaf 1)
GREEN=$(tput setaf 2)
YELLOW=$(tput setaf 3)
NC=$(tput sgr0) # No Color

if [ "$EUID" -ne 0 ]; then
  echo "${RED}This script must be run as root.${NC}"
  exit 1
fi

if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ] || [ -z "$4" ]; then
  echo "${RED}Usage: $0 /dev/disk_name filesystem_type pattern passes${NC}"
  echo "Example: $0 /dev/sdb ext4 zeros 1"
  exit 1
fi

DISK="$1"
FS_CHOICE="$2"
PATTERN="$3"
PASSES="$4"

command -v lsblk >/dev/null 2>&1 || { echo >&2 "${RED}lsblk is required but not installed. Aborting.${NC}"; exit 1; }
command -v parted >/dev/null 2>&1 || { echo >&2 "${RED}parted is required but not installed. Aborting.${NC}"; exit 1; }
command -v partprobe >/dev/null 2>&1 || { echo >&2 "${RED}partprobe is required but not installed. Aborting.${NC}"; exit 1; }
command -v dd >/dev/null 2>&1 || { echo >&2 "${RED}dd is required but not installed. Aborting.${NC}"; exit 1; }
command -v tr >/dev/null 2>&1 || { echo >&2 "${RED}tr is required but not installed. Aborting.${NC}"; exit 1; }


if [ ! -b "$DISK" ]; then
  echo "${RED}Error: '$DISK' is not a valid block device.${NC}"
  exit 1
fi

echo "${YELLOW}Checking for mounted partitions on $DISK...${NC}"
for part in $(lsblk -lno NAME "$DISK" | grep -v "^$(basename "$DISK")$"); do
  PART_PATH="/dev/$part"
  if mountpoint -q "$PART_PATH"; then
    echo "Unmounting $PART_PATH..."
    umount "$PART_PATH"
  fi
done

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

command -v $TOOL >/dev/null 2>&1 || { echo >&2 "${RED}Tool '$TOOL' for $FS_CHOICE is not installed. Aborting.${NC}"; exit 1; }

echo
echo "${GREEN}--- Starting Partitioning and Formatting ---${NC}"

echo "1. Wiping partition table on $DISK..."
parted "$DISK" --script -- mklabel gpt

echo "2. Creating new primary partition on $DISK..."
parted "$DISK" --script -- mkpart primary 0% 100%

echo "3. Reloading partition table..."
partprobe "$DISK"
sleep 2

PARTITION_NAME=$(lsblk -lno NAME "$DISK" | tail -n 1)
PARTITION="/dev/$PARTITION_NAME"

if [ ! -b "$PARTITION" ]; then
    echo "${RED}Error: Could not find new partition $PARTITION.${NC}"
    exit 1
fi

echo "4. Found new partition: $PARTITION"

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
    "pattern": "zeros",
    "verify": False,
    "post_action": "none"
}

ANDROID_WIPE_SCRIPT = """#!/bin/bash
set -e

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

echo "Checking for connected devices..."
DEVICE_LIST=$(adb devices | grep -w "device" | awk '{print $1}')

if [ -z "$DEVICE_LIST" ]; then
    echo "No devices detected. Connect at least one device via USB."
    echo "If using normal Android mode, enable Developer Options and USB Debugging."
    sleep 3
    exit 1
fi

echo "Detected devices:"
echo "$DEVICE_LIST"
echo "---"

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


def check_root():
    if os.geteuid() != 0:
        click.secho("Error: This tool must be run as root (use sudo).", fg='red', bold=True)
        raise click.Abort()

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_CONFIG.copy()
    return DEFAULT_CONFIG.copy()

def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        click.echo(f"Config saved to {CONFIG_FILE}")
    except Exception as e:
        click.secho(f"Failed to save config: {e}", fg='red')

def scan_drives(quiet=False):
    drives = []
    try:
        cmd = ["lsblk", "-J", "-d", "-o", "NAME,SIZE,MODEL,TYPE"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        for item in data.get('blockdevices', []):
            if item.get('type') in ['rom', 'loop']:
                continue

            drives.append({
                "name": "/dev/" + item.get('name', 'N/A'),
                "size": item.get('size', 'N/A'),
                "model": item.get('model', 'N/A')
            })

        if not drives and not quiet:
            click.echo("No suitable drives found.")

    except FileNotFoundError:
        if not quiet:
            click.secho("Error: 'lsblk' command not found. Please install it.", fg='red')
    except Exception as e:
        if not quiet:
            click.secho(f"Drive scan failed: {e}", fg='red')
    return drives

def run_script(script_content, script_args):
    try:
        with tempfile.NamedTemporaryFile(mode='w', delete=False, prefix='uee_script_', suffix='.sh') as f:
            f.write(script_content)
            script_path = f.name

        os.chmod(script_path, 0o755)

        cmd = ["/bin/bash", script_path] + script_args
        click.secho(f"--- Starting script: {' '.join(cmd)} ---", fg='yellow')

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True
        )

        for line in iter(process.stdout.readline, ''):
            click.echo(line, nl=False)

        process.stdout.close()
        return_code = process.wait()

        click.echo("--- Script finished ---")

        if return_code != 0:
            click.secho(f"Script failed with exit code {return_code}", fg='red', bold=True)
            raise click.Abort()
        else:
            click.secho("Operation completed successfully.", fg='green', bold=True)

    finally:
        if 'script_path' in locals() and os.path.exists(script_path):
            os.remove(script_path)


@click.group()
def cli():
    """
    UEE - Ultimate Erase Engine (CLI Version)

    A tool for securely wiping and formatting block devices and Android phones.
    Requires root privileges for most operations.
    """
    pass


@cli.command('list-drives')
def list_drives_cmd():
    """Scans for and lists available block devices."""
    click.echo("Scanning for available drives...")
    drives = scan_drives()
    if drives:
        click.echo("-------------------------------------")
        click.echo(f"{'DEVICE':<15} {'SIZE':>8}   {'MODEL'}")
        click.echo("-------------------------------------")
        for d in drives:
            click.echo(f"{d['name']:<15} {d['size']:>8}   {d['model']}")


@cli.command()
@click.option('--set-pattern', type=click.Choice(['zeros', 'ones', 'random']), help='Set default wipe pattern.')
@click.option('--set-passes', type=click.IntRange(min=1), help='Set default number of wipe passes.')
@click.option('--view', is_flag=True, help='View the current saved configuration.')
def config(set_pattern, set_passes, view):
    """
    View or update the default wipe settings in uee_config.json.

    These defaults are used by the 'format' command if not overridden.
    """
    conf = load_config()

    if view:
        click.echo("Current configuration:")
        click.echo(json.dumps(conf, indent=2))
        return

    updated = False
    if set_pattern:
        conf['pattern'] = set_pattern
        click.echo(f"Default pattern set to: {set_pattern}")
        updated = True

    if set_passes:
        conf['passes'] = set_passes
        click.echo(f"Default passes set to: {set_passes}")
        updated = True

    if updated:
        save_config(conf)
    else:
        click.echo("No changes made. Use --view to see config or --set-pattern/--set-passes to change it.")
        click.echo("Try './uee-cli.py config --help' for more info.")


@cli.command('android-wipe')
@click.option('--yes', '-y', is_flag=True, help='Skip the confirmation prompt.')
def android_wipe(yes):
    """
    Attempts to factory reset ALL connected Android devices.

    This command will reboot devices into recovery and send the
    --wipe_data command via ADB.
    """
    check_root()

    click.secho("WARNING: This will attempt to factory reset ALL connected Android devices.", fg='red', bold=True)

    if not yes:
        click.confirm("Are you sure you want to proceed?", abort=True)

    click.echo("Starting Android wipe procedure...")
    run_script(ANDROID_WIPE_SCRIPT, [])


@cli.command()
@click.argument('disk', type=str)
@click.argument('filesystem', type=click.Choice(['ext4', 'fat32', 'exfat', 'ntfs']))
@click.option('--pattern', 'pattern_override', type=click.Choice(['zeros', 'ones', 'random', 'none']), help='Wipe pattern to use (overrides config). "none" skips wipe.')
@click.option('--passes', 'passes_override', type=click.IntRange(min=1), help='Number of passes (overrides config).')
@click.option('--yes', '-y', is_flag=True, help='Skip the final confirmation prompt.')
def format(disk, filesystem, pattern_override, passes_override, yes):
    """
    Wipes, partitions, and formats a target DISK.

    DISK: The block device to format (e.g., /dev/sdb)

    FILESYSTEM: The filesystem to apply (ext4, fat32, exfat, ntfs)

    This command is DESTRUCTIVE and will erase all data.
    """
    check_root()
    conf = load_config()

    pattern = pattern_override or conf.get('pattern', DEFAULT_CONFIG['pattern'])
    passes = passes_override or conf.get('passes', DEFAULT_CONFIG['passes'])

    if pattern == 'none':
        passes = 1

    click.echo("Performing safety checks...")

    try:
        if not stat.S_ISBLK(os.stat(disk).st_mode):
            click.secho(f"Error: '{disk}' is not a block device.", fg='red', bold=True)
            raise click.Abort()
    except FileNotFoundError:
        click.secho(f"Error: Device '{disk}' does not exist.", fg='red', bold=True)
        raise click.Abort()
    except Exception as e:
        click.secho(f"Error checking device: {e}", fg='red', bold=True)
        raise click.Abort()

    available_drives = [d['name'] for d in scan_drives(quiet=True)]
    if disk not in available_drives:
        click.secho(f"Error: '{disk}' was not found as a suitable top-level drive.", fg='red', bold=True)
        click.echo("This tool only formats whole disks, not partitions.")
        click.echo("Available disks:")
        list_drives_cmd.callback()
        raise click.Abort()

    click.secho(f"\n!!! FINAL WARNING !!!", fg='red', bold=True)
    click.echo("You are about to PERMANENTLY DESTROY all data on the following device:")

    click.echo("\n--- OPERATION PLAN ---")
    click.echo(f"  Target Disk: {disk}")
    click.echo(f"  Wipe Pattern: {pattern}")
    if pattern != 'none':
        click.echo(f"  Wipe Passes: {passes}")
    click.echo(f"  Filesystem: {filesystem}")
    click.echo("----------------------\n")

    if not yes:
        basename = os.path.basename(disk)
        confirmation = click.prompt(f"To confirm this IRREVERSIBLE action, type the device name '{basename}'")
        if confirmation != basename:
            click.echo("Confirmation failed. Aborting.")
            raise click.Abort()

    click.echo("Confirmation received. Starting operation...")

    run_script(UEE_FORMAT_SCRIPT, [disk, filesystem, pattern, str(passes)])


if __name__ == '__main__':
    cli()
