# SPDX-License-Identifier: GPL-3.0-or-later
"""Map slider indices to published ranges or enumerations without inventing values."""
from dataclasses import dataclass
from math import floor, isclose, isfinite


@dataclass(frozen=True)
class ControlScale:
    count: int
    choices: tuple = ()
    low: float = 0
    step: float = 1
    floating: bool = False
    segments: tuple[str, ...] = ()

    @classmethod
    def from_prop(cls, prop, segmented: bool = False):
        if prop.type == "bool":
            return None
        if prop.value_list:
            choices = tuple((entry["value"], str(entry.get("desc_zh_cn") or entry.get("description") or entry["value"]))
                            for entry in prop.value_list if isinstance(entry, dict) and "value" in entry)
            if len(choices) < 2:
                return None
            return cls(len(choices), choices=choices,
                       segments=tuple(label for _, label in choices) if segmented else ())
        if not prop.range or len(prop.range) != 3:
            return None
        low, high, step = prop.range
        if (not all(isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
                    for value in (low, high, step)) or high <= low or step <= 0):
            return None
        count = floor((high - low) / step + 1e-7) + 1
        if count < 2:
            return None
        labels = tuple(f"{low + index * step:g}" for index in range(count)) if segmented and count <= 12 else ()
        return cls(count, low=low, step=step, floating=prop.type in ("float", "double"), segments=labels)

    def value_at(self, index: int):
        if not 0 <= index < self.count:
            raise IndexError(index)
        if self.choices:
            return self.choices[index][0]
        value = round(self.low + index * self.step, 8)
        return float(value) if self.floating else int(value)

    def index_of(self, value) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        if self.choices:
            return next((index for index, (candidate, _) in enumerate(self.choices) if candidate == value), None)
        if not isinstance(value, (int, float)) or not isfinite(value):
            return None
        index = round((value - self.low) / self.step)
        if 0 <= index < self.count and isclose(value, self.value_at(index), rel_tol=1e-8, abs_tol=1e-7):
            return index
        return None

    def label_at(self, index: int) -> str:
        return self.choices[index][1] if self.choices else f"{self.value_at(index):g}"

    def label_for(self, value) -> str:
        index = self.index_of(value)
        return self.label_at(index) if index is not None else "未知档位"
