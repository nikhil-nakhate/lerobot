# VR Teleoperation for XLeRobot

WebXR-based virtual-reality teleoperation for the **XLeRobot** dual-arm mobile
manipulator (two SO101 arms + 2-DOF head + 3-omniwheel holonomic base).

You drive the robot from a VR headset browser (e.g. Meta Quest): the controller
poses move the arm end-effectors via inverse kinematics, the triggers actuate the
grippers, and the thumbsticks pan the head and drive the base.

## Layout

```
vr_teleop/
├── src/lerobot_vr_teleop/
│   ├── xlevr_paths.py            # locate the XLeVR submodule + its assets (no cwd reliance)
│   ├── vr_monitor.py             # XLeVR WebSocket + HTTPS bridge -> latest controller goals
│   ├── config_vr_teleop.py       # VRTeleopConfig
│   ├── teleop_vr.py              # VRTeleop(Teleoperator): robot-agnostic VR goals
│   ├── xlerobot_vr_controller.py # XLeRobotVRController: goals -> XLerobot action (IK lives here)
│   └── recording.py              # LeRobot dataset recording helpers
├── examples/
│   ├── teleop_xlerobot_vr.py            # real-time teleop
│   └── record_xlerobot_vr_dataset.py   # teleop + dataset recording
└── tests/                        # no-hardware unit + smoke tests
```

The VR input stack (`xlevr` package, `web-ui/` WebXR front-end, SSL certs) lives in
the **XLeRobot** repository, vendored as a git submodule at the repo root:
`third_party/XLeRobot` (provides `third_party/XLeRobot/XLeVR`).

## Design

`VRTeleop` is a first-class, **robot-agnostic** `lerobot` `Teleoperator`: its
`get_action()` returns raw VR goals (controller positions in meters, wrist angles
in degrees, trigger/thumbstick values) for each enabled controller — never robot
joint angles.

`XLeRobotVRController` is the **XLeRobot-specific** mapper that turns those goals
into a flat action dict (`left_arm_*.pos`, `right_arm_*.pos`, `head_motor_*.pos`,
`x.vel`/`y.vel`/`theta.vel`) using `SO101Kinematics` IK and the wrist-coupling
convention `wrist_flex = -shoulder_lift - elbow_flex + pitch`. It holds no robot
reference — the caller passes the current observation in and gets an action out.

## Setup

```bash
# 1. Fetch the XLeVR submodule (provides the xlevr package + web-ui + certs)
git submodule update --init --recursive

# 2. Install the VR teleop package + the xlevr submodule
pip install -e vr_teleop
pip install -e third_party/XLeRobot/XLeVR   # or rely on the example bootstrap

# 3. Run a demo
python vr_teleop/examples/teleop_xlerobot_vr.py
```

Then open the printed `https://<ip>:8443` URL in the headset browser and accept the
self-signed certificate. If your `xlevr` checkout is elsewhere, set `XLEVR_ROOT` or
pass `xlevr_root=...` in `VRTeleopConfig`.

> The example scripts add `vr_teleop/src` to `sys.path` for convenience, so step 2's
> `pip install -e vr_teleop` is optional for running them. The `xlevr` submodule is
> located and imported automatically by `xlevr_paths`.

## Tests (no hardware required)

```bash
pytest vr_teleop/tests
```

`test_xlerobot_vr_controller.py` verifies the IK/mapping deterministically (IK
round-trips, wrist coupling, gripper threshold, base signs, first-frame baseline).
`test_vr_monitor_smoke.py` verifies the XLeVR bridge initializes and resolves its
assets (skipped if the submodule / its deps are absent).

## Safe on-robot bring-up

1. Set `XLerobotConfig.max_relative_target` to a small scalar to clamp per-step deltas.
2. Start with the right arm only (`ENABLE_LEFT=False, ENABLE_HEAD=False, ENABLE_BASE=False`).
3. `reset_to_zero()` and confirm slow tracking at low `kp` before engaging deltas.
4. Verify the gripper, then enable the head, then the base last.
5. Keep `disable_torque_on_disconnect=True` so faults drop torque.
