#!/usr/bin/env python3
"""End-to-end loopback: simulate a Quest controller over the real WebSocket and
verify VRTeleop.get_action() + XLeRobotVRController produce a valid robot action.
No headset, no robot hardware. Proves the server/data pipeline independently."""
import asyncio
import json
import ssl
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import websockets  # noqa: E402

from lerobot_vr_teleop import VRTeleop, VRTeleopConfig, XLeRobotVRController  # noqa: E402
from lerobot_vr_teleop.xlerobot_vr_controller import ARM_JOINTS  # noqa: E402

WS, HTTPS = 9442, 9443


def controller_blob(px, py, pz, trig=0.0, tx=0.0, ty=0.0):
    return {
        "position": {"x": px, "y": py, "z": pz},
        "rotation": {"x": 0, "y": 0, "z": 0},
        "quaternion": {"x": 0, "y": 0, "z": 0, "w": 1},
        "trigger": trig,
        "thumbstick": {"x": tx, "y": ty},
        "buttons": {},
        "gripActive": False,
    }


def packet(px, py, pz, **kw):
    c = controller_blob(px, py, pz, **kw)
    return json.dumps(
        {"timestamp": 0, "leftController": c, "rightController": dict(c), "headset": {"position": None}}
    )


async def fake_quest():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    async with websockets.connect(f"wss://localhost:{WS}", ssl=ctx) as ws:
        # 1st packet sets origin; later packets stream absolute positions + trigger.
        for p in [
            packet(0.30, 0.20, 0.10),
            packet(0.32, 0.22, 0.08, trig=0.9),
            packet(0.34, 0.24, 0.06, trig=0.9, tx=0.8),
        ]:
            await ws.send(p)
            await asyncio.sleep(0.25)
        await asyncio.sleep(0.3)


def main():
    teleop = VRTeleop(VRTeleopConfig(websocket_port=WS, https_port=HTTPS))
    teleop.connect()
    print("STEP 1 — VRTeleop connected, servers up:", teleop.is_connected)

    print("STEP 2 — before any data, right.valid =", teleop.get_action()["right"]["valid"])

    asyncio.run(fake_quest())
    time.sleep(0.3)

    action_goals = teleop.get_action()
    rg = action_goals["right"]
    print("STEP 3 — after simulated Quest packets:")
    print("         right.valid        =", rg["valid"])
    print("         right.target_pos   =", rg["target_position"])
    print("         right.trigger      =", rg["trigger"])

    obs = {f"{s}_arm_{j}.pos": 0.0 for s in ("left", "right") for j in ARM_JOINTS}
    obs.update({"head_motor_1.pos": 0.0, "head_motor_2.pos": 0.0})
    ctrl = XLeRobotVRController(obs, enable_left=False, enable_head=False, enable_base=False, kp=0.8)
    # Two passes: first seeds baseline, second produces motion.
    ctrl.goals_to_action(action_goals, obs)
    act = ctrl.goals_to_action(action_goals, obs)
    print("STEP 4 — controller action (right arm):")
    for k in [f"right_arm_{j}.pos" for j in ARM_JOINTS]:
        print(f"         {k:30s} = {act[k]:.3f}")

    teleop.disconnect()
    ok = rg["valid"] and rg["target_position"] is not None
    print("\nRESULT:", "PIPELINE OK ✅" if ok else "PIPELINE BROKEN ❌")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
