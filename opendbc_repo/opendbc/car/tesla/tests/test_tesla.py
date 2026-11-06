"""CarState failure cases:
CS1 stock Autosteer enabled no longer raises invalidLkasSetting (except MISSING_DAS_SETTINGS).
CS2 the SP extension changes the source invalidLkasSetting or another CarState field.
"""
import re
import unittest
from unittest.mock import patch

from opendbc.can import CANPacker
from opendbc.car import Bus, gen_empty_fingerprint
from opendbc.car.structs import CarParams, CarParamsSP
from opendbc.car.tesla.carstate import CarState
from opendbc.car.tesla.interface import CarInterface
from opendbc.car.tesla.fingerprints import FW_VERSIONS
from opendbc.car.tesla.radar_interface import RADAR_START_ADDR
from opendbc.car.tesla.values import CAR, DBC, DBC_2_BIT, CANBUS, TeslaFlags, TeslaSafetyFlags, get_dbc
from opendbc.sunnypilot.car.tesla.carstate_ext import CarStateExt
from opendbc.sunnypilot.car.tesla.values import TeslaFlagsSP

Ecu = CarParams.Ecu

# Fields prefixed unknown_* we observe structurally but don't know the meaning of.
# Only `platform` has evidence-backed semantic meaning (matches car_model in FW_VERSIONS).
#
# unknown_prefix is everything before the comma; we don't split it because we don't know what its
# parts mean, but observed shape is: <family>_<package>_<triplet> (<build>), e.g.
#   TeMYG4 _ Main     _ 0.0.0 (78)     or     TeM3 _ SP_XP002p2 _ 0.0.0 (23)
#   family   package    triplet build           family  package    triplet build
#
# After the comma, the version string decomposes into:
#   platform             : E/Y/X = car model (Model 3 / Y / X). The only field with known meaning.
#   variant_code         : differentiator WITHIN a platform — hardware/trim/calibration bits packed
#                          into <digit?><letters?><3-digit series>, e.g. '4HP015', '4003', 'L014',
#                          'PR003'. We don't fully know what the parts mean individually, but the
#                          whole string identifies a specific variant within the car model.
#   software_major/minor : numeric components after the first '.' — conventional release numbers.
#                          minor is optional (e.g. 'E4S014.27' has no minor).
#
# Suspected (not confirmed): for M3/MY, `TeM3_*` outer + no-leading-digit variant_code == HW3, and
# `TeMYG4_*` outer + leading-'4' variant_code == HW4 (the 'G4' in TeMYG4 likely denotes Gen 4).
#
# Example full parse of 'TeMYG4_Main_0.0.0 (78),E4HP015.05.0':
#   unknown_prefix='TeMYG4_Main_0.0.0 (78)'
#   platform=E  variant_code=4HP015  software_major=05  software_minor=0
FW_RE = re.compile(
  rb'^(?P<unknown_prefix>.+),' +
  rb'(?P<platform>[EYX])' +
  rb'(?P<variant_code>\d?[A-Z]*\d{3})' +
  rb'\.(?P<software_major>\d+)' +
  rb'(?:\.(?P<software_minor>\d+))?$'
)

PLATFORM_TO_CAR = {
  b'E': CAR.TESLA_MODEL_3,
  b'Y': CAR.TESLA_MODEL_Y,
  b'X': CAR.TESLA_MODEL_X,
}


class TestTeslaCarState(unittest.TestCase):
  def test_stock_autosteer_setting(self):
    update_ext = CarStateExt.update
    for candidate in CAR:
      for flags in (0, TeslaFlags.MISSING_DAS_SETTINGS):
        for vehicle_bus in (False, True):
          for autosteer in (0, 1):
            with self.subTest(candidate=candidate, flags=flags, vehicle_bus=vehicle_bus, autosteer=autosteer):
              CP = CarParams(carFingerprint=candidate.value, flags=int(flags))
              CP_SP = CarParamsSP(flags=TeslaFlagsSP.HAS_VEHICLE_BUS if vehicle_bus else 0)
              cs = CarState(CP, CP_SP)
              parsers = cs.get_can_parsers(CP, CP_SP)
              self.assertIn("DAS_autosteerEnabled", parsers[Bus.ap_party].vl["DAS_settings"])
              packer = CANPacker(DBC[candidate][Bus.party])
              parsers[Bus.ap_party].update([(0, [packer.make_can_msg("DAS_settings", CANBUS.autopilot_party,
                                                                   {"DAS_autosteerEnabled": autosteer})])])
              self.assertEqual(parsers[Bus.ap_party].vl["DAS_settings"]["DAS_autosteerEnabled"], autosteer)

              def check_update(state, ret, ret_sp, can_parsers):
                before = ret.to_dict()
                update_ext(state, ret, ret_sp, can_parsers)
                after = ret.to_dict()
                self.assertEqual(after, before, "CS2: SP extension preserves CarState")

              with patch.object(CarStateExt, "update", check_update):
                ret, _ = cs.update(parsers)
              self.assertEqual(ret.invalidLkasSetting, bool(autosteer and not flags), "CS1: stock Autosteer signal")


