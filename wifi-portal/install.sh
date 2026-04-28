#!/bin/bash
# Run this once on the Pi to install the WiFi portal
# Usage: sudo bash install.sh

set -e

echo "Installing WiFi Setup Portal..."

# Install Flask
pip3 install flask --break-system-packages

# Copy portal files to /home/sdl2
mkdir -p /home/sdl2/wifi-portal/templates
cp app.py /home/sdl2/wifi-portal/
cp templates/index.html /home/sdl2/wifi-portal/templates/
cp send_ip_email.py /home/sdl2/wifi-portal/
cp email_config.json /home/sdl2/wifi-portal/

# Install wifi-portal service
cp wifi-portal.service /etc/systemd/system/

# Install wifi-check script and service
cp scripts/wifi-check.sh /usr/local/bin/wifi-check.sh
chmod +x /usr/local/bin/wifi-check.sh
cp scripts/wifi-check.service /etc/systemd/system/

# Install NetworkManager dispatcher for email
cp scripts/99-send-ip /etc/NetworkManager/dispatcher.d/99-send-ip
chmod +x /etc/NetworkManager/dispatcher.d/99-send-ip
chmod +x /home/sdl2/wifi-portal/send_ip_email.py

# Enable and start services
systemctl daemon-reload
systemctl enable wifi-portal.service
systemctl enable wifi-check.service
systemctl start wifi-portal.service
systemctl start wifi-check.service

echo ""
echo "Done! Both services are running."
echo "To verify: sudo systemctl status wifi-portal.service"
echo "           sudo systemctl status wifi-check.service"
