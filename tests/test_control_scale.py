# SPDX-License-Identifier: GPL-3.0-or-later
from app.core.control_scale import ControlScale
from app.core.models import PropInfo


def test_sparse_enum_slider_never_invents_intermediate_values():
    prop = PropInfo("fan-level", "档位", "uint8", True, True, value_list=[
        {"value": 1, "description": "低档"}, {"value": 3, "description": "中档"},
        {"value": 7, "description": "高档"}])
    scale = ControlScale.from_prop(prop, segmented=True)
    assert scale.segments == ("低档", "中档", "高档")
    assert [scale.value_at(index) for index in range(scale.count)] == [1, 3, 7]
    assert scale.index_of(3) == 1 and scale.index_of(2) is None
    assert scale.index_of(True) is None


def test_string_enum_and_unknown_current_value():
    prop = PropInfo("speed", "风速", "string", True, True, value_list=[
        {"value": "low", "description": "一档"}, {"value": "high", "description": "二档"}])
    scale = ControlScale.from_prop(prop, segmented=True)
    assert scale.value_at(1) == "high"
    assert scale.label_for("low") == "一档"
    assert scale.index_of("medium") is None


def test_small_stepped_range_segments_and_large_range_stays_quantized():
    prop = PropInfo("fan-level", "档位", "uint8", True, True, (1, 3, 1))
    scale = ControlScale.from_prop(prop, segmented=True)
    assert scale.segments == ("1", "2", "3")
    prop.range = (1, 100, 1)
    scale = ControlScale.from_prop(prop, segmented=True)
    assert not scale.segments and scale.count == 100
    assert scale.value_at(98) == 99


def test_nonzero_range_step_roundtrip_and_off_step_rejection():
    prop = PropInfo("color-temperature", "色温", "uint32", True, True, (2700, 6500, 100))
    scale = ControlScale.from_prop(prop)
    assert not scale.segments
    assert scale.value_at(13) == 4000 and scale.index_of(4000) == 13
    assert scale.index_of(4050) is None
