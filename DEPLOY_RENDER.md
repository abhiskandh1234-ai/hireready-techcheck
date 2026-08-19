# HireReady V7 — First Live Deploy

## GitHub
Create a repository named `hireready-techcheck` and upload the CONTENTS of this folder to the repository root.

The GitHub root should show:
- app.py
- requirements.txt
- render.yaml
- static/
- README.md

Never upload an API key.

## Render
Create a new Web Service from the GitHub repository.

Use:
- Runtime: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`

Environment variables:
- `GEMINI_API_KEY` = your current private Gemini API key
- `GEMINI_MODEL` = `gemini-3.7-flash`
- `HIREREADY_BRAND_NAME` = `HireReady TechCheck`
- `HIREREADY_BRAND_TAGLINE` = `AI-powered interview readiness and technical support`

Do not put secret values in GitHub files.

## Important
This first live build still uses SQLite. It is for verifying the public deployment flow. Cloud-persistent PostgreSQL is the next step after the Render URL works.
