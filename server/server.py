from time import sleep
from pathlib import Path
from server import CameraServer
from PCA9685 import PCA9685
from libcamera import controls

# Get the directory where this script is located
script_dir = Path(__file__).resolve().parent

# Open and read the YAML file
with open(script_dir / 'server_settings.yaml', 'r') as file:
    data = yaml.safe_load(file)
    buffer_size = data["BufferSize"]
    server_port = data["ServerPort"]


class PHTestServer(CameraServer):
    def __init__(self, host="0.0.0.0", port=server_port):
        super().__init__(host, port)
(phenv) sdl2@raspberrypi:~/pizerocam/src/picam_server $ cat ~/pizerocam/src/picam_server/server.py
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

# Get the directory where this script is located
script_dir = Path(__file__).resolve().parent

# Open and read the JSON file
with open(script_dir / 'server_settings.yaml', 'r') as file:
    data = yaml.safe_load(file)
    buffer_size = data["BufferSize"]
    chunk_size = data["ChunkSize"]
    server_port = data["ServerPort"]


class CameraServer:
    """
    This is a class of a server with ability to take photos on demand with user-defined
    LED backlight. The client can request photos and changing the LED backlight.
    """
    def __init__(self, host="0,0,0,0", port=server_port):
        self.host = host
        self.port = port
        self.logger = self._setup_logger()
        self.server_ip = self._get_server_ip()
        self.led = self._init_led()
        self.cam = self._init_cam()
        self.color = (200, 200, 200)    # Default LED configuration
        self.camera_lock = threading.Lock()     # Thread lock

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
        # NeoPixel LED RING with 12 pixels MUST use board.D10
        led = NeoPixel(board.D10, 12, auto_write=True)

        # Blink to show initialization
        for i in range(0, 3):
            led.fill((100, 100, 100))
            sleep(0.5)
            led.fill((0, 0, 0))
        self.logger.info("LED initialized!")
        return led

    def test_led(self, led):
        self.logger.info("Start testing LED")
        _ = input("Please watch for possible dead pixels. Press any key.")    # TODO: Possible
        for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255)]:
            for i in range(0, 12):
                led.fill((0, 0, 0))
                led[i] = color
                sleep(0.1)
        led.fill((0, 0, 0))
        self.logger.info("LED test complete.")

    def _init_cam(self):
        self.logger.info("Initializing camera session")
        cam = Picamera2(0)
        config = cam.create_still_configuration(main={"size": (1920, 1080)})
        cam.configure(config)
        if 'AfMode' in cam.camera_controls:
            cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
        cam.start()
        self.logger.info(f"Camera initiated.")
        return cam

    def __del__(self):
        """
        Making sure the instance is destroyed when camera is closed
        """
        if hasattr(self, 'cam'):
            self.cam.stop()
            self.cam.close()
            self.logger.info(f"Camera closed.")

    def take_photo(self):
        # This function will instantiate a new camera instance every time
        try:
            with self.camera_lock:
                # Create output directory
                photo_dir = os.path.join(os.getcwd(), "photos")
                os.makedirs(photo_dir, exist_ok=True)

                # Generate filename
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                color_cor = ''.join(f"{num:03d}" for num in self.color)
                filename = f"capture_{timestamp}_{color_cor}.jpg"
                img_path = os.path.join(photo_dir, filename)

                # Camera and LED operations
                self.led.fill(self.color)
                sleep(3)           # Wait for auto-exposure to settle
                self.cam.capture_file(img_path)
                self.led.fill((0, 0, 0))
                self.logger.info(f"Captured {filename}")
                return img_path

        except Exception as e:
            self.logger.error(f"Capture failed: {e}")
            self.led.fill((0, 0, 0))
            return None

    def send_photo(self, conn, img_path):
        """
        Function to send filename, send file size, confirm file size, and send file
        :param conn:
        :param img_path: Absolute image path on the server
        :return: False if failed
        """
        # Read the entire file into memory:
        with open(img_path, 'rb') as f:
            image_data = f.read()
        img_size = len(image_data)
        img_name = os.path.basename(img_path)

        # Send the file name with newline
        send_file_name(conn, img_name, self.logger)
        self.logger.info(f"Sent file name {img_name}.")

        # Confirm the echoed filename
        echo_name = receive_file_name(conn, self.logger)
        if not echo_name:
            self.logger.error("Failed to receive echoed image name from client.")
            return False
        elif echo_name != img_name:
            self.logger.error("File name mismatch! Aborting transfer.")
            return False
        else:
            self.logger.info(f"Client confirmed image name {img_name}.")

        # Send size plus newline
        send_file_size(conn, img_size, self.logger)
        self.logger.info(f"Sent file size {img_size} to client.")

        # Receive the echoed size back and confirm
        echoed_size_str = receive_file_size(conn, self.logger)
        if not echoed_size_str:
            self.logger.error("Failed to receive echoed size from client (connection closed).")
            return False
        try:
            echoed_size = int(echoed_size_str)      # Try to parse it into an integer
            if echoed_size != img_size:  # Confirm they match
                self.logger.error("File size mismatch! Aborting transfer.")
                return False
            else:
                self.logger.info("File size confirmed. Proceeding with file transfer.")
        except ValueError:
            self.logger.error(f"Invalid size echoed: '{echoed_size_str}'.")
            return False

        # Send the file data in chunks
        offset = 0
        while offset < img_size:
            end = offset + chunk_size
            chunk = image_data[offset:end]
            conn.sendall(chunk)
            offset = end
        self.logger.info("File transfer complete.")
        self.logger.info("Waiting for new command...")

    def handle_client(self, conn):
        """Handle client connection in a thread-safe manner"""
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
                    # Request color coordinates from client
                    conn.sendall("PLEASE SEND RGB".encode('utf-8'))
                    self.logger.info("Sent color request to client.")

                    # Receive and process RGB values
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
        """Start the server with clean error handling"""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            server.bind((self.server_ip, self.port))
            server.listen(5)
            self.logger.info(f"Server started on {self.server_ip}:{self.port}.")
            self.logger.info("Waiting for connection...")

            while True:
                # Accept the connection from client
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
