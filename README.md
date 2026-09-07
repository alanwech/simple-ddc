# simple-ddc

A lightweight DDC/CI monitor brightness controller for Linux — a Monitorian-style GUI built with only Python + tkinter (no extra packages needed).

![screenshot placeholder](https://via.placeholder.com/520x300/1E1E2E/CDD6F4?text=simple-ddc)

## Features

- 🖥 **Auto-detects** all DDC/CI-capable monitors
- ☀ **Real-time brightness slider** with debounced writes
- ◐ **Contrast slider** when supported by the monitor
- 📊 **Details panel** per monitor: brightness, contrast, colour preset, connector and bus
- 🔄 **Auto-refresh** every 5 s (toggleable)
- 🚫 **Zero pip dependencies** — only Python 3 stdlib + tkinter

## Requirements

| Package | Fedora install |
|---------|---------------|
| Python 3 | pre-installed |
| python3-tkinter | `sudo dnf install python3-tkinter` |
| ddcutil | `sudo dnf install ddcutil` |

## Quick Start (Fedora / RHEL / CentOS Stream)

```bash
# 1. Install dependencies
sudo dnf install -y ddcutil python3-tkinter

# 2. Clone the repo
git clone https://github.com/YOUR_USERNAME/simple-ddc
cd simple-ddc

# 3. Grant your user DDC access (run once, then log out/in)
bash setup-ddc-permissions.sh

# 4. Run
python3 simple_ddc.py
```

> **Why do I need to log out?**  
> The `setup-ddc-permissions.sh` script adds you to the `i2c` group and installs a udev rule so your user can talk to `/dev/i2c-*` devices without `sudo`. Linux group changes only take effect in new login sessions.

## Manual permission setup

If you prefer to do it yourself:

```bash
sudo groupadd --system i2c
sudo usermod -aG i2c $USER
sudo tee /etc/udev/rules.d/45-ddcutil-i2c.rules <<'EOF'
KERNEL=="i2c-[0-9]*", TAG+="uaccess"
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
# log out and back in
```

## Optional: install as a desktop app

```bash
sudo mkdir -p /opt/simple-ddc
sudo cp simple_ddc.py /opt/simple-ddc/
sudo cp simple-ddc.desktop /usr/share/applications/
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "No monitors detected" | Run `setup-ddc-permissions.sh`, log out/in |
| "ddcutil not found" | `sudo dnf install ddcutil` |
| Slider has no effect | Some monitors need `--sleep-multiplier 2` — edit `run()` in `simple_ddc.py` |
| Contrast shows `n/a` | That monitor does not expose VCP `0x12` through DDC/CI |
| Display not listed | Run `ddcutil detect` in a terminal to debug |

## Tested on

- Fedora 44 (Wayland)
- Monitors connected via DisplayPort