import os
import yaml
import socket
import threading
from datetime import datetime
from time import sleep
from pathlib import Path
from picamera2 import Picamera2
from libcamera import controls
import board
import neopixel
from logger import get_logger
from socket_utils import send_file_name, receive_file_name
from socket_utils import send_file_size, receive_file_size

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
    LED backlight. The client can request photos, change LED backlight, and control motors.
    """
    def __init__(self, host="0,0,0,0", port=server_port, init_camera=True, init_motor=True, resolution=None):
        self.host = host
        self.port = port
        self.logger = self._setup_logger()
        self.server_ip = self._get_server_ip()
        self.led = self._init_led()
        self.resolution_preference = resolution
        self.cam = self._init_cam() if init_camera else None
        self.color = (10, 10, 10)    # Default LED configuration
        self.camera_lock = threading.Lock()     # Thread lock
        
        # Motor control (for pH testing automation)
        self.motor_driver = self._init_motor_driver() if init_motor else None
        self.PWMA = 0
        self.AIN1 = 1
        self.AIN2 = 2

    @staticmethod
    def _setup_logger():
        return get_logger("WirelessCameraLogger")

    def _get_server_ip(self):
        import os
        
        # Check for manual IP override via environment variable
        manual_ip = os.getenv('PIZEROCAM_SERVER_IP')
        if manual_ip:
            self.logger.info(f"Using manual IP override: {manual_ip}")
            return manual_ip
        
        # Try to detect Tailscale IP
        tailscale_ip = self._detect_tailscale_ip()
        if tailscale_ip:
            return tailscale_ip
        
        # Fall back to original method
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s_test:
                s_test.connect(("8.8.8.8", 80))
                server_ip = s_test.getsockname()[0]
                self.logger.info(f"Using socket-detected IP address: {server_ip}")
                return server_ip
        except Exception as e:
            self.logger.error(f"Failed to detect IP address: {e}")
            return "localhost"
    
    def _detect_tailscale_ip(self):
        """Detect Tailscale IP address using multiple methods"""
        # Method 1: Try netifaces (most reliable)
        tailscale_ip = self._get_tailscale_ip_netifaces()
        if tailscale_ip:
            return tailscale_ip
        
        # Method 2: Try tailscale command
        tailscale_ip = self._get_tailscale_ip_command()
        if tailscale_ip:
            return tailscale_ip
        
        # Method 3: Check for tailscale0 interface manually
        tailscale_ip = self._get_tailscale_ip_manual()
        if tailscale_ip:
            return tailscale_ip
        
        self.logger.info("No Tailscale IP detected")
        return None
    
    def _get_tailscale_ip_netifaces(self):
        """Get Tailscale IP using netifaces library"""
        try:
            import netifaces
            
            interfaces = netifaces.interfaces()
            for interface in interfaces:
                try:
                    # Check for tailscale interface names
                    if 'tailscale' in interface.lower() or interface == 'utun10':
                        addrs = netifaces.ifaddresses(interface)
                        if netifaces.AF_INET in addrs:
                            for addr_info in addrs[netifaces.AF_INET]:
                                ip = addr_info.get('addr')
                                if ip and ip.startswith('100.'):
                                    self.logger.info(f"Found Tailscale IP via netifaces: {ip}")
                                    return ip
                    
                    # Also check all interfaces for 100.x.x.x addresses
                    addrs = netifaces.ifaddresses(interface)
                    if netifaces.AF_INET in addrs:
                        for addr_info in addrs[netifaces.AF_INET]:
                            ip = addr_info.get('addr')
                            if ip and ip.startswith('100.'):
                                self.logger.info(f"Found Tailscale IP via netifaces: {ip}")
                                return ip
                except (ValueError, KeyError):
                    continue
        except ImportError:
            self.logger.warning("netifaces not available, trying other methods")
        return None
    
    def _get_tailscale_ip_command(self):
        """Get Tailscale IP using tailscale command"""
        try:
            import subprocess
            result = subprocess.run(['tailscale', 'ip'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                ip = result.stdout.strip()
                if ip and ip.startswith('100.'):
                    self.logger.info(f"Found Tailscale IP via command: {ip}")
                    return ip
        except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None
    
    def _get_tailscale_ip_manual(self):
        """Get Tailscale IP by parsing network interfaces manually"""
        try:
            import subprocess
            # Try to get IP from tailscale0 interface
            result = subprocess.run(['ip', 'addr', 'show', 'tailscale0'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if 'inet ' in line and '100.' in line:
                        ip = line.split('inet ')[1].split('/')[0]
                        self.logger.info(f"Found Tailscale IP via manual method: {ip}")
                        return ip
        except (subprocess.SubprocessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return None

    def _init_led(self):
        # NeoPixel LED RING with 12 pixels MUST use board.D10
        led = neopixel.NeoPixel(board.D10, 12, auto_write=True)

        # Blink to show initialization
        for i in range(0, 3):
            led.fill((100, 100, 100))
            sleep(0.5)
            led.fill((0, 0, 0))
        self.logger.info("LED initialized!")
        return led
    
    def _init_motor_driver(self):
        """Initialize PCA9685 motor driver for pH testing automation."""
        try:
            from .PCA9685 import PCA9685
            self.logger.info("Attempting to initialize motor driver...")
            pwm = PCA9685(0x40, debug=False)
            pwm.setPWMFreq(50)
            self.logger.info("Motor driver initialized successfully.")
            return pwm
        except Exception as e:
            self.logger.error(f"Failed to initialize motor driver: {e}")
            self.logger.warning("Motor functionality will be disabled")
            return None

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
    
    def run_motor(self):
        """
        Run motor A for 1 second at 50% speed.
        Used for pH strip dispensing/positioning automation.
        
        Returns:
            bool: True if motor ran successfully, False otherwise
        """
        try:
            if self.motor_driver is None:
                self.logger.error("Motor driver not initialized - cannot run motor")
                return False
                
            self.logger.info("Running motor...")
            # Set speed to 50%
            self.motor_driver.setDutycycle(self.PWMA, 50)
            
            # Set direction to forward
            self.motor_driver.setLevel(self.AIN1, 0)
            self.motor_driver.setLevel(self.AIN2, 1)
            sleep(1)
            
            # Stop motor
            self.motor_driver.setDutycycle(self.PWMA, 0)
            self.logger.info("Motor run complete.")
            return True
        except Exception as e:
            self.logger.error(f"Motor run failed: {e}")
            return False

    def _init_cam(self):
        self.logger.info("Initializing camera session")
        cam = Picamera2(0)
        
        # Define resolution mappings
        resolution_map = {
            "max": (4608, 2592),   # Maximum sensor resolution
            "4k": (3840, 2160),    # 4K resolution
            "fhd": (1920, 1080),   # Full HD
            "hd": (1280, 720),     # HD
            "vga": (640, 480),     # VGA
        }
        
        # Get resolutions in order of preference
        if self.resolution_preference and self.resolution_preference in resolution_map:
            # User specified a resolution - try that first
            preferred_res = resolution_map[self.resolution_preference]
            resolutions = [preferred_res]
            # Add fallbacks (smaller resolutions)
            fallback_resolutions = [
                (4608, 2592),  # Maximum sensor resolution
                (1920, 1080),  # Full HD
                (1280, 720),   # HD  
                (640, 480),    # VGA
            ]
            for res in fallback_resolutions:
                if res != preferred_res and res not in resolutions:
                    resolutions.append(res)
        else:
            # Default resolution order
            resolutions = [
                (4608, 2592),  # Maximum sensor resolution
                (1920, 1080),  # Full HD
                (1280, 720),   # HD  
                (640, 480),    # VGA
            ]
        
        for width, height in resolutions:
            try:
                self.logger.info(f"Attempting camera configuration with {width}x{height}")
                config = cam.create_still_configuration(main={"size": (width, height)})
                cam.configure(config)
                
                if 'AfMode' in cam.camera_controls:
                    cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})
                    
                cam.start()
                self.logger.info(f"Camera initiated successfully with {width}x{height} resolution.")
                return cam
                
            except Exception as e:
                self.logger.warning(f"Failed to configure camera with {width}x{height}: {e}")
                continue
        
        # If all resolutions fail, try with default configuration
        try:
            self.logger.info("Attempting default camera configuration")
            config = cam.create_still_configuration()
            # Try to modify the config to use smaller size if possible
            if hasattr(config, 'main') and hasattr(config.main, 'size'):
                config.main.size = (640, 480)
            cam.configure(config)
            cam.start()
            self.logger.info("Camera initiated with default/fallback configuration.")
            return cam
        except Exception as e:
            self.logger.error(f"Failed to initialize camera with any configuration: {e}")
            raise

    def __del__(self):
        """
        Making sure the instance is destroyed when camera is closed
        """
        if hasattr(self, 'cam') and self.cam is not None:
            self.cam.stop()
            self.cam.close()
            self.logger.info(f"Camera closed.")

    def take_photo(self):
        # This function will instantiate a new camera instance every time
        try:
            if self.cam is None:
                self.logger.error("Camera not initialized - cannot take photo")
                return None
                
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
                sleep(5)           # Wait for auto-exposure and autofocus to settle
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

                elif msg == "RUN_MOTOR":
                    if self.run_motor():
                        conn.sendall("MOTOR_RUN_COMPLETE".encode('utf-8'))
                    else:
                        conn.sendall("MOTOR_RUN_FAILED".encode('utf-8'))

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
