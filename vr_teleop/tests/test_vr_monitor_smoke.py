"""No-hardware smoke tests for the XLeVR bridge and asset resolution."""

import pytest


def test_xlevr_paths_resolve():
    paths = pytest.importorskip("lerobot_vr_teleop.xlevr_paths")
    root = paths.xlevr_root()
    assert (root / "xlevr" / "__init__.py").is_file()
    assert paths.web_ui_dir(root).is_dir()
    certfile, keyfile = paths.cert_paths(root)
    assert certfile.is_file() and keyfile.is_file()


def test_vr_monitor_initializes_print_only():
    # XLeVR pulls in websockets + scipy; skip cleanly if they (or the submodule) are absent.
    pytest.importorskip("websockets")
    pytest.importorskip("scipy")
    from lerobot_vr_teleop.xlevr_paths import xlevr_root

    try:
        xlevr_root()
    except FileNotFoundError:
        pytest.skip("XLeVR submodule not initialized")

    from lerobot_vr_teleop.vr_monitor import VRMonitor

    # initialize() builds the config + servers but does NOT bind any port.
    monitor = VRMonitor(print_only=True, start_https_ui=False)
    assert monitor.initialize() is True
    assert monitor.config is not None
    # Cert paths handed to XLeVR must be absolute (cwd-independent).
    assert monitor.config.certfile.endswith("cert.pem")
    assert monitor.get_latest_goal_nowait("left") is None
