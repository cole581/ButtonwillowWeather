# Elk Hills-Buttonwillow Airport (L62) — weather vs NWS forecast

Hourly collector and dashboard comparing the WeatherXM station **High Indigo Air** (Elk Hills area, ≈35.353, −119.481) with the NWS hourly forecast for 35.355, −119.481.

A GitHub Actions workflow runs every hour on GitHub's servers (no computer of yours needs to be on). It:

1. reads the station's latest reading (temperature, dew point, humidity, wind, gust, wind direction, rain rate and rain counter, pressure) from WeatherXM's public Explorer endpoint;
2. saves a 48-hour snapshot of the NWS gridpoint forecast (the same data behind the forecast.weather.gov hourly graph);
3. rebuilds the dashboard (`docs/index.html`) and commits everything back to this repository.

## Files

| Path | What it is |
|---|---|
| `docs/index.html` | The dashboard. GitHub Pages publishes it; it also works if you download it and open it in a browser. |
| `data/observations.csv` | Every station reading collected (SI units: °C, %, m/s, mm, hPa; times UTC). |
| `data/forecasts/YYYY-MM.jsonl` | One NWS forecast snapshot per hour (°C, %, km/h, degrees, mm per hour). |
| `data/matched.csv` | Each observation beside the NWS forecast for that hour at 0, 3, 6, 12 and 24 h lead — the table for your own analysis. Wind in m/s. |
| `data/runs.csv` | Log of every run: which source worked, errors. |
| `scripts/collect.py`, `scripts/build.py` | The collector and the page builder (Python standard library only). |
| `.github/workflows/collect.yml` | The hourly schedule. |


