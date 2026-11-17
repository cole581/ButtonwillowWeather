#!/usr/bin/env python3
"""Hourly collector for the High Indigo Air weather dashboard (GitHub Actions).

Pulls the latest WeatherXM observation for station "High Indigo Air" (public
Explorer cell endpoint, no key) and the NWS gridpoint forecast for
35.355,-119.481, and appends them to files under data/:

  data/observations.csv          one row per new station observation (deduplicated by timestamp)
  data/forecasts/YYYY-MM.jsonl   one line per run: 48-hour hourly NWS forecast snapshot
  data/runs.csv                  one row per run: which sources succeeded, errors

Standard library only.  Usage: python scripts/collect.py [--mock-dir DIR]
(mock dir holds wxm.json, points.json, grid.json; WX_NOW=ISO time overrides the clock, for testing)
"""
import csv, json, os, re, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

LAT, LON = 35.355, -119.481
WXM_CELL = "8729ac626ffffff"
WXM_NAME = "High Indigo Air"
WXM_ID = "a1e49090-ad73-11ef-8b2f-f594437d6709"
UA = "OdysAviation-FlightTest-WxDashboard/1.0"
FCST_HOURS = 48        # kept in the hourly history (enough for 24 h lead comparisons)
FCST_HOURS_LATEST = 168  # newest forecast only, for the dashboard's look-ahead
LAYERS = {  # NWS layer -> short key
    "temperature": "T", "dewpoint": "Td", "relativeHumidity": "RH",
    "windSpeed": "WS", "windDirection": "WD", "windGust": "WG",
    "probabilityOfPrecipitation": "PoP", "quantitativePrecipitation": "QPF",
    "skyCover": "SKY",
}
SUM_LAYERS = {"QPF"}  # amounts spread evenly over their interval


def get(url, mock=None, tries=3):
    if mock:
        with open(mock) as f:
            return json.load(f)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/geo+json, application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # NWS grid endpoint returns sporadic 500s
            last = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dur(s):
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", s)
    if not m:
        raise ValueError("bad duration " + s)
    d, h, mi = (int(x or 0) for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi)


def rnd(v, n=2):
    return None if v is None else round(float(v), n)


def wxm_obs(mock=None):
    data = get(f"https://api.weatherxm.com/api/v1/cells/{WXM_CELL}/devices", mock)
    dev = next((d for d in data if d.get("id") == WXM_ID), None) or \
          next((d for d in data if (d.get("name") or "").lower() == WXM_NAME.lower()), None)
    if not dev:
        raise RuntimeError("station not found in cell")
    cw = dev.get("current_weather") or {}
    ts = datetime.fromisoformat(cw["timestamp"].replace("Z", "+00:00"))
    obs = {
        "ts": iso_z(ts),
        "temp_c": rnd(cw.get("temperature")),
        "dew_c": rnd(cw.get("dew_point")),
        "rh": rnd(cw.get("humidity"), 1),
        "wind_ms": rnd(cw.get("wind_speed")),
        "gust_ms": rnd(cw.get("wind_gust")),
        "wind_dir": rnd(cw.get("wind_direction"), 0),
        "precip_rate_mmh": rnd(cw.get("precipitation")),
        "precip_accum_mm": rnd(cw.get("precipitation_accumulated")),
        "pressure_hpa": rnd(cw.get("pressure"), 1),
        "icon": cw.get("icon"),
        "active": bool(dev.get("isActive", True)),
    }
    return ts, obs


def nws_fcst(now, mock_points=None, mock_grid=None, n_hours=FCST_HOURS):
    pts = get(f"https://api.weather.gov/points/{LAT},{LON}", mock_points)["properties"]
    grid = get(pts["forecastGridData"], mock_grid)["properties"]
    start = now.replace(minute=0, second=0, microsecond=0)
    hours = [start + timedelta(hours=i) for i in range(n_hours)]
    idx = {h: i for i, h in enumerate(hours)}
    out = {"t": [iso_z(h) for h in hours]}
    for layer, key in LAYERS.items():
        col = [None] * n_hours
        for v in (grid.get(layer) or {}).get("values", []):
            t0s, dur = v["validTime"].split("/")
            t0 = datetime.fromisoformat(t0s.replace("Z", "+00:00"))
            n = max(1, int(parse_dur(dur).total_seconds() // 3600))
            val = v["value"]
            if val is not None and key in SUM_LAYERS:
                val = val / n
            for k in range(n):
                i = idx.get(t0 + timedelta(hours=k))
                if i is not None:
                    col[i] = rnd(val, 2)
        out[key] = col
    return {
        "issued": grid.get("updateTime"),
        "grid": f'{pts.get("gridId")}/{pts.get("gridX")},{pts.get("gridY")}',
        "elev_m": rnd((grid.get("elevation") or {}).get("value"), 0),
        "units": {"T": "degC", "Td": "degC", "RH": "%", "WS": "km/h", "WD": "deg",
                  "WG": "km/h", "PoP": "%", "QPF": "mm/h", "SKY": "%"},
        **out,
    }


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
OBS_FIELDS = ["ts", "temp_c", "dew_c", "rh", "wind_ms", "gust_ms", "wind_dir", "precip_rate_mmh",
              "precip_accum_mm", "pressure_hpa", "icon", "active", "fetched"]
RUN_FIELDS = ["at", "wxm_ok", "nws_ok", "obs_ts", "new_obs", "fcst_issued", "fcst_saved", "errors"]


def append_csv(path, fields, row):
    new = not os.path.exists(path)
    if not new:  # add any new columns to an existing file's header (older rows get blanks)
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
            old = rows[0].keys() if rows else None
        if old is not None and list(old) != fields:
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})


