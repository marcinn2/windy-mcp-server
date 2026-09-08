import math

from pydantic import BaseModel, Field

from ..capabilities import DESCRIPTIONS, LEGENDS
from ..enums import TempUnit

# Windy reports wind as eastward/northward vector components. They are useless
# to a reader expecting a speed, so they are converted to speed and direction.
_WIND_U = "wind_u"
_WIND_V = "wind_v"


class ForecastSeries(BaseModel):
    parameter_level: str
    unit: str | None
    values: list[float | None]
    description: str | None = None
    legend: dict[str, str] | None = None


class ForecastResponse(BaseModel):
    timestamps: list[int]
    series: list[ForecastSeries]
    # Non-series fields Windy may include alongside the data (e.g. a warning
    # string). Kept rather than dropped so callers see everything the API said.
    extras: dict = Field(default_factory=dict)

    @classmethod
    def from_raw(
        cls, data: dict, temp_unit: TempUnit = TempUnit.kelvin
    ) -> "ForecastResponse":
        timestamps: list[int] = data["ts"]
        units: dict[str, str | None] = data.get("units", {})

        reserved = {"ts", "units"}
        raw: dict[str, list] = {}
        extras: dict = {}
        for key, value in data.items():
            if key in reserved:
                continue
            if isinstance(value, list):
                raw[key] = value
            else:
                extras[key] = value

        series: list[ForecastSeries] = []
        for key, values in raw.items():
            base, _, level = key.rpartition("-")
            if not base:
                base, level = key, ""

            # Replace the u component with derived speed and direction, and drop
            # the v component that was folded into them.
            if base == _WIND_V and f"{_WIND_U}-{level}" in raw:
                continue
            if base == _WIND_U and f"{_WIND_V}-{level}" in raw:
                speed, direction = _speed_and_direction(
                    values, raw[f"{_WIND_V}-{level}"]
                )
                series.append(_build(f"wind_speed-{level}", units.get(key), speed))
                series.append(_build(f"wind_dir-{level}", "°", direction))
                continue

            converted, unit = _convert(base, values, units.get(key), temp_unit)
            series.append(_build(key, unit, converted))

        return cls(timestamps=timestamps, series=series, extras=extras)


def _build(key: str, unit: str | None, values: list[float | None]) -> ForecastSeries:
    base = key.rpartition("-")[0] or key
    return ForecastSeries(
        parameter_level=key,
        unit=unit,
        values=values,
        description=DESCRIPTIONS.get(base),
        legend=_legend_for(base, values),
    )


def _legend_for(base: str, values: list[float | None]) -> dict[str, str] | None:
    """Return the code table for a coded parameter, limited to codes present."""
    legend = LEGENDS.get(base)
    if legend is None:
        return None
    present = {str(int(v)) for v in values if v is not None}
    seen = {code: label for code, label in legend.items() if code in present}
    return seen or None


def _convert(
    base: str,
    values: list[float | None],
    unit: str | None,
    temp_unit: TempUnit,
) -> tuple[list[float | None], str | None]:
    """Apply the unit conversions Windy leaves to the caller.

    Both conversions are driven by the unit string the API actually returned, so
    a change on Windy's side degrades to passing the values through untouched.
    """
    if temp_unit == TempUnit.celsius and unit == TempUnit.kelvin.value:
        converted = [round(v - 273.15, 2) if v is not None else None for v in values]
        return converted, TempUnit.celsius.value
    # Accumulated precipitation arrives in metres, which reads as a rounding
    # error next to the millimetres every forecast is quoted in.
    if base.startswith("past3h") and unit == "m":
        converted = [round(v * 1000, 3) if v is not None else None for v in values]
        return converted, "mm"
    return values, unit


def _speed_and_direction(
    u: list[float | None], v: list[float | None]
) -> tuple[list[float | None], list[float | None]]:
    """Convert eastward/northward wind components to speed and bearing.

    Direction follows the meteorological convention: the bearing the wind blows
    *from*, in degrees clockwise from true north.
    """
    speed: list[float | None] = []
    direction: list[float | None] = []
    for u_val, v_val in zip(u, v, strict=False):
        if u_val is None or v_val is None:
            speed.append(None)
            direction.append(None)
            continue
        magnitude = math.hypot(u_val, v_val)
        speed.append(round(magnitude, 2))
        if magnitude == 0:
            # Calm air has no meaningful bearing.
            direction.append(None)
        else:
            bearing = (270 - math.degrees(math.atan2(v_val, u_val))) % 360
            direction.append(round(bearing, 1))
    return speed, direction
