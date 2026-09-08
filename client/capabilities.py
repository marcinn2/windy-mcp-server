"""Model/parameter support matrix and coded-value legends for the Windy API.

Sourced from the official Point Forecast documentation
(https://api.windy.com/point-forecast/docs).

The Windy API silently omits any parameter/level series that the selected model
does not provide, and only answers 204 when *none* of the requested parameters
exist for that model. Knowing the matrix up front lets us explain a partial
result instead of returning a confusingly empty one.
"""

from .enums import Level, Model, Parameter

WEATHER_MODELS = frozenset(
    {
        Model.arome,
        Model.arome_antilles,
        Model.arome_france,
        Model.arome_reunion,
        Model.icon,
        Model.icon_d2,
        Model.icon_eu,
        Model.gfs,
        Model.nam_conus,
        Model.nam_hawaii,
        Model.nam_alaska,
        Model.hrrr_conus,
        Model.hrrr_alaska,
        Model.can_hrdps,
    }
)

WAVE_MODELS = frozenset(
    {Model.gfs_wave, Model.icon_wave, Model.icon_eu_wave, Model.can_rdwps_wave}
)

CURRENT_MODELS = frozenset({Model.cmems})

AIR_QUALITY_MODELS = frozenset({Model.cams, Model.cams_eu})

# Parameters that accept a pressure level; every other parameter is only ever
# returned at "surface", whatever levels the request asks for.
LEVEL_AWARE_PARAMETERS = frozenset(
    {Parameter.temp, Parameter.dewpoint, Parameter.wind, Parameter.gh, Parameter.rh}
)

# Which models provide which parameter. Anything absent from a parameter's set
# is documented by Windy as unsupported for that model.
PARAMETER_MODELS: dict[Parameter, frozenset[Model]] = {
    # Weather parameters available from every weather model.
    Parameter.temp: WEATHER_MODELS,
    Parameter.dewpoint: WEATHER_MODELS,
    Parameter.rh: WEATHER_MODELS,
    Parameter.pressure: WEATHER_MODELS,
    Parameter.precip: WEATHER_MODELS,
    Parameter.conv_precip: WEATHER_MODELS,
    Parameter.wind: WEATHER_MODELS,
    Parameter.wind_gust: WEATHER_MODELS,
    Parameter.cape: WEATHER_MODELS,
    Parameter.ptype: WEATHER_MODELS,
    Parameter.lclouds: WEATHER_MODELS,
    Parameter.mclouds: WEATHER_MODELS,
    Parameter.hclouds: WEATHER_MODELS,
    # Weather parameters with restricted model support.
    Parameter.snow_precip: WEATHER_MODELS - {Model.nam_hawaii, Model.can_hrdps},
    Parameter.gh: frozenset({Model.icon, Model.icon_d2, Model.icon_eu}),
    Parameter.cbase: frozenset({Model.arome, Model.arome_antilles}),
    Parameter.visibility: frozenset({Model.arome_france, Model.arome_reunion}),
    Parameter.weather_warnings: frozenset({Model.nam_conus, Model.can_hrdps}),
    # Sea parameters.
    Parameter.waves: WAVE_MODELS,
    Parameter.waves_power: WAVE_MODELS,
    Parameter.swell1: WAVE_MODELS,
    Parameter.swell2: WAVE_MODELS,
    Parameter.wind_waves: frozenset({Model.gfs_wave, Model.icon_wave}),
    Parameter.currents: CURRENT_MODELS,
    Parameter.currents_tide: CURRENT_MODELS,
    # Air quality parameters.
    Parameter.aqi: AIR_QUALITY_MODELS,
    Parameter.so2sm: AIR_QUALITY_MODELS,
    Parameter.dustsm: AIR_QUALITY_MODELS,
    Parameter.cosc: AIR_QUALITY_MODELS,
    Parameter.go3: AIR_QUALITY_MODELS,
    Parameter.no2: AIR_QUALITY_MODELS,
    Parameter.pm10: AIR_QUALITY_MODELS,
    Parameter.pm2p5: AIR_QUALITY_MODELS,
    # Pollen is European-only.
    Parameter.pollen_alder: frozenset({Model.cams_eu}),
    Parameter.pollen_birch: frozenset({Model.cams_eu}),
    Parameter.pollen_grass: frozenset({Model.cams_eu}),
    Parameter.pollen_mugwort: frozenset({Model.cams_eu}),
    Parameter.pollen_olive: frozenset({Model.cams_eu}),
    Parameter.pollen_ragweed: frozenset({Model.cams_eu}),
}


