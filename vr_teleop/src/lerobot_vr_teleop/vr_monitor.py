#!/usr/bin/env python3
"""VR monitor bridge between the XLeVR WebSocket/WebXR stack and lerobot.

This is a cleaned-up port of the prototype ``examples/vr_monitor.py``. The key
differences:

* No ``os.chdir`` and no ``PYTHONPATH`` mutation. The XLeVR package is made
  importable via :func:`lerobot_vr_teleop.xlevr_paths.ensure_importable`, and all
  assets (the ``web-ui/`` static files and the SSL ``cert.pem``/``key.pem``) are
  resolved to absolute paths from the submodule location -- not the cwd.
* :class:`VRMonitor` is parameterized (ports, host, scale, print-only) so the
  :class:`~lerobot_vr_teleop.teleop_vr.VRTeleop` teleoperator can configure it.
* The thread-safe ``get_latest_goal_nowait`` / ``get_left_goal_nowait`` /
  ``get_right_goal_nowait`` API is preserved so existing consumers work unchanged.
"""

from __future__ import annotations

import asyncio
import http.server
import logging
import socket
import ssl
import threading
from pathlib import Path

from .xlevr_paths import cert_paths, ensure_importable, web_ui_dir, xlevr_root

logger = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Best-effort local IP for printing the headset connection URL."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "localhost"


def import_xlevr_modules(root: Path):
    """Import the XLeVR modules after ensuring the submodule is on ``sys.path``."""
    ensure_importable(root)
    from xlevr.config import XLeVRConfig
    from xlevr.inputs.base import ControlGoal, ControlMode
    from xlevr.inputs.vr_ws_server import VRWebSocketServer

    return XLeVRConfig, VRWebSocketServer, ControlGoal, ControlMode


class SimpleAPIHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTPS handler serving the WebXR front-end from ``web-ui/``."""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Never let the headset cache the WebXR assets, so JS fixes always load.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        try:
            super().end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ssl.SSLError):
            pass

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002 - signature defined by stdlib
        pass  # silence per-request HTTP logging

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.serve_file("index.html", "text/html")
        elif self.path.endswith(".css"):
            self.serve_file(self.path.lstrip("/"), "text/css")
        elif self.path.endswith(".js"):
            self.serve_file(self.path.lstrip("/"), "application/javascript")
        elif self.path.endswith(".ico"):
            self.serve_file(self.path.lstrip("/"), "image/x-icon")
        elif self.path.endswith((".jpg", ".jpeg", ".png", ".gif")):
            if self.path.endswith((".jpg", ".jpeg")):
                content_type = "image/jpeg"
            elif self.path.endswith(".png"):
                content_type = "image/png"
            else:
                content_type = "image/gif"
            self.serve_file(self.path.lstrip("/"), content_type)
        else:
            self.send_error(404, "Not found")

    def serve_file(self, rel_path: str, content_type: str):
        web_root = Path(getattr(self.server, "web_root_path"))
        # Resolve and confine the request to the web root (no path traversal).
        file_path = (web_root / rel_path).resolve()
        try:
            file_path.relative_to(web_root.resolve())
        except ValueError:
            self.send_error(403, "Forbidden")
            return
        if not file_path.is_file():
            self.send_error(404, f"File not found: {rel_path}")
            return
        try:
            content = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error("Error serving file %s: %s", rel_path, e)
            self.send_error(500, "Internal server error")


class SimpleHTTPSServer:
    """HTTPS server that serves the WebXR UI from an absolute web-ui directory."""

    def __init__(self, host_ip: str, https_port: int, web_root: Path, certfile: Path, keyfile: Path):
        self.host_ip = host_ip
        self.https_port = https_port
        self.web_root = Path(web_root)
        self.certfile = Path(certfile)
        self.keyfile = Path(keyfile)
        self.httpd: http.server.HTTPServer | None = None
        self.server_thread: threading.Thread | None = None

    async def start(self):
        self.httpd = http.server.HTTPServer((self.host_ip, self.https_port), SimpleAPIHandler)
        # Stash the absolute web root on the server so the handler can read it.
        self.httpd.web_root_path = str(self.web_root)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.certfile), str(self.keyfile))
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)

        self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.server_thread.start()
        logger.info("HTTPS server started on %s:%s", self.host_ip, self.https_port)

    async def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            if self.server_thread:
                self.server_thread.join(timeout=5)
            logger.info("HTTPS server stopped")
            self.httpd = None


class VRMonitor:
    """Owns the XLeVR WebSocket + HTTPS servers and exposes the latest goals.

    Goals are stored per controller (``left`` / ``right`` / ``headset``) and read
    back in a thread-safe manner via :meth:`get_latest_goal_nowait`.
    """

    def __init__(
        self,
        *,
        https_port: int = 8443,
        websocket_port: int = 8442,
        host_ip: str = "0.0.0.0",
        vr_to_robot_scale: float = 1.0,
        print_only: bool = False,
        start_https_ui: bool = True,
        xlevr_root: str | Path | None = None,
    ):
        self.https_port = https_port
        self.websocket_port = websocket_port
        self.host_ip = host_ip
        self.vr_to_robot_scale = vr_to_robot_scale
        self.print_only = print_only
        self.start_https_ui = start_https_ui
        self._xlevr_root_override = xlevr_root

        self.config = None
        self.vr_server = None
        self.https_server: SimpleHTTPSServer | None = None
        self.command_queue: asyncio.Queue | None = None
        self.is_running = False

        self.latest_goal = None
        self.left_goal = None
        self.right_goal = None
        self.headset_goal = None
        self._goal_lock = threading.Lock()

    def initialize(self) -> bool:
        """Resolve XLeVR, build its config, and construct the servers."""
        root = xlevr_root(self._xlevr_root_override)
        certfile, keyfile = cert_paths(root)
        if not certfile.is_file() or not keyfile.is_file():
            logger.error("SSL certificates not found at %s / %s", certfile, keyfile)
            return False

        try:
            XLeVRConfig, VRWebSocketServer, _ControlGoal, _ControlMode = import_xlevr_modules(root)
        except ImportError as e:
            logger.error("Failed to import xlevr modules: %s", e)
            return False

        # Construct the config explicitly with absolute paths so XLeVR never
        # depends on the current working directory.
        self.config = XLeVRConfig(
            https_port=self.https_port,
            websocket_port=self.websocket_port,
            host_ip=self.host_ip,
            certfile=str(certfile),
            keyfile=str(keyfile),
            enable_vr=True,
            enable_keyboard=False,
            enable_https=self.start_https_ui,
            vr_to_robot_scale=self.vr_to_robot_scale,
        )

        self.command_queue = asyncio.Queue()
        try:
            self.vr_server = VRWebSocketServer(
                command_queue=self.command_queue,
                config=self.config,
                print_only=self.print_only,
            )
        except Exception as e:
            logger.error("Failed to create VR WebSocket server: %s", e)
            return False

        if self.start_https_ui:
            self.https_server = SimpleHTTPSServer(
                host_ip=self.host_ip,
                https_port=self.https_port,
                web_root=web_ui_dir(root),
                certfile=certfile,
                keyfile=keyfile,
            )
        logger.info("XLeVR monitor initialized (root=%s)", root)
        return True

    async def start_monitoring(self):
        """Async entry point: start servers and consume the goal queue."""
        if not self.initialize():
            logger.error("Failed to initialize VR monitor")
            return
        try:
            if self.https_server is not None:
                await self.https_server.start()
            await self.vr_server.start()
            self.is_running = True

            host_display = get_local_ip() if self.host_ip == "0.0.0.0" else self.host_ip
            logger.info("VR monitor running. Open the headset browser at https://%s:%s", host_display, self.https_port)

            await self._monitor_commands()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Error in VR monitor: %s", e)
        finally:
            await self.stop_monitoring()

    async def _monitor_commands(self):
        while self.is_running:
            try:
                goal = await asyncio.wait_for(self.command_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            with self._goal_lock:
                if goal.arm == "left":
                    self.left_goal = goal
                elif goal.arm == "right":
                    self.right_goal = goal
                elif goal.arm == "headset":
                    self.headset_goal = goal
                self.latest_goal = goal

    def get_latest_goal_nowait(self, arm: str | None = None):
        """Return the latest goal(s). ``arm`` selects one; ``None`` returns a dict."""
        with self._goal_lock:
            if arm == "left":
                return self.left_goal
            if arm == "right":
                return self.right_goal
            if arm == "headset":
                return self.headset_goal
            return {
                "left": self.left_goal,
                "right": self.right_goal,
                "headset": self.headset_goal,
                "has_left": self.left_goal is not None,
                "has_right": self.right_goal is not None,
                "has_headset": self.headset_goal is not None,
            }

    def get_left_goal_nowait(self):
        return self.get_latest_goal_nowait("left")

    def get_right_goal_nowait(self):
        return self.get_latest_goal_nowait("right")

    async def stop_monitoring(self):
        self.is_running = False
        if self.vr_server:
            try:
                await self.vr_server.stop()
            except Exception as e:
                logger.warning("Error stopping VR WebSocket server: %s", e)
        if self.https_server:
            try:
                await self.https_server.stop()
            except Exception as e:
                logger.warning("Error stopping HTTPS server: %s", e)
        logger.info("VR monitor stopped")


def main():
    """Run the monitor standalone (useful for connecting/testing the headset)."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    monitor = VRMonitor()
    try:
        asyncio.run(monitor.start_monitoring())
    except KeyboardInterrupt:
        logger.info("VR monitor stopped by user")


if __name__ == "__main__":
    main()
