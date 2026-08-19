# HireReady TechCheck V6 — Professional White-Label Prototype

V6 upgrades the working V5 full-stack AI prototype into a recruiter/company-demo-quality product concept.

## New in V6

- Professional product landing panel
- White-label backend brand configuration
- Candidate registration/login
- System readiness checks
- Real Gemini AI troubleshooting
- AI-assisted support tickets
- Admin analytics dashboard
- Resolution rate + average readiness metrics
- Category and priority analytics
- Ticket search and filters
- CSV ticket export
- Dockerfile and environment configuration

## Run on Windows

Open CMD inside this folder and run:

```bat
python -m pip install -r requirements.txt
```

Set your Gemini API key:

```bat
set GEMINI_API_KEY=YOUR_KEY_HERE
set GEMINI_MODEL=gemini-3.7-flash
```

Start the app:

```bat
python app.py
```

Open:

```text
http://localhost:8005
```

Or double-click `start_v6.bat`.

## Demo admin

Email: `admin@hireready.local`

Password: `HireReady@123`

Change this before any public deployment.

## White-label branding

You can configure product branding before starting:

```bat
set HIREREADY_BRAND_NAME=Company Candidate TechCheck
set HIREREADY_BRAND_TAGLINE=Interview readiness and candidate technical support
python app.py
```

Keep the product marked as an independent concept unless the company has actually authorized or commissioned it.

## Docker

```bash
docker build -t hireready-v6 .
docker run --rm -p 8005:8005 -e GEMINI_API_KEY=YOUR_KEY hireready-v6
```

## Production note

V6 is deployment-structured, but SQLite remains a prototype database. Before a real public SaaS launch, migrate to PostgreSQL and add HTTPS, production secrets management, CSRF protection, rate limiting, email verification/password reset, audit logs, stronger session controls, backups, privacy/retention controls, and monitoring.

## Pitch positioning

Use wording like:

> Independent concept prototype showing how candidate technical readiness, AI troubleshooting, and helpdesk escalation could be unified into one workflow.
