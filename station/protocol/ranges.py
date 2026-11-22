from dataclasses import dataclass

from station.database import InvalidInput
from station.protocol.normalization import to_micrograms_per_liter


@dataclass(frozen=True)
class ConcentrationRange:
    lower_ug_l: int
    upper_ug_l: int

    def contains(self, value_ug_l):
        return self.lower_ug_l <= value_ug_l <= self.upper_ug_l


def build_concentration_range(lower, upper, unit):
    bounds = ConcentrationRange(
        to_micrograms_per_liter(lower, unit), to_micrograms_per_liter(upper, unit)
    )
    if bounds.lower_ug_l > bounds.upper_ug_l:
        raise InvalidInput('concentration range has reversed endpoints')
    return bounds
