#!/usr/bin/env python3
from flask import Flask, render_template, request, jsonify
import subprocess
import time
import threading
import json

app = Flask(__name__)

RECIPIENT_FILE = "/home/sdl2/wifi-portal/recipient.json"

def save_recipient(email):
    with open(RECIPIENT_FILE, "w") as f:
        json.dump({"email": email}, f)

def scan_networks():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, timeout=15
        )
        networks = []
        seen = set()
        for line in result.stdout.strip().split("\n"):
            parts = line.split(":")
            if len(parts) >= 3:
                ssid = parts[0].strip()
                signal = parts[1].strip()
                security = parts[2].strip()
                if ssid and ssid not in seen and ssid != "pHModule-Setup":
                    seen.add(ssid)
                    networks.append({
                        "ssid": ssid,
                        "signal": int(signal) if signal.isdigit() else 0,
                        "secured": security not in ("", "--")
                    })
        networks.sort(key=lambda x: x["signal"], reverse=True)
        return networks
    except Exception:
        return []

def get_wlan_ip():
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

def connect_to_wifi(ssid, password, username=None):
    try:
        subprocess.run(["nmcli", "connection", "delete", ssid], capture_output=True)

        if username:
            domain = username.split('@')[1] if '@' in username else 'utoronto.ca'
            result = subprocess.run([
                "nmcli", "connection", "add",
                "type", "wifi",
                "ifname", "wlan0",
                "con-name", ssid,
                "ssid", ssid,
                "wifi-sec.key-mgmt", "wpa-eap",
                "802-1x.eap", "peap",
                "802-1x.phase2-auth", "mschapv2",
                "802-1x.identity", username,
                "802-1x.password", password,
                "802-1x.anonymous-identity", f"anonymous@{domain}",
            ], capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                return False, result.stderr or "Failed to add connection"

            subprocess.Popen(["nmcli", "connection", "up", ssid])

        else:
            subprocess.Popen([
                "nmcli", "device", "wifi", "connect", ssid, "password", password
            ])

        return True, "Credentials saved"

    except Exception as e:
        return False, str(e)

def delayed_hotspot_down(seconds=3):
    def drop():
        time.sleep(seconds)
        subprocess.run(["nmcli", "connection", "down", "Hotspot"], capture_output=True)
    thread = threading.Thread(target=drop)
    thread.daemon = True
    thread.start()

@app.route("/")
def index():
    networks = scan_networks()
    return render_template("index.html", networks=networks)

@app.route("/scan")
def scan():
    networks = scan_networks()
    return jsonify(networks)

@app.route("/status")
def status():
    result = subprocess.run(
        ["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"],
        capture_output=True, text=True
    )
    connected = any(
        line.startswith("yes") and "pHModule-Setup" not in line
        for line in result.stdout.strip().split("\n")
    )
    ip = get_wlan_ip()
    return jsonify({"connected": connected, "ip": ip})

@app.route("/connect", methods=["POST"])
def connect():
    data = request.get_json()
    ssid = data.get("ssid", "").strip()
    password = data.get("password", "").strip()
    username = data.get("username", "").strip() or None
    recipient = data.get("email", "").strip() or None

    if not ssid:
        return jsonify({"success": False, "message": "No network selected."})

    if recipient:
        save_recipient(recipient)

    success, message = connect_to_wifi(ssid, password, username)

    if success:
        delayed_hotspot_down(3)
        email_msg = f" Email with IP will be sent to {recipient}." if recipient else ""
        return jsonify({
            "success": True,
            "message": f"Connecting to {ssid}!{email_msg}"
        })
    else:
        return jsonify({"success": False, "message": f"Could not connect: {message}"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=False)
