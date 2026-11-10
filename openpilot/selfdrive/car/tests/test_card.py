import unittest

from openpilot.selfdrive.car.params_cache import get_cached_car_params
from opendbc.car.structs import car


class TestCachedCarParams(unittest.TestCase):
  def test_falls_back_to_persistent_params_when_manager_cache_is_cleared(self):
    persistent_params = car.CarParams.new_message(
      brand="tesla",
      carVin="00000000000000000",
      carFingerprint="TESLA_MODEL_Y",
    )

    params = {
      "CarParamsCache": None,
      "CarParamsPersistent": persistent_params.to_bytes(),
    }

    cached_params = get_cached_car_params(params)

    self.assertIsNotNone(cached_params)
    self.assertEqual(cached_params.brand, "tesla")
    self.assertEqual(cached_params.carFingerprint, "TESLA_MODEL_Y")
