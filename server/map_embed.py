"""Windy Map Forecast API helpers.

The Windy Map Forecast API is a browser library (Leaflet-based) rather than a
REST data service. These helpers build a self-contained HTML page that boots the
interactive Windy map for a location and weather overlay, using a Map Forecast
API key.
"""

import json

# Boot scripts published by Windy for the Map Forecast API.
LEAFLET_URL = "https://unpkg.com/leaflet@1.4.0/dist/leaflet.js"
LIBBOOT_URL = "https://api.windy.com/assets/map-forecast/libBoot.js"


def build_map_embed_html(
    *,
    key: str,
    lat: float,
    lon: float,
    zoom: int = 5,
    overlay: str = "wind",
) -> str:
    """Return a standalone HTML document that renders the interactive Windy map.

    Args:
        key: Windy Map Forecast API key (used client-side by the boot script).
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        zoom: Initial map zoom level.
        overlay: Weather layer to display (e.g. "wind", "temp", "rain").
    """
    options = {
        "key": key,
        "verbose": False,
        "lat": lat,
        "lon": lon,
        "zoom": zoom,
        "overlay": overlay,
    }
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Windy Map — {overlay}</title>
  <style>html, body, #windy {{ height: 100%; margin: 0; padding: 0; }}</style>
  <script src="{LEAFLET_URL}"></script>
  <script src="{LIBBOOT_URL}"></script>
</head>
<body>
  <div id="windy"></div>
  <script>
    const options = {json.dumps(options)};
    windyInit(options, (windyAPI) => {{
      const {{ store }} = windyAPI;
      store.set("overlay", {json.dumps(overlay)});
    }});
  </script>
</body>
</html>
"""