class TestTeslaFingerprint(unittest.TestCase):
  def test_fw_platform_code(self):
    # Every EPS FW must parse and its platform letter must match the car it's filed under.
    for car_model, ecus in FW_VERSIONS.items():
      for fw in ecus.get((Ecu.eps, 0x730, None), []):
        m = FW_RE.match(fw)

        assert m is not None, f"Unparsable FW: {fw}"
        assert PLATFORM_TO_CAR[m['platform']] == car_model, f"Platform letter {m['platform']!r} != {car_model.value}: {fw}"

  def test_radar_detection(self):
    # Test radar availability detection for cars with radar DBC defined
    for radar in (True, False):
      fingerprint = gen_empty_fingerprint()
      if radar:
        fingerprint[1][RADAR_START_ADDR] = 8
      CP = CarInterface.get_params(CAR.TESLA_MODEL_3, fingerprint, [], False, False, False)
      assert CP.radarUnavailable != radar

  def test_no_radar_car(self):
    # Model X doesn't have radar DBC defined, should always be unavailable
    for radar in (True, False):
      fingerprint = gen_empty_fingerprint()
      if radar:
        fingerprint[1][RADAR_START_ADDR] = 8
      CP = CarInterface.get_params(CAR.TESLA_MODEL_X, fingerprint, [], False, False, False)
      assert CP.radarUnavailable  # Always unavailable since no radar DBC


class TestTeslaSteeringProtocol(unittest.TestCase):
  """Steering protocol failure cases:
  SP1 a 2021 Model Y without 3-bit markers is still left in dashcam mode.
  SP2 0x054 on the vehicle bus is mistaken for the 3-bit party-bus marker.
  SP3 the legacy 2-bit protocol is packed with the 3-bit signal width.
  SP4 Model X is enabled by the generic legacy fallback.
  """

  @staticmethod
  def _params(candidate, bus=None, address=None):
    fingerprint = gen_empty_fingerprint()
    if bus is not None:
      fingerprint[bus][address] = 8
    return CarInterface.get_params(candidate, fingerprint, [], False, False, False)

  def test_legacy_model_3_and_y_are_supported(self):
    for candidate in (CAR.TESLA_MODEL_3, CAR.TESLA_MODEL_Y):
      with self.subTest(candidate=candidate):
        CP = self._params(candidate)
        self.assertFalse(CP.dashcamOnly, "SP1: 2-bit Model 3/Y must not be dashcam-only")
        self.assertTrue(CP.flags & TeslaFlags.DAS_STEERING_2_BIT)
        self.assertTrue(CP.safetyConfigs[0].safetyParam & TeslaSafetyFlags.DAS_STEERING_2_BIT)
        self.assertEqual(get_dbc(CP.carFingerprint, CP.flags), DBC_2_BIT[candidate])

  def test_vehicle_bus_054_does_not_select_three_bit(self):
    CP = self._params(CAR.TESLA_MODEL_Y, CANBUS.vehicle, 0x054)
    self.assertFalse(CP.dashcamOnly, "SP2: bus 1 0x054 is not the party-bus marker")
    self.assertTrue(CP.flags & TeslaFlags.DAS_STEERING_2_BIT)

  def test_three_bit_markers_select_three_bit(self):
    for bus, address in ((CANBUS.party, 0x054), (CANBUS.autopilot_party, 0x489)):
      with self.subTest(bus=bus, address=hex(address)):
        CP = self._params(CAR.TESLA_MODEL_Y, bus, address)
        self.assertFalse(CP.dashcamOnly)
        self.assertFalse(CP.flags & TeslaFlags.DAS_STEERING_2_BIT)
        self.assertFalse(CP.safetyConfigs[0].safetyParam & TeslaSafetyFlags.DAS_STEERING_2_BIT)
        self.assertEqual(get_dbc(CP.carFingerprint, CP.flags), DBC[CAR.TESLA_MODEL_Y])

  def test_model_x_is_not_enabled_by_legacy_fallback(self):
    CP = self._params(CAR.TESLA_MODEL_X)
    self.assertTrue(CP.dashcamOnly, "SP4: Model X remains unsupported")
    self.assertFalse(CP.flags & TeslaFlags.DAS_STEERING_2_BIT)

  def test_legacy_packer_uses_two_bit_signal(self):
    legacy_packer = CANPacker(DBC_2_BIT[CAR.TESLA_MODEL_Y][Bus.party])
    _, data, _ = legacy_packer.make_can_msg("DAS_steeringControl", CANBUS.party, {
      "DAS_steeringAngleRequest": 0, "DAS_steeringControlType": 1,
    })
    self.assertEqual(data[2] >> 6, 1, "SP3: legacy control type starts at bit 6")
    self.assertEqual(data[2] >> 5, 2, "SP3: 3-bit decoding would misread this frame")
