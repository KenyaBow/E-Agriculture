# FarmPulse

A mobile-first Flask PWA for farm weather, leaf and soil analysis, chatbot guidance, irrigation planning, crop recommendations, disease risk, market timing, and report downloads.

## Run locally

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
py app.py
```

Open http://127.0.0.1:5000

## Notes

- Weather uses Open-Meteo when available and falls back to a local planning outlook if network access is unavailable.
- The app is portrait-oriented and installable as a PWA.
- Reports are stored in memory per browser client.
