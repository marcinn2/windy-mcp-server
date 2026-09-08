"""Correctness tests for the Windy API mapping.

The contract under test is the official Point Forecast documentation
(https://api.windy.com/point-forecast/docs): request shape, model/parameter
support, response decoding and unit handling.
"""

import math

import pytest
from pydantic import ValidationError

from client import (
    ForecastRequest,
    ForecastResponse,
    Level,
    Model,
    Parameter,
    TempUnit,
    describe_unsupported,
    unsupported_parameters,
    unusable_levels,
)

# --- Request shape -------------------------------------------------------


def test_payload_matches_documented_body():
    request = ForecastRequest(
        lat=49.809,
        lon=16.787,
        model=Model.gfs,
        parameters=[Parameter.wind, Parameter.dewpoint],
        levels=[Level.surface, Level.hPa800],
        temp_unit=TempUnit.celsius,
    )
    payload = request.model_dump(mode="json", exclude={"temp_unit"})
    assert payload == {
        "lat": 49.809,
        "lon": 16.787,
        "model": "gfs",
        "parameters": ["wind", "dewpoint"],
        "levels": ["surface", "800h"],
    }


@pytest.mark.parametrize("lat,lon", [(95, 0), (-91, 0), (0, 181), (0, -181)])
def test_out_of_range_coordinates_rejected(lat, lon):
    with pytest.raises(ValidationError):
        ForecastRequest(lat=lat, lon=lon, model=Model.gfs, parameters=[Parameter.temp])


def test_empty_parameters_rejected():
    with pytest.raises(ValidationError):
        ForecastRequest(lat=0, lon=0, model=Model.gfs, parameters=[])


def test_model_providing_nothing_is_rejected_with_guidance():
    with pytest.raises(ValidationError) as excinfo:
        ForecastRequest(lat=0, lon=0, model=Model.gfs, parameters=[Parameter.waves])
    message = str(excinfo.value)
    assert "gfsWave" in message and "provides none" in message


def test_partial_support_is_allowed():
    # aqi is supported by cams, pollen is not; the call still returns aqi.
    request = ForecastRequest(
        lat=0,
        lon=0,
        model=Model.cams,
        parameters=[Parameter.aqi, Parameter.pollen_birch],
    )
    assert request.model == Model.cams


# --- Support matrix ------------------------------------------------------


def test_pollen_requires_cams_eu():
    assert unsupported_parameters(Model.cams, [Parameter.pollen_birch]) == [
        Parameter.pollen_birch
    ]
    assert unsupported_parameters(Model.cams_eu, [Parameter.pollen_birch]) == []


@pytest.mark.parametrize(
    "parameter,supported,unsupported",
    [
        (Parameter.gh, Model.icon_eu, Model.gfs),
        (Parameter.cbase, Model.arome, Model.gfs),
        (Parameter.visibility, Model.arome_france, Model.gfs),
        (Parameter.weather_warnings, Model.nam_conus, Model.gfs),
        (Parameter.snow_precip, Model.gfs, Model.nam_hawaii),
        (Parameter.wind_waves, Model.gfs_wave, Model.icon_eu_wave),
        (Parameter.currents, Model.cmems, Model.gfs_wave),
    ],
)
def test_documented_restrictions(parameter, supported, unsupported):
    assert unsupported_parameters(supported, [parameter]) == []
    assert unsupported_parameters(unsupported, [parameter]) == [parameter]


def test_describe_unsupported_names_a_working_model():
    note = describe_unsupported(Model.cams, [Parameter.aqi, Parameter.pollen_grass])
    assert note is not None
    assert "pollenGrass" in note and "camsEu" in note
    assert describe_unsupported(Model.cams, [Parameter.aqi]) is None


def test_levels_warning_only_when_no_parameter_uses_them():
    assert unusable_levels([Parameter.precip], [Level.hPa850]) is not None
    assert unusable_levels([Parameter.temp], [Level.hPa850]) is None
    assert unusable_levels([Parameter.precip], [Level.surface]) is None


# --- Response decoding ---------------------------------------------------


def _raw(**overrides):
    data = {
        "ts": [1700000000000, 1700010800000],
        "units": {"temp-surface": "K"},
        "temp-surface": [273.15, 283.15],
    }
    data.update(overrides)
    return data


def _by_key(response):
    return {s.parameter_level: s for s in response.series}


def test_kelvin_converted_to_celsius_at_every_level():
    raw = _raw(
        units={"temp-surface": "K", "dewpoint-850h": "K"},
        **{"dewpoint-850h": [280.15, None]},
    )
    series = _by_key(ForecastResponse.from_raw(raw, temp_unit=TempUnit.celsius))
    assert series["temp-surface"].values == [0.0, 10.0]
    assert series["temp-surface"].unit == "°C"
    assert series["dewpoint-850h"].values == [7.0, None]


