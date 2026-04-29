import os
import yaml
import socket
import threading
from datetime import datetime
from time import sleep
from pathlib import Path
from picamera2 import Picamera2
from libcamera import controls
from neopixel import NeoPixel
from neopixel import board
from sdl_utils import get_logger, send_file_name, receive_file_name
from sdl_utils import send_file_size, receive_file_size

"""
This is a module for the Raspberry Pi Camera Server
Please install the dependencies ONLY on Pi Zero 2 W/WH
Code will NOT work on Pi 5
"""

script_dir = Path(__file__).resolve().parent

with open(script_dir / 'server_settings.yaml', 'r') as file:
    data = yaml.safe_load(file)
    buffer_size = data["BufferSize"]
    chunk_size = data["ChunkSize"]
    server_port = data["ServerPort"]


class CameraServer:
    def __init__(self, host="0.0.0.0", port=server_port):
        self.host = host
        self.port = port
        self.logger = self._setup_logger()
        self.server_ip = self._get_server_ip()
        self.led = self._init_led()
        self.cam = self._init_cam()
        self.color = (200, 200, 200)
        self.camera_lock = threading.Lock()

    @staticmethod
    def _setup_logger():
        return get_logger("WirelessCameraLogger")

    def _get_server_ip(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s_test:
            s_test.connect(("8.8.8.8", 80))
            server_ip = s_test.getsockname()[0]
            self.logger.info(f"My IP address is : {server_ip}")
            return server_ip

    def _init_led(self):
        led = NeoPixel(board.D10, 12, auto_write=True)
        for i in range(0, 3):
            led.fill((100, 100, 100))
            sleep(0.5)
            led.fill((0, 0, 0))
        self.logger.info("LED initialized!")
        return led

    def _init_cam(self):
        self.logger.info("Initializing camera session")
        cam = Picamera2(0)
        config = cam.create_still_configuration(main={"size": (1920, 1080)})
        cam.configure(config)
        if 'AfMode' in cam.camera_controls:
            cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        cam.start()
        self.logger.info("Camera initiated.")
        return cam

    def __del__(self):
        if hasattr(self, 'cam'):
            self.cam.stop()
            self.cam.close()
            self.logger.info("Camera closed.")

    def take_photo(self):
        try:
            with self.camera_lock:
                photo_dir = os.path.join(os.getcwd(), "photos")
                os.makedirs(photo_dir, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                color_cor = ''.join(f"{num:03d}" for num in self.color)
                filename = f"capture_{timestamp}_{color_cor}.jpg"
                img_path = os.path.join(photo_dir, filename)
                self.led.fill(self.color)
                sleep(3)
                self.cam.capture_file(img_path)
                self.led.fill((0, 0, 0))
                self.logger.info(f"Captured {filename}")
                return img_path
        except Exception as e:
            self.logger.error(f"Capture failed: {e}")
            self.led.fill((0, 0, 0))
            return None

    def send_photo(self, conn, img_path):
        with open(img_path, 'rb') as f:
            image_data = f.read()
        img_size = len(image_data)
        img_name = os.path.basename(img_path)

        send_file_name(conn, img_name, self.logger)
        self.logger.info(f"Sent file name {img_name}.")

        echo_name = receive_file_name(conn, self.logger)
        if not echo_name:
            self.logger.error("Failed to receive echoed image name from client.")
            return False
        elif echo_name != img_name:
            self.logger.error("File name mismatch! Aborting transfer.")
            return False
        else:
            self.logger.info(f"Client confirmed image name {img_name}.")

        send_file_size(conn, img_size, self.logger)
        self.logger.info(f"Sent file size {img_size} to client.")

        echoed_size_str = receive_file_size(conn, self.logger)
        if not echoed_size_str:
            self.logger.error("Failed to receive echoed size from client.")
            return False
        try:
            echoed_size = int(echoed_size_str)
            if echoed_size != img_size:
                self.logger.error("File size mismatch! Aborting transfer.")
                return False
            else:
                self.logger.info("File size confirmed. Proceeding with file transfer.")
        except ValueError:
            self.logger.error(f"Invalid size echoed: '{echoed_size_str}'.")
            return False

        offset = 0
        while offset < img_size:
            end = offset + chunk_size
            chunk = image_data[offset:end]
            conn.sendall(chunk)
            offset = end
        self.logger.info("File transfer complete.")
        self.logger.info("Waiting for new command...")

    def handle_client(self, conn):
        try:
            while True:
                msg = conn.recv(buffer_size).decode('utf-8').strip()
                if not msg:
                    break
                self.logger.info(f"Received message: {msg}.")

                if msg == "TAKE_PHOTO":
                    image_path = self.take_photo()
                    if image_path:
                        self.send_photo(conn, image_path)

                elif msg == "CHANGE_COLOR":
                    conn.sendall("PLEASE SEND RGB".encode('utf-8'))
                    self.logger.info("Sent color request to client.")
                    rgb_data = conn.recv(buffer_size).decode('utf-8').strip()
                    try:
                        r, g, b = map(int, rgb_data.split(','))
                        if all(0 <= val <= 255 for val in (r, g, b)):
                            self.color = (r, g, b)
                            self.led.fill(self.color)
                            sleep(1)
                            self.led.fill((0, 0, 0))
                            conn.sendall("COLOR_CHANGED".encode('utf-8'))
                            self.logger.info(f"LED color changed to ({r},{g},{b}).")
                        else:
                            raise ValueError("Values out of range (0-255).")
                    except Exception as e:
                        conn.sendall(f"INVALID_RGB: {e}".encode('utf-8'))
                        self.logger.error(f"Invalid RGB values: {rgb_data}.")

        except Exception as e:
            self.logger.error(f"Handle client error: {e}.")
        finally:
            conn.close()
            self.logger.info("Client connection closed.")
            self.logger.info("Waiting for new connection.")

    def start_server(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((self.server_ip, self.port))
            server.listen(5)
            self.logger.info(f"Server started on {self.server_ip}:{self.port}.")
            self.logger.info("Waiting for connection...")
            while True:
                conn, addr = server.accept()
                self.logger.info(f"Connected with address: {addr}.")
                threading.Thread(
                    target=self.handle_client,
                    args=(conn,),
                    daemon=True
                ).start()
        except KeyboardInterrupt:
            self.logger.info("Server shutdown requested.")
        finally:
            server.close()
            self.led.fill((0, 0, 0))
            self.logger.info("Server socket closed.")


if __name__ == "__main__":
    camera = CameraServer()
    camera.start_server()
