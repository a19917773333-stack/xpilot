from types import SimpleNamespace

import numpy as np
import pyray as rl

from openpilot.selfdrive.ui.mici.onroad.model_renderer import ModelRenderer


def test_lead_markers_expose_screen_anchor_and_source():
  renderer = object.__new__(ModelRenderer)
  renderer._rect = rl.Rectangle(10.0, 20.0, 100.0, 50.0)
  renderer._lead_vehicles = [
    SimpleNamespace(
      visible=True,
      bar=np.array([[30.0, 40.0], [30.0, 42.0], [35.0, 42.0], [35.0, 40.0]], dtype=np.float32),
      d_rel=20.0,
      radar=True,
    ),
    SimpleNamespace(
      visible=False,
      bar=np.array([[30.0, 50.0], [30.0, 52.0], [35.0, 52.0], [35.0, 50.0]], dtype=np.float32),
      d_rel=40.0,
      radar=False,
    ),
  ]

  markers = renderer.lead_markers()

  assert len(markers) == 1
  assert (markers[0].x, markers[0].y, markers[0].d_rel, markers[0].radar) == (42.5, 60.0, 20.0, True)


def test_lead_source_is_preserved_per_vehicle():
  class Filter:
    initialized = False
    x = 0.0

    def update(self, value):
      self.x = value
      return value

  def vehicle():
    return SimpleNamespace(y_filter=Filter(), d_filter=Filter(), fade_filter=Filter(), visible=False,
                           bar=np.empty((0, 2)), d_rel=0.0, radar=False)

  renderer = object.__new__(ModelRenderer)
  renderer._lead_vehicles = [vehicle(), vehicle()]
  renderer._path = SimpleNamespace(raw_points=np.array([[0.0, 0.0, 0.0], [100.0, 0.0, 0.0]], dtype=np.float32))
  renderer._get_lead_bar = lambda *args: np.zeros((4, 2), dtype=np.float32)
  radar_leads = [
    SimpleNamespace(present=True, dRel=20.0, yRel=0.0, radar=True),
    SimpleNamespace(present=True, dRel=40.0, yRel=1.0, radar=False),
  ]
  sm = {
    'longitudinalPlan': SimpleNamespace(longitudinalPlanSource='radar'),
    'modelV2': SimpleNamespace(leadsV3=[]),
    'radarState': SimpleNamespace(leadOne=radar_leads[0], leadTwo=radar_leads[1]),
    'selfdriveState': SimpleNamespace(enabled=True, engageable=True),
    'carState': SimpleNamespace(brakePressed=False),
  }

  renderer._update_leads(sm)

  assert [lead.radar for lead in renderer._lead_vehicles] == [True, False]
