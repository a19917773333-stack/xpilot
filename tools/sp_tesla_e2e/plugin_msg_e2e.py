#!/usr/bin/env python3
"""Migration acceptance through real pluginMsg IPC (no device or Params writes).

Failure cases listed before implementation:
- Card cannot deliver two 100 Hz streams alongside 20 Hz plan diagnostics.
- A second publishing process displaces card or is rejected itself.
- JSON loses raw CAN bytes, source/kind identity, or expiry.

Prints the repeatable evidence as JSON; exit 1 means the migration is blocked.
"""
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from openpilot.cereal import custom, messaging
from openpilot.tesla import plugins


def second_publisher(connection):
  faults = []
  plugins.record_fault = lambda *args: faults.append(str(args[-1]))
  plugin = SimpleNamespace(NAME="traffic_light", CLAIMS=("msg:traffic.plan",))
  try:
    pm = messaging.PubMaster(["pluginMsg"])
    sent = plugins.send_msg(pm, plugin, "traffic.plan", {"sample": 1}, 350)
    connection.send({"sent": sent, "faults": faults})
  except messaging.MultiplePublishersError as error:
    connection.send({"sent": False, "faults": [repr(error)]})


def measure():
  faults = []
  plugins.record_fault = lambda *args: faults.append(str(args[-1]))
  traffic = custom.TeslaTrafficControl.new_message().to_dict()
  traffic["rawPayload"] = "0123456789abcdef"
  streams = [
    ("traffic_light", "traffic.observation", traffic, 100, 750),
    ("bms", "battery.state", custom.TeslaBattery.new_message().to_dict(), 100, 2000),
    ("traffic_light", "traffic.plan", custom.TeslaTrafficControlPlan.new_message().to_dict(), 20, 350),
  ]
  pm = messaging.PubMaster(["pluginMsg"])
  reader = plugins.PluginMsgs()
  counts = {kind: 0 for _, kind, _, _, _ in streams}
  sizes = {}
  start = time.monotonic()
  for tick in range(100):
    time.sleep(max(0, start + tick / 100 - time.monotonic()))
    for source, kind, payload, hz, expiry in streams:
      if tick % (100 // hz):
        continue
      payload = {**payload, "sample": tick}
      plugin = SimpleNamespace(NAME=source, CLAIMS=(f"msg:{kind}",))
      assert plugins.send_msg(pm, plugin, kind, payload, expiry), faults
      deadline = time.monotonic() + 1
      while reader.fresh(kind).get(source) != payload:
        assert time.monotonic() < deadline, (source, kind, tick)
        time.sleep(0.001)
      counts[kind] += 1
      event = messaging.new_message("pluginMsg")
      event.pluginMsg = {"source": source, "kind": kind, "payload": json.dumps(payload), "validForMs": expiry}
      sizes[kind] = len(event.to_bytes())
  elapsed = time.monotonic() - start
  assert counts == {kind: hz for _, kind, _, hz, _ in streams}, counts
  assert not reader.fresh("traffic.observation", time.monotonic_ns() + 3_000_000_000)

  parent, child = multiprocessing.get_context("spawn").Pipe()
  process = multiprocessing.get_context("spawn").Process(target=second_publisher, args=(child,))
  process.start()
  assert parent.poll(10), "second publisher timed out"
  second = parent.recv()
  process.join(10)
  assert process.exitcode == 0, process.exitcode
  plugin = SimpleNamespace(NAME="bms", CLAIMS=("msg:battery.state",))
  first_survives = plugins.send_msg(pm, plugin, "battery.state", {"sample": 101}, 2000)
  return {"counts": counts, "elapsed_s": elapsed, "wire_bytes_per_message": sizes,
          "nominal_wire_bytes_per_second": sum(sizes[kind] * hz for _, kind, _, hz, _ in streams),
          "second_publisher": second, "first_publisher_survives": first_survives, "first_publisher_faults": faults,
          "migration_ready": second["sent"] and first_survives}


if __name__ == "__main__":
  shm = "/tmp" if sys.platform == "darwin" else "/dev/shm"
  with tempfile.TemporaryDirectory(prefix="msgq_x58_", dir=shm) as directory:
    os.environ["OPENPILOT_PREFIX"] = Path(directory).name.removeprefix("msgq_")
    result = measure()
  print(json.dumps(result, indent=2))
  sys.exit(0 if result["migration_ready"] else 1)
