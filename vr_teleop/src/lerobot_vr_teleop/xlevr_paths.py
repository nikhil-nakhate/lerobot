#!/usr/bin/env python3
"""Locate the vendored XLeVR submodule and its assets without relying on the
current working directory.

The legacy prototype (``examples/vr_monitor.py``) hardcoded an absolute path and
called ``os.chdir`` into the XLeVR checkout so that cwd-relative lookups for the
``web-ui/`` assets and ``cert.pem``/``key.pem`` would resolve. That corrupts the
parent process's working directory (breaking dataset ``root=`` paths and
``/dev/...`` device resolution).

Instead we resolve everything from the package location (or an explicit
override / ``XLEVR_ROOT`` env var) and make ``xlevr`` importable by adding the
submodule to ``sys.path`` -- no ``os.chdir``, no cwd dependence.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# vr_teleop/src/lerobot_vr_teleop/xlevr_paths.py
#   parents[0] -> lerobot_vr_teleop
#   parents[1] -> src
#   parents[2] -> vr_teleop
#   parents[3] -> repo root (contains third_party/XLeRobot/XLeVR)
_DEFAULT_SUBMODULE_XLEVR = Path(__file__).resolve().parents[3] / "third_party" / "XLeRobot" / "XLeVR"

_ENV_VAR = "XLEVR_ROOT"


def _looks_like_xlevr(path: Path) -> bool:
    return (path / "xlevr" / "__init__.py").is_file()


def xlevr_root(override: str | os.PathLike | None = None) -> Path:
    """Return the absolute path to the XLeVR package root.

    Resolution order: explicit ``override`` arg, ``XLEVR_ROOT`` env var, then the
    in-repo submodule at ``third_party/XLeRobot/XLeVR``. Raises ``FileNotFoundError``
    with actionable guidance if none is found.
    """
    candidates: list[Path] = []
    if override is not None:
        candidates.append(Path(override).expanduser().resolve())
    env_root = os.environ.get(_ENV_VAR)
    if env_root:
        candidates.append(Path(env_root).expanduser().resolve())
    candidates.append(_DEFAULT_SUBMODULE_XLEVR)

    for candidate in candidates:
        if _looks_like_xlevr(candidate):
            return candidate

    raise FileNotFoundError(
        "Could not locate the XLeVR package. Expected it at "
        f"'{_DEFAULT_SUBMODULE_XLEVR}'. Initialize the submodule with:\n"
        "    git submodule update --init --recursive\n"
        f"or set the {_ENV_VAR} environment variable / pass xlevr_root explicitly."
    )


def web_ui_dir(root: Path | None = None) -> Path:
    """Directory of static WebXR assets served to the headset browser."""
    root = root if root is not None else xlevr_root()
    return root / "web-ui"


def cert_paths(root: Path | None = None) -> tuple[Path, Path]:
    """Absolute ``(certfile, keyfile)`` paths for the HTTPS/WSS servers."""
    root = root if root is not None else xlevr_root()
    return root / "cert.pem", root / "key.pem"


def ensure_importable(root: Path | None = None) -> Path:
    """Make ``import xlevr`` work by adding the submodule to ``sys.path``.

    No ``os.chdir`` and no ``PYTHONPATH`` mutation -- only a controlled
    ``sys.path`` entry. Idempotent. Returns the resolved root.
    """
    root = root if root is not None else xlevr_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root
