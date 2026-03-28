# Trading Dashboard - Flattened GitHub Upload

Upload these files directly to the **root** of your GitHub repo.

Your repo should look like this:

- render.yaml
- app.py
- requirements.txt
- README.md
- .env.example

## Render Blueprint
After uploading these files:

1. Commit to `main`
2. In Render, run **Manual Deploy -> Deploy latest commit**
3. Add your secrets in Render under **Environment**

## Required environment variables
- TWILIO_ACCOUNT_SID
- TWILIO_AUTH_TOKEN
- TWILIO_FROM
- TWILIO_TO
- POLYGON_API_KEY

This package is intentionally minimal so Render can start cleanly.
Once it is live, the full scanner logic can be layered back in.
