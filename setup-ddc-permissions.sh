#!/usr/bin/env bash
# setup-ddc-permissions.sh
# Run once to grant your user access to DDC/CI monitors without sudo.
# Tested on Fedora 38+ / any systemd distro.

set -e

echo "==> Creating i2c group..."
sudo groupadd --system i2c 2>/dev/null && echo "  Group 'i2c' created." || echo "  Group 'i2c' already exists."

echo "==> Adding $USER to group i2c..."
sudo usermod -aG i2c "$USER"

echo "==> Installing udev rule for /dev/i2c-* ..."
sudo tee /etc/udev/rules.d/45-ddcutil-i2c.rules > /dev/null << 'EOF'
KERNEL=="i2c-[0-9]*", TAG+="uaccess"
KERNEL=="i2c-[0-9]*", GROUP="i2c", MODE="0660"
EOF

echo "==> Reloading udev rules..."
sudo udevadm control --reload-rules
sudo udevadm trigger

echo ""
echo "✔  Done!  Please LOG OUT and LOG BACK IN for group changes to take effect."
echo "   Then run:  python3 simple_ddc.py"