def last_obs_ts(path):
    if not os.path.exists(path):
        return set()
    with open(path, newline="") as f:
        return {r["ts"] for r in csv.DictReader(f)}


def last_snapshot():
    """(issued, fetched time) of the newest saved forecast snapshot, or (None, None)."""
    files = sorted(f for f in os.listdir(os.path.join(DATA, "forecasts")) if f.endswith(".jsonl"))
    for name in reversed(files):
        with open(os.path.join(DATA, "forecasts", name), "rb") as f:
            lines = [l for l in f.read().splitlines() if l.strip()]
        if lines:
            try:
                r = json.loads(lines[-1])
                return r.get("issued"), datetime.fromisoformat(r["at"].replace("Z", "+00:00"))
            except (ValueError, KeyError):
                return None, None
    return None, None


def main():
    mock = None
    if "--mock-dir" in sys.argv:
        mock = sys.argv[sys.argv.index("--mock-dir") + 1]
    now = datetime.fromisoformat(os.environ["WX_NOW"].replace("Z", "+00:00")) if os.environ.get("WX_NOW") \
        else datetime.now(timezone.utc)
    os.makedirs(os.path.join(DATA, "forecasts"), exist_ok=True)
    run = {"at": iso_z(now), "wxm_ok": False, "nws_ok": False, "new_obs": False, "fcst_saved": False}
    errors = []

    try:
        _, obs = wxm_obs(mock and f"{mock}/wxm.json")
        obs["fetched"] = iso_z(now)
        run["wxm_ok"], run["obs_ts"] = True, obs["ts"]
        obs_path = os.path.join(DATA, "observations.csv")
        if obs["ts"] not in last_obs_ts(obs_path):
            append_csv(obs_path, OBS_FIELDS, obs)
            run["new_obs"] = True
    except Exception as e:
        errors.append(f"WeatherXM: {e}"[:300])

    try:
        full = nws_fcst(now, mock and f"{mock}/points.json", mock and f"{mock}/grid.json", FCST_HOURS_LATEST)
        full = {"at": iso_z(now), **full}
        # trim trailing hours NWS hasn't forecast yet
        n = len(full["t"])
        while n and all((full.get(k) or [None])[n - 1] is None for k in LAYERS.values()):
            n -= 1
        full.update({k: full[k][:n] for k in ["t", *LAYERS.values()]})
        with open(os.path.join(DATA, "forecast_latest.json"), "w") as f:
            json.dump(full, f, separators=(",", ":"))
        hist = dict(full, **{k: full[k][:FCST_HOURS] for k in ["t", *LAYERS.values()]})
        run["nws_ok"], run["fcst_issued"] = True, full.get("issued")
        # Runs happen every 15 min; keep a history snapshot about hourly: when the last one is
        # ~an hour old, or sooner (25+ min) if NWS has issued a new forecast since.
        last_issued, last_at = last_snapshot()
        age = None if last_at is None else now - last_at
        if age is None or age >= timedelta(minutes=55) or \
                (last_issued != full.get("issued") and age >= timedelta(minutes=25)):
            with open(os.path.join(DATA, "forecasts", f"{now:%Y-%m}.jsonl"), "a") as f:
                f.write(json.dumps(hist, separators=(",", ":")) + "\n")
            run["fcst_saved"] = True
    except Exception as e:
        errors.append(f"NWS: {e}"[:300])

    run["errors"] = " | ".join(errors)
    append_csv(os.path.join(DATA, "runs.csv"), RUN_FIELDS, run)
    print(json.dumps(run))
    # Fail the job only if both sources failed, so GitHub emails you about real outages.
    if not run["wxm_ok"] and not run["nws_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
