# Trading Dashboard - Render-safe replacement

This package replaces the prior threaded design with a Render-safe Streamlit app.

## Why this version is different
- No background thread
- Direct polling during reruns
- Visible environment diagnostics
- Visible Polygon request failures
- Starts from `app.py` so it matches `render.yaml`

## Files included
- `app.py`
- `app_polygon_only.py`
- `render.yaml`
- `requirements.txt`

## Deploy steps
1. Replace the existing files with these.
2. Commit and push.
3. In Render, confirm `POLYGON_API_KEY` is set.
4. Open the app and use **Force refresh now** once.

## What you should see
- `Scanner Status` should change from `Waiting` once Polygon returns data.
- `Environment check` will show whether `POLYGON_API_KEY` is present.
- `Errors` will show any HTTP or request failures instead of silently staying empty.
