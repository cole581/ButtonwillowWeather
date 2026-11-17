#!/usr/bin/env python3
"""Builds the dashboard and the analysis table from the files collect.py keeps.

  docs/index.html      the dashboard (GitHub Pages serves it); last 8 days of data + newest 7-day forecast embedded
  data/matched.csv     every observation with the NWS forecast for that hour at 0/3/6/12/24 h lead (wide table)
  data/forecast_errors.csv   append-only log: one row per observation per lead with actual, forecast and
                             actual - forecast for each variable (rows are only ever added, never rewritten)

Standard library only.  Usage: python scripts/build.py   (WX_NOW=ISO time overrides the clock, for testing)
"""
import bisect, csv, glob, json, os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PAGE_DAYS = 8                     # history embedded in the page (page shows up to 7 d)
LEADS = [0, 3, 6, 12, 24]
VARS = ["T", "Td", "RH", "WS", "WD", "WG", "PoP", "QPF", "SKY"]
NUM = ["temp_c", "dew_c", "rh", "wind_ms", "gust_ms", "wind_dir", "precip_rate_mmh",
       "precip_accum_mm", "pressure_hpa"]
HOUR = timedelta(hours=1)


def parse_t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def num(s):
    try:
        return float(s) if s not in ("", None) else None
    except ValueError:
        return None


def load_obs():
    p = os.path.join(DATA, "observations.csv")
    if not os.path.exists(p):
        return []
    out = {}
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            o = {k: num(r.get(k)) if k in NUM else r.get(k) for k in r}
            o["active"] = r.get("active") in ("True", "true", "1")
            o["_t"] = parse_t(r["ts"])
            out[r["ts"]] = o
    obs = sorted(out.values(), key=lambda o: o["_t"])
    prev = None  # hourly precip from the station's running counter (resets when it drops)
    for o in obs:
        a = o.get("precip_accum_mm")
        o["precip_mm"] = None if a is None or prev is None else round(a - prev if a >= prev else a, 3)
        if a is not None:
            prev = a
    return obs


def load_runs():
    runs = []
    for p in sorted(glob.glob(os.path.join(DATA, "forecasts", "*.jsonl"))):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    r["_t"] = parse_t(r["at"])
                    runs.append(r)
    runs.sort(key=lambda r: r["_t"])
    return runs


def last_status():
    p = os.path.join(DATA, "runs.csv")
    if not os.path.exists(p):
        return None
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    r = rows[-1]
    return {"at": r["at"], "wxm_ok": r["wxm_ok"] == "True", "nws_ok": r["nws_ok"] == "True",
            "errors": [e for e in (r.get("errors") or "").split(" | ") if e]}


class Matcher:
    """For a valid hour, the value from the newest run fetched at or before a cutoff."""
    def __init__(self, runs):
        self.by_hour = {}  # (hour, var) -> sorted list of (run_time, value)
        for r in runs:
            for i, ts in enumerate(r.get("t", [])):
                h = parse_t(ts)
                for v in VARS:
                    val = (r.get(v) or [None] * 99)[i] if i < len(r.get(v) or []) else None
                    if val is not None:
                        self.by_hour.setdefault((h, v), []).append((r["_t"], val))
        for lst in self.by_hour.values():
            lst.sort(key=lambda x: x[0])

    def at(self, hour, var, cutoff):
        lst = self.by_hour.get((hour, var))
        if not lst:
            return None, None
        i = bisect.bisect_right([x[0] for x in lst], cutoff) - 1
        return (lst[i][1], lst[i][0]) if i >= 0 else (None, None)


