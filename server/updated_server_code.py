import yaml
from time import sleep
from pathlib import Path
from server import CameraServer
from PCA9685 import PCA9685
from libcamera import controls

script_dir = Path(__file__).resolve().parent

with open(script_dir / 'server_settings.yaml', 'r') as file:
    data = yaml.safe_load(file)
    buffer_size = data["BufferSize"]
    server_port = data["ServerPort"]


class PHTestServer(CameraServer):
    def __init__(self, host="0.0.0.0", port=server_port):
        super().__init__(host, port)


if __name__ == "__main__":
    server = PHTestServer()
    server.start_server()