def models_for(parameter: Parameter) -> list[str]:
    """Return the models that provide `parameter`, sorted for stable messages."""
    return sorted(str(m) for m in PARAMETER_MODELS.get(parameter, frozenset()))


def unsupported_parameters(
    model: Model, parameters: list[Parameter]
) -> list[Parameter]:
    """Return the requested parameters that `model` does not provide."""
    return [p for p in parameters if model not in PARAMETER_MODELS.get(p, frozenset())]


def describe_unsupported(model: Model, parameters: list[Parameter]) -> str | None:
    """Explain which requested parameters `model` lacks, and where to get them.

    Returns None when the model provides everything that was requested.
    """
    missing = unsupported_parameters(model, parameters)
    if not missing:
        return None
    details = ", ".join(
        f"{p} (available from: {', '.join(models_for(p)) or 'no model'})"
        for p in missing
    )
    return (
        f"Model '{model}' does not provide {len(missing)} requested "
        f"parameter(s), so they are absent from the series below: {details}."
    )


def unusable_levels(parameters: list[Parameter], levels: list[Level]) -> str | None:
    """Warn when pressure levels were requested but no parameter can use them.

    Windy only returns non-surface data for temp, dewpoint, wind, gh and rh.
    Other parameters come back at surface regardless of the requested levels.
    """
    non_surface = [lv for lv in levels if lv != Level.surface]
    if not non_surface:
        return None
    if any(p in LEVEL_AWARE_PARAMETERS for p in parameters):
        return None
    usable = ", ".join(sorted(str(p) for p in LEVEL_AWARE_PARAMETERS))
    return (
        f"Pressure levels ({', '.join(str(lv) for lv in non_surface)}) were "
        f"requested, but none of the requested parameters vary by level, so all "
        f"values are surface values. Levels apply to: {usable}."
    )


# Coded parameter values. Windy returns these as bare integers, which are
# meaningless without the lookup table, so responses carry the legend.
PTYPE_LEGEND: dict[str, str] = {
    "0": "no precipitation",
    "1": "rain",
    "3": "freezing rain",
    "5": "snow",
    "7": "mixture of rain and snow",
    "8": "ice pellets",
}

WEATHER_WARNINGS_LEGEND: dict[str, str] = {
    "45": "fog",
    "48": "fog, depositing rime",
    "51": "slight drizzle",
    "53": "moderate drizzle",
    "55": "heavy drizzle",
    "56": "freezing drizzle, slight",
    "57": "freezing drizzle, moderate or heavy",
    "61": "slight rain, not freezing",
    "63": "moderate rain, not freezing",
    "65": "heavy rain, not freezing",
    "66": "freezing rain, slight",
    "67": "freezing rain, moderate or heavy",
    "71": "slight fall of snowflakes",
    "73": "moderate fall of snowflakes",
    "75": "heavy fall of snowflakes",
    "77": "snow grains",
    "80": "rain shower(s), slight",
    "81": "rain shower(s), moderate or heavy",
    "82": "rain shower(s), violent",
    "85": "snow shower(s), slight",
    "86": "snow shower(s), moderate or heavy",
    "95": "thunderstorm, slight or moderate",
    "96": "thunderstorm with hail, or heavy thunderstorm",
}

# Response-key prefix -> legend for that key's coded values.
LEGENDS: dict[str, dict[str, str]] = {
    "ptype": PTYPE_LEGEND,
    "weatherwarnings": WEATHER_WARNINGS_LEGEND,
}

# Response-key prefix -> plain-language note, for keys whose meaning is not
# obvious from the name alone. Keys that speak for themselves are left out to
# keep responses compact.
DESCRIPTIONS: dict[str, str] = {
    "wind_speed": "wind speed, derived from the model's u/v wind components",
    "wind_dir": (
        "direction the wind blows FROM, in degrees clockwise from true north "
        "(0 = northerly, 90 = easterly); derived from the u/v wind components"
    ),
    "gust": "maximum wind gust",
    "past3hprecip": "total precipitation accumulated over the preceding 3 hours",
    "past3hsnowprecip": "snow precipitation accumulated over the preceding 3 hours",
    "past3hconvprecip": (
        "convective precipitation accumulated over the preceding 3 hours"
    ),
    "cbase": "height of the cloud base above ground",
    "gh": "geopotential height of the pressure level",
    "cape": "convective available potential energy; higher values favour storms",
    "aqi_us": "air quality index on the US EPA scale; higher is worse",
    "ptype": "precipitation type as a numeric code; see the legend field",
    "weatherwarnings": "significant weather as a numeric code; see the legend field",
}