def write_matched(obs, runs):
    m = Matcher(runs)
    cols = ["obs_time_utc", "temp_c", "dew_c", "rh_pct", "wind_ms", "gust_ms", "wind_dir_deg",
            "precip_mm", "precip_rate_mmh", "pressure_hpa"]
    for L in LEADS:
        cols += [f"L{L}_{c}" for c in ("fcst_fetched_utc", "temp_c", "dew_c", "rh_pct", "wind_ms",
                                         "gust_ms", "wind_dir_deg", "qpf_mm", "pop_pct", "sky_pct")]
    tmp = os.path.join(DATA, "matched.csv.tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for o in obs:
            t = o["_t"]
            hour = t.replace(minute=0, second=0, microsecond=0)
            row = [o["ts"], o["temp_c"], o["dew_c"], o["rh"], o["wind_ms"], o["gust_ms"], o["wind_dir"],
                   o["precip_mm"], o["precip_rate_mmh"], o["pressure_hpa"]]
            for L in LEADS:
                cut = t - timedelta(hours=L)
                vals, fetched = {}, None
                for v in VARS:
                    val, rt = m.at(hour, v, cut)
                    vals[v] = val
                    if rt and (fetched is None or rt > fetched):
                        fetched = rt
                ws = None if vals["WS"] is None else round(vals["WS"] / 3.6, 2)
                wg = None if vals["WG"] is None else round(vals["WG"] / 3.6, 2)
                row += [iso_z(fetched) if fetched else None, vals["T"], vals["Td"], vals["RH"], ws, wg,
                        vals["WD"], vals["QPF"], vals["PoP"], vals["SKY"]]
            w.writerow(["" if x is None else x for x in row])
    os.replace(tmp, os.path.join(DATA, "matched.csv"))


# variable: (log column stem, obs key, forecast key, forecast -> SI conversion)
ERR_VARS = [
    ("temp_c", "temp_c", "T", lambda v: v),
    ("wind_ms", "wind_ms", "WS", lambda v: v / 3.6),
    ("gust_ms", "gust_ms", "WG", lambda v: v / 3.6),
    ("wind_dir_deg", "wind_dir", "WD", lambda v: v),
    ("precip_mm", "precip_mm", "QPF", lambda v: v),
    ("rh_pct", "rh", "RH", lambda v: v),
]
ERR_COLS = ["obs_time_utc", "lead_h", "fcst_fetched_utc"] + \
    [f"{n}_{k}" for n, *_ in ERR_VARS for k in ("actual", "forecast", "error")]
CALM_MS = 1.0   # direction error is left blank when the observed wind is below this


def err_of(name, a, f):
    if a is None or f is None:
        return None
    if name == "wind_dir_deg":
        return round(((a - f + 540) % 360) - 180, 1)
    return round(a - f, 3)


def update_error_log(obs, runs):
    """Append rows for observations not yet logged. Existing rows are never changed."""
    path = os.path.join(DATA, "forecast_errors.csv")
    seen, new_file = set(), not os.path.exists(path)
    if not new_file:
        with open(path, newline="") as f:
            for r in csv.DictReader(f):
                seen.add((r["obs_time_utc"], r["lead_h"]))
    m, added = Matcher(runs), 0
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(ERR_COLS)
        for o in obs:
            hour = o["_t"].replace(minute=0, second=0, microsecond=0)
            for L in LEADS:
                if (o["ts"], str(L)) in seen:
                    continue
                cut, fetched, row = o["_t"] - timedelta(hours=L), None, [o["ts"], L]
                cells = []
                for name, okey, fkey, conv in ERR_VARS:
                    fv, rt = m.at(hour, fkey, cut)
                    fv = None if fv is None else round(conv(fv), 3)
                    if rt and (fetched is None or rt > fetched):
                        fetched = rt
                    a = o.get(okey)
                    e = err_of(name, a, fv)
                    if name == "wind_dir_deg" and (o.get("wind_ms") is None or o["wind_ms"] < CALM_MS):
                        e = None
                    cells += [a, fv, e]
                row += [iso_z(fetched) if fetched else None] + cells
                w.writerow(["" if x is None else x for x in row])
                added += 1
    return added


def accuracy_summary(now):
    """All-time / 7-day / 24-hour statistics of actual - forecast, per lead and variable."""
    path = os.path.join(DATA, "forecast_errors.csv")
    out = {"since": None, "leads": {}}
    if not os.path.exists(path):
        return out
    acc = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            t = parse_t(r["obs_time_utc"])
            for name, *_ in ERR_VARS:
                e = num(r.get(f"{name}_error"))
                if e is None:
                    continue
                acc.setdefault(r["lead_h"], {}).setdefault(name, []).append(
                    (t, e, num(r.get(f"{name}_actual")), num(r.get(f"{name}_forecast"))))
    for lead, byvar in acc.items():
        res = {}
        for name, pts in byvar.items():
            pts.sort(key=lambda p: p[0])
            es = [p[1] for p in pts]
            def mean_since(h):
                xs = [p[1] for p in pts if p[0] >= now - timedelta(hours=h)]
                return (round(sum(xs) / len(xs), 3), len(xs)) if xs else (None, 0)
            m24, n24 = mean_since(24)
            m7, n7 = mean_since(168)
            last = pts[-1]
            res[name] = {
                "n": len(es), "mean": round(sum(es) / len(es), 3),
                "mae": round(sum(abs(e) for e in es) / len(es), 3),
                "rmse": round((sum(e * e for e in es) / len(es)) ** 0.5, 3),
                "mean24": m24, "n24": n24, "mean7d": m7, "n7d": n7, "first": iso_z(pts[0][0]),
                "last": {"t": iso_z(last[0]), "err": last[1], "actual": last[2], "forecast": last[3]},
            }
        out["leads"][lead] = res
    firsts = [v["first"] for res in out["leads"].values() for v in res.values()]
    out["since"] = min(firsts) if firsts else None
    return out


def page_data(obs, runs, now):
    since = now - timedelta(days=PAGE_DAYS)
    p_obs = [{k: v for k, v in o.items() if not k.startswith("_")} for o in obs if o["_t"] >= since]
    p_runs = []
    fruns = [r for r in runs if r["_t"] >= since - timedelta(days=1)]
    for j, r in enumerate(fruns):
        latest = j == len(fruns) - 1
        keep = [i for i, ts in enumerate(r["t"])
                if latest or parse_t(ts) <= r["_t"] + timedelta(hours=25)]  # leads up to 24 h
        fc = {"issued": r.get("issued"), "grid": r.get("grid"), "t": [r["t"][i] for i in keep]}
        for v in VARS:
            col = r.get(v) or []
            fc[v] = [col[i] if i < len(col) else None for i in keep]
        p_runs.append({"at": r["at"], "fcst": fc})
    latest = None
    lp = os.path.join(DATA, "forecast_latest.json")
    if os.path.exists(lp):
        try:
            with open(lp) as f:
                lf = json.load(f)
            latest = {"at": lf["at"], "fcst": {k: lf.get(k) for k in ["issued", "grid", "t", *VARS]}}
        except (OSError, ValueError, KeyError):
            latest = None
    return {"built": iso_z(now), "status": last_status(), "obs": p_obs, "runs": p_runs, "latest": latest,
            "accuracy": accuracy_summary(now)}


def main():
    now = parse_t(os.environ["WX_NOW"]) if os.environ.get("WX_NOW") else datetime.now(timezone.utc)
    os.makedirs(DATA, exist_ok=True)
    obs, runs = load_obs(), load_runs()
    write_matched(obs, runs)
    added = update_error_log(obs, runs)
    data = json.dumps(page_data(obs, runs, now), separators=(",", ":")).replace("</", "<\\/")
    with open(os.path.join(ROOT, "scripts", "template.html")) as f:
        html = f.read()
    marker = "/*__DATA__*/null"
    assert marker in html, "template is missing the data marker"
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    with open(os.path.join(ROOT, "docs", "index.html"), "w") as f:
        f.write(html.replace(marker, data))
    print(f"built: {len(obs)} observations, {len(runs)} forecast snapshots, {added} error-log rows added, page {len(data)//1024} KB")


if __name__ == "__main__":
    main()
