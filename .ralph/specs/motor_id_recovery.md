# Motor ID Recovery — XLeRobot

## Symptom
`examples/xlerobot/check_motors.py` reports 6 motors unreachable:
- bus1 `/dev/ttyACM0`: `left_arm_shoulder_pan` (id 1) flaky; `head_motor_1/2` (7,8) missing.
- bus2 `/dev/ttyACM1`: `right_arm_shoulder_pan` (id 1) flaky; base wheels (7,8,9) missing.

## Diagnosis (evidence)
- Repeated pings: ids 2–6 respond 5/5 on both buses; id 1 responds intermittently
  (1/5, 3/5); ids 7/8/9 never respond at any id or baud-rate.
- A **data read** of id 1 (`Present_Position` / `Model_Number`) fails 6/6 on both
  buses with `ConnectionError`, while a short ping occasionally succeeds.
- Only two USB-serial boards exist (`1a86:55d3` ×2), so head/base are daisy-chained
  on the arm ports, not on separate ports.

Conclusion: the head and base motors are still at the **factory-default id 1** and
collide with `shoulder_pan` (also id 1). A short ping sometimes slips through; a
longer data transfer always garbles. Counts fit exactly:
- bus1 = {1×3 (pan+head1+head2), 2,3,4,5,6} = 8 motors.
- bus2 = {1×4 (pan+3 wheels), 2,3,4,5,6} = 9 motors.
The flakiness proves these motors are **powered and alive** — they only need IDs.

## Why it needs one motor at a time
Two motors sharing id 1 cannot be addressed individually over a half-duplex serial
bus — there is no unique handle. Writing the ID register addresses *by current id*,
so it would hit every motor at id 1 at once. Therefore each mis-ID'd motor must be
the only motor on the bus when its id is set. (This matches both the lerobot
`lerobot-setup-motors` flow and the XLeRobot/Bambot docs: "connect motors one by one".)

## Target id map (from the XLeRobot driver, `src/lerobot/robots/xlerobot/xlerobot.py`)
- bus1 `/dev/ttyACM0`: left arm 1–6, `head_motor_1`=7, `head_motor_2`=8.
- bus2 `/dev/ttyACM1`: right arm 1–6, `base_left_wheel`=7, `base_back_wheel`=8, `base_right_wheel`=9.
Arms (ids 1–6) are already correct; only the 5 motors above need assigning.

## Procedure
For each of the 5 motors: isolate it (only that motor electrically on the bus —
unplug the rest of the chain or wire the single motor straight to the board), then:
```bash
# head (bus1)
python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM0 --id 7   # head_motor_1
python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM0 --id 8   # head_motor_2
# base (bus2)
python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM1 --id 7   # base_left_wheel
python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM1 --id 8   # base_back_wheel
python examples/xlerobot/assign_motor_ids.py --port /dev/ttyACM1 --id 9   # base_right_wheel
```
`assign_motor_ids.py` refuses to write unless exactly one motor is present AND a
repeated data read is clean (this catches "two motors still at id 1"). It then uses
lerobot's tested `setup_motor` to write the id + default baud-rate to EEPROM.

Re-assemble the full chains and verify:
```bash
python examples/xlerobot/check_motors.py   # exits 0 only when all 17 respond
```

Official alternative (rewrites ALL 17 ids, more replugging):
```bash
lerobot-setup-motors --robot.type=xlerobot --robot.port1=/dev/ttyACM0 --robot.port2=/dev/ttyACM1
```

## Note
This last step is physically gated (a human must isolate each motor); it cannot be
done purely in software because of the shared-bus addressing constraint above.