def test_kelvin_preserved_when_requested():
    series = _by_key(ForecastResponse.from_raw(_raw(), temp_unit=TempUnit.kelvin))
    assert series["temp-surface"].values == [273.15, 283.15]
    assert series["temp-surface"].unit == "K"


def test_wind_components_become_speed_and_bearing():
    raw = _raw(
        units={"wind_u-surface": "m*s-1", "wind_v-surface": "m*s-1"},
        **{"wind_u-surface": [3.0, 0.0], "wind_v-surface": [4.0, 0.0]},
    )
    series = _by_key(ForecastResponse.from_raw(raw))
    assert "wind_u-surface" not in series and "wind_v-surface" not in series
    assert series["wind_speed-surface"].values == [5.0, 0.0]
    assert series["wind_speed-surface"].unit == "m*s-1"
    # Blowing towards the north-east means it comes from the south-west.
    assert series["wind_dir-surface"].values[0] == pytest.approx(216.9, abs=0.1)
    # Calm air has no bearing.
    assert series["wind_dir-surface"].values[1] is None


@pytest.mark.parametrize(
    "u,v,bearing",
    [
        (1.0, 0.0, 270.0),  # blowing east, so out of the west
        (0.0, 1.0, 180.0),  # blowing north, so out of the south
        (-1.0, 0.0, 90.0),  # blowing west, so out of the east
        (0.0, -1.0, 0.0),  # blowing south, so out of the north
    ],
)
def test_wind_bearing_follows_meteorological_convention(u, v, bearing):
    raw = _raw(
        units={"wind_u-surface": "m*s-1", "wind_v-surface": "m*s-1"},
        **{"wind_u-surface": [u], "wind_v-surface": [v]},
    )
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["wind_dir-surface"].values[0] == pytest.approx(bearing)
    assert series["wind_speed-surface"].values[0] == pytest.approx(math.hypot(u, v))


def test_lone_wind_component_is_left_alone():
    raw = _raw(units={"wind_u-surface": "m*s-1"}, **{"wind_u-surface": [3.0, 4.0]})
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["wind_u-surface"].values == [3.0, 4.0]


def test_wind_derived_per_level():
    raw = _raw(
        units={
            "wind_u-surface": "m*s-1",
            "wind_v-surface": "m*s-1",
            "wind_u-850h": "m*s-1",
            "wind_v-850h": "m*s-1",
        },
        **{
            "wind_u-surface": [3.0],
            "wind_v-surface": [4.0],
            "wind_u-850h": [6.0],
            "wind_v-850h": [8.0],
        },
    )
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["wind_speed-surface"].values == [5.0]
    assert series["wind_speed-850h"].values == [10.0]


def test_metre_precipitation_converted_to_millimetres():
    raw = _raw(
        units={"past3hprecip-surface": "m"},
        **{"past3hprecip-surface": [0.001, None]},
    )
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["past3hprecip-surface"].values == [1.0, None]
    assert series["past3hprecip-surface"].unit == "mm"
    assert "3 hours" in series["past3hprecip-surface"].description


def test_precipitation_left_alone_when_already_millimetres():
    raw = _raw(units={"past3hprecip-surface": "mm"}, **{"past3hprecip-surface": [1.0]})
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["past3hprecip-surface"].values == [1.0]
    assert series["past3hprecip-surface"].unit == "mm"


def test_metre_heights_are_not_treated_as_precipitation():
    raw = _raw(units={"cbase-surface": "m"}, **{"cbase-surface": [1200.0]})
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["cbase-surface"].values == [1200.0]
    assert series["cbase-surface"].unit == "m"


def test_coded_parameters_carry_a_legend_of_codes_present():
    raw = _raw(units={"ptype-surface": None}, **{"ptype-surface": [0.0, 5.0, None]})
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["ptype-surface"].legend == {"0": "no precipitation", "5": "snow"}


def test_weather_warning_codes_are_decoded():
    raw = _raw(
        units={"weatherwarnings-surface": None},
        **{"weatherwarnings-surface": [95.0]},
    )
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["weatherwarnings-surface"].legend == {
        "95": "thunderstorm, slight or moderate"
    }


def test_plain_series_carry_no_legend():
    series = _by_key(ForecastResponse.from_raw(_raw()))
    assert series["temp-surface"].legend is None


def test_nulls_are_preserved():
    raw = _raw(units={"cape-surface": "J*kg-1"}, **{"cape-surface": [None, 12.0]})
    series = _by_key(ForecastResponse.from_raw(raw))
    assert series["cape-surface"].values == [None, 12.0]


def test_non_series_fields_are_kept():
    response = ForecastResponse.from_raw(_raw(warning="degraded model run"))
    assert response.extras == {"warning": "degraded model run"}
    assert "warning" not in _by_key(response)


def test_timestamps_pass_through_unchanged():
    response = ForecastResponse.from_raw(_raw())
    assert response.timestamps == [1700000000000, 1700010800000]
