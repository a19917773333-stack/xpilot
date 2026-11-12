#!/usr/bin/env python3
"""Runtime Chestnut recovery policy check.

Failure cases listed before implementation:
- C1 recovery fires without a prior big-model failure
- C2 USB2, missing USB, or an unstable USB link starts a retry
- C3 a retry starts while the vehicle is engaged, active, or moving
- C4 the link becomes safe for less than the settle window and still starts a retry
- C5 one failure starts more than one retry
- C6 a non-USB model failure is treated as a recoverable link failure
"""
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "openpilot/sunnypilot/modeld_v2/recovery.py"


def load_module():
  spec = importlib.util.spec_from_file_location("chestnut_recovery", MODULE)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {MODULE}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def main() -> int:
  errors = []

  try:
    module = load_module()
    recovery = module.ChestnutRecovery(settle_time=5.0)
  except Exception as exc:
    errors.append(f"C1 recovery module unavailable: {exc!r}")
    print(json.dumps({"errors": errors}, indent=1))
    return 1

  if module.is_chestnut_link_error(RuntimeError("model output not finite")):
    errors.append("C6 non-USB model error classified as recoverable")
  if not module.is_chestnut_link_error(RuntimeError("AMD failed with -4")):
    errors.append("C6 USB no-device error not recognized")

  if recovery.ready(0.0, usb_ready=True, safe_to_cycle=True):
    errors.append("C1 recovery fired without a failure")

  recovery.failed()
  for now, usb_ready, safe in ((0.0, False, True), (6.0, True, False), (12.0, True, True), (16.9, True, True)):
    if recovery.ready(now, usb_ready=usb_ready, safe_to_cycle=safe):
      errors.append(f"C2/C3/C4 recovery fired at {now} usb_ready={usb_ready} safe={safe}")

  if not recovery.ready(17.0, usb_ready=True, safe_to_cycle=True):
    errors.append("C4 recovery did not fire after the settle window")

  if recovery.ready(40.0, usb_ready=True, safe_to_cycle=True):
    errors.append("C5 recovery fired twice for one failure")

  recovery.failed()
  recovery.ready(50.0, usb_ready=True, safe_to_cycle=True)
  if recovery.ready(54.9, usb_ready=True, safe_to_cycle=True):
    errors.append("C2 unstable link fired before settling")
  if recovery.ready(55.0, usb_ready=False, safe_to_cycle=True):
    errors.append("C2 USB drop did not reset the settle window")
  if recovery.ready(61.0, usb_ready=True, safe_to_cycle=True):
    errors.append("C4 recovery reused time from before the USB drop")
  if not recovery.ready(66.0, usb_ready=True, safe_to_cycle=True):
    errors.append("C4 recovery did not restart the settle window after USB returned")

  print(json.dumps({"errors": errors}, indent=1))
  return 1 if errors else 0


if __name__ == "__main__":
  raise SystemExit(main())
