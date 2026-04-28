#!/usr/bin/env python3
import smtplib
import json
import sys
import subprocess
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def get_ip():
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "wlan0"],
            capture_output=True, text=True
        )
        for line in result.stdout.split("\n"):
            if "inet " in line:
                ip = line.strip().split()[1].split("/")[0]
                if ip != "10.42.0.1":
                    return ip
    except Exception:
        pass
    return None

def get_ssid():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
            capture_output=True, text=True
        )
        for line in result.stdout.strip().split("\n"):
            if line.startswith("yes"):
                return line.split(":")[1]
    except Exception:
        pass
    return "Unknown"

def send_email(recipient, ip, ssid):
    try:
        with open("/home/sdl2/wifi-portal/email_config.json") as f:
            config = json.load(f)

        sender = config["sender_email"]
        password = config["sender_password"]

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = "pH Module — Device Connected"

        body = f"""Your pH Module has connected to a new network.

Network: {ssid}
IP Address: {ip}

SSH Command:
ssh sdl2@{ip}

— pH Module 2.0 · Acceleration Consortium
"""
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print(f"Email sent to {recipient}")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: send_ip_email.py recipient@email.com")
        sys.exit(1)

    recipient = sys.argv[1]
    ip = get_ip()
    ssid = get_ssid()

    if not ip:
        print("No IP found")
        sys.exit(1)

    send_email(recipient, ip, ssid)
