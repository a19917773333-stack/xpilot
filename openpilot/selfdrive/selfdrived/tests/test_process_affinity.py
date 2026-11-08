"""Guard selfdrived's startup scheduling configuration.

Failure modes:
- selfdrived requests the old CPU4 affinity.
- SelfdriveD is constructed before realtime scheduling and affinity are configured.
- the process no longer requests the control-loop realtime priority.
"""
from unittest.mock import patch

from openpilot.common.test import OpenpilotTestCase
import openpilot.selfdrive.selfdrived.selfdrived as selfdrived_module


class TestSelfdriveDProcessAffinity(OpenpilotTestCase):
  def test_main_configures_realtime_process_before_startup(self):
    startup_order = []

    def config_realtime_process(cores, priority):
      startup_order.append(("config", cores, priority))

    class StubSelfdriveD:
      def __init__(self):
        startup_order.append(("init",))

      def run(self):
        startup_order.append(("run",))

    with patch.object(selfdrived_module, "config_realtime_process", side_effect=config_realtime_process), \
         patch.object(selfdrived_module, "SelfdriveD", StubSelfdriveD):
      selfdrived_module.main()

    assert startup_order == [
      ("config", 6, selfdrived_module.Priority.CTRL_HIGH),
      ("init",),
      ("run",),
    ]
