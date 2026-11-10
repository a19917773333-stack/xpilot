"""Vehicle fingerprint cache regression cases.

C1: An exact Tesla cache without a readable VIN must resume without diagnostic VIN/FW queries.
C2: A fuzzy cache without a readable VIN must still perform diagnostic queries.
C3: A non-Tesla cache without a readable VIN must still perform diagnostic queries.
C4: A non-empty cache for a different CAN fingerprint must not be used.
"""

import unittest
from unittest.mock import patch

from opendbc.car import car_helpers
from opendbc.car.structs import CarParams
from opendbc.car.vin import VIN_UNKNOWN


class TestFingerprintCache(unittest.TestCase):
  @staticmethod
  def _cached_params(brand: str = "tesla", fuzzy: bool = False) -> CarParams:
    return CarParams(
      brand=brand,
      carVin=VIN_UNKNOWN,
      carFw=[CarParams.CarFw(fwVersion="test", brand=brand, address=0x738)],
      carFingerprint="TESLA_MODEL_Y",
      fingerprintSource=CarParams.FingerprintSource.fw,
      fuzzyFingerprint=fuzzy,
    )

  @staticmethod
  def _can_recv(wait_for_one: bool = False) -> list:
    return []

  @staticmethod
  def _can_send(msgs) -> None:
    return None

  @staticmethod
  def _set_obd_multiplexing(enabled: bool) -> None:
    return None

  def _fingerprint(self, cached_params: CarParams, can_fingerprint: str | None = "TESLA_MODEL_Y"):
    with patch.object(car_helpers, "get_vin") as get_vin, \
         patch.object(car_helpers, "get_present_ecus") as get_present_ecus, \
         patch.object(car_helpers, "get_fw_versions_ordered") as get_fw_versions, \
         patch.object(car_helpers, "can_fingerprint", return_value=(can_fingerprint, {})), \
         patch.object(car_helpers, "match_fw_to_car", return_value=(True, {"TESLA_MODEL_Y"})):
      get_vin.return_value = (-1, -1, VIN_UNKNOWN)
      get_present_ecus.return_value = set()
      get_fw_versions.return_value = []
      result = car_helpers.fingerprint(
        self._can_recv,
        self._can_send,
        self._set_obd_multiplexing,
        cached_params,
        None,
      )
    return result, get_vin, get_present_ecus, get_fw_versions

  def test_TESLA_exact_cache_without_vin_skips_diagnostic_queries(self):
    result, get_vin, get_present_ecus, get_fw_versions = self._fingerprint(self._cached_params(), "TESLA_MODEL_Y")

    self.assertEqual(result[2], VIN_UNKNOWN)
    get_vin.assert_not_called()
    get_present_ecus.assert_not_called()
    get_fw_versions.assert_not_called()

  def test_TESLA_fuzzy_cache_without_vin_still_queries(self):
    _, get_vin, get_present_ecus, get_fw_versions = self._fingerprint(self._cached_params(fuzzy=True))

    get_vin.assert_called_once()
    get_present_ecus.assert_called_once()
    get_fw_versions.assert_called_once()

  def test_non_TESLA_cache_without_vin_still_queries(self):
    _, get_vin, get_present_ecus, get_fw_versions = self._fingerprint(self._cached_params(brand="toyota"))

    get_vin.assert_called_once()
    get_present_ecus.assert_called_once()
    get_fw_versions.assert_called_once()

  def test_TESLA_cache_for_different_can_fingerprint_still_queries(self):
    _, get_vin, get_present_ecus, get_fw_versions = self._fingerprint(self._cached_params(), "TESLA_MODEL_3")

    get_vin.assert_called_once()
    get_present_ecus.assert_called_once()
    get_fw_versions.assert_called_once()


if __name__ == "__main__":
  unittest.main()
