from decimal import Decimal, InvalidOperation
import re
from types import MappingProxyType

from station.database import InvalidInput


SUPPORTED_CONCENTRATION_UNITS = MappingProxyType({'μg/L': 1, 'mg/L': 1000})
_DECIMAL_TEXT = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')


def to_micrograms_per_liter(value, unit):
    if not isinstance(unit, str) or unit not in SUPPORTED_CONCENTRATION_UNITS:
        raise InvalidInput('unknown concentration unit')
    if type(value) is not int and not isinstance(value, str):
        raise InvalidInput('concentration must be an integer or decimal text')
    if isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value) is None:
        raise InvalidInput('invalid decimal concentration')
    try:
        numerator, denominator = Decimal(value).as_integer_ratio()
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise InvalidInput('invalid decimal concentration') from exc
    scaled = numerator * SUPPORTED_CONCENTRATION_UNITS[unit]
    result, remainder = divmod(scaled, denominator)
    if remainder:
        raise InvalidInput('concentration does not convert to an integer μg/L')
    return result
