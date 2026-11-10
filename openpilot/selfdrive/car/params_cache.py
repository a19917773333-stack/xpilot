from opendbc.car.structs import car


def get_cached_car_params(params):
  # CarParamsCache is cleared whenever manager starts, so use the last
  # persisted params as a fallback across ignition cycles.
  for key in ("CarParamsCache", "CarParamsPersistent"):
    cached_params_raw = params.get(key)
    if cached_params_raw is not None:
      with car.CarParams.from_bytes(cached_params_raw) as cached_params:
        return cached_params

  return None
