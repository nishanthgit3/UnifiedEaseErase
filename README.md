# Unified Ease Erase (UEE)  

Unified Ease Erase (UEE) is a secure data sanitization system designed for Linux systems and Android devices through ADB. It provides a streamlined user experience for beginners while offering extensive configurability for advanced users and large-scale device processing. UEE focuses on reliability, clarity, and consistent behavior across supported platforms and storage types.  


https://github.com/user-attachments/assets/6f0cb345-91f6-48a4-9590-a143d40dd75f


---

## 1. Supported Platforms

### Linux
- Core environment for UEE tools.
- Full-featured CLI for power users.
- Optional GUI client layered over the CLI for convenience.

To run TUI version of UEE:  
```bash
sudo python3 uee-tui.py
```

To run CLI version of UEE:  
```bash
sudo python3 uee-cli.py
```

### Android (via ADB)
- Automated, minimal-interaction wipe workflow.
- Supports complete internal storage wipe and factory reset processes.
- Fully integrated with the same configuration system used on Linux.

---

## 2. Supported Storage Types

UEE securely wipes multiple storage technologies, including:

- HDD  
- SATA SSD  
- NVMe SSD  
- eMMC  
- UFS  

Wipe behavior is consistent across all supported device types.

---

## 3. Operating Modes

### Basic Mode
- Designed for everyday users.
- Automatically detects connected storage devices.
- Offers simple wipe options such as Write Zeroes and Write Ones.
- Optional verification pass to ensure wipe accuracy.
- One-click Auto Erase using safe, recommended defaults.

### Advanced Mode
- Intended for technical users and automated workflows.
- Allows fine-grained control of wipe passes, patterns, and verification.
- Accessible through CLI and TUI interfaces.
- Entirely driven by a unified configuration file.

---

## 4. Configuration File

UEE uses a single configuration file named `uee_config.json`.

**Key characteristics:**
- Defines wipe patterns, number of passes, verification settings, and end actions.
- Shared unmodified across Linux and Android workflows.
- Ensures consistent behavior on all devices processed.
- Suitable for automation, standardization, and high-volume wipe operations.

---

## 5. Wiping Methods and Patterns

UEE supports a range of overwrite techniques, including:

- Write Zeroes (0x00)  
- Write Ones (0xFF)  
- Random data patterns  
- Multi-pass sequences defined within the configuration file  

Verification can be enabled to confirm that the target pattern was correctly written to the device.

---

## 6. Android Wipe Workflow (ADB)

UEE provides a structured wipe process for Android devices:

- Detects devices automatically after ADB authorization.
- Performs full internal storage erasure.
- Can trigger factory reset where supported.
- Designed for zero-touch or bulk-device processing.
- Uses the same configuration file as Linux to maintain uniform behavior.
