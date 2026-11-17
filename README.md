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

## Setup (web browser only, about 10 minutes)

1. **Create the repository.** Go to <https://github.com/new>, name it (for example `l62-weather`), choose **Public** (see note below), leave "Add a README" unchecked, and click **Create repository**.
2. **Upload the files.** On the new repo's page click **uploading an existing file**, drag in everything from the unzipped folder (`README.md`, `scripts`, `docs`, `.github`), and click **Commit changes**.
   - Check that `.github/workflows/collect.yml` arrived (some browsers skip folders whose names start with a dot). If it's missing: **Add file → Create new file**, type `.github/workflows/collect.yml` as the name, paste in that file's contents, and commit.
3. **Start the first run.** Open the **Actions** tab. If asked, click the button to enable workflows. Click **Collect weather → Run workflow → Run workflow**. After about a minute the run should show a green check, and `data/` will appear in the repo.
   - If it fails at "Commit data" with a permission error: **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**, then run it again.
4. **Turn on the web page.** **Settings → Pages**. Under "Build and deployment", Source: **Deploy from a branch**; Branch: **main**, folder **/docs**; **Save**. After a minute or two the page is live at `https://<your-username>.github.io/<repo-name>/` (the URL is shown at the top of that Settings page).

From then on it runs by itself every hour at about :41 past the hour (GitHub sometimes starts scheduled runs several minutes late, and very occasionally skips one).

## Notes

- **Public vs private.** On a free GitHub account, Pages only works for public repositories, so the dashboard and data are viewable by anyone with the link (it is public weather data, but it does show interest in this site). A private repository works for collection too, but you'd view the dashboard by downloading `docs/index.html` and opening it, or need a paid GitHub plan for Pages (and on most paid plans the Pages site is still public).
- **Usage.** Each run takes under a minute. Public repositories don't use Actions minutes; a private repo on a free account uses roughly 730 of its 2,000 free minutes a month.
- **Failures.** If both sources fail in a run, the run is marked failed and GitHub emails you. One source failing is logged in `data/runs.csv` and shown on the dashboard.
- **Inactivity.** GitHub may disable scheduled workflows in a repository with no activity for 60 days. The hourly commits should count as activity; if GitHub ever emails that the workflow was disabled, re-enable it from the Actions tab.
- **Missed hours can't be backfilled.** The free WeatherXM endpoint only gives the current reading, and past NWS forecasts aren't readily available.
- **Gust direction** isn't reported separately by WeatherXM or NWS; wind direction is used for both.
- **WeatherXM endpoint.** This uses the unauthenticated endpoint behind explorer.weatherxm.com. It isn't an official API and could change. With a WeatherXM Pro API key, `scripts/collect.py` could switch to `https://pro.weatherxm.com/api/v1/stations/{id}/latest` (and `/history` for backfilling gaps).
