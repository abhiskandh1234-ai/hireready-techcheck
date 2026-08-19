from fastapi import FastAPI, HTTPException, Request, Response, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional, List, Literal
import sqlite3
import hashlib
import hmac
import secrets
import os
import csv
import io
from datetime import datetime, timedelta, timezone

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("HIREREADY_DB_PATH", str(BASE_DIR / "hireready.db")))
STATIC_DIR = BASE_DIR / "static"
APP_NAME = os.getenv("HIREREADY_BRAND_NAME", "HireReady TechCheck")
BRAND_TAGLINE = os.getenv("HIREREADY_BRAND_TAGLINE", "AI-powered interview readiness and technical support")

app = FastAPI(title=f"{APP_NAME} V7")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- DATABASE ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now():
    return datetime.now(timezone.utc)


def hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 200_000
    )
    return derived.hex()


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt_hex), expected_hash)


def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('candidate','admin')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_code TEXT UNIQUE NOT NULL,
            candidate_id INTEGER NOT NULL,
            candidate_name TEXT NOT NULL,
            candidate_email TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            interview_minutes INTEGER NOT NULL,
            readiness_score INTEGER,
            system_report TEXT,
            ai_summary TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            FOREIGN KEY(candidate_id) REFERENCES users(id)
        );
        """)

        # Upgrade an older V4 database if necessary.
        cols = [r["name"] for r in db.execute("PRAGMA table_info(tickets)").fetchall()]
        if "ai_summary" not in cols:
            db.execute("ALTER TABLE tickets ADD COLUMN ai_summary TEXT")

        existing = db.execute(
            "SELECT id FROM users WHERE email = ?",
            ("admin@hireready.local",)
        ).fetchone()

        if not existing:
            salt = secrets.token_hex(16)
            db.execute(
                """INSERT INTO users
                (name, email, password_hash, salt, role, created_at)
                VALUES (?, ?, ?, ?, 'admin', ?)""",
                (
                    "HireReady Admin",
                    "admin@hireready.local",
                    hash_password("HireReady@123", salt),
                    salt,
                    utc_now().isoformat(),
                ),
            )
        db.commit()


# ---------- AUTH ----------

def create_session(db, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(days=7)
    db.execute(
        "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires.isoformat()),
    )
    db.commit()
    return token


def current_user(request: Request):
    token = request.cookies.get("hireready_session")
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    with get_db() as db:
        row = db.execute(
            """
            SELECT u.id, u.name, u.email, u.role, s.expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="Invalid session")

        if datetime.fromisoformat(row["expires_at"]) < utc_now():
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            db.commit()
            raise HTTPException(status_code=401, detail="Session expired")

        return dict(row)


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---------- API MODELS ----------

class RegisterBody(BaseModel):
    name: str
    email: str
    password: str


class LoginBody(BaseModel):
    email: str
    password: str


class AIRequest(BaseModel):
    issue: str
    interview_minutes: int = 60
    readiness_score: Optional[int] = None
    system_report: Optional[str] = None


class AIAnalysis(BaseModel):
    category: Literal[
        "Camera",
        "Microphone",
        "Internet / Wi-Fi",
        "Browser",
        "Speaker / Audio",
        "Slow laptop",
        "Interview / Assessment",
        "Other",
    ] = Field(description="Most relevant technical issue category.")
    priority: Literal["Low", "Medium", "High"] = Field(
        description="Urgency based on technical impact and how soon the interview starts."
    )
    likely_cause: str = Field(description="Short likely cause of the problem.")
    summary: str = Field(description="Short support-ticket-ready summary.")
    steps: List[str] = Field(
        min_length=3, max_length=7,
        description="Safe practical troubleshooting steps ordered from easiest to more advanced."
    )
    escalation_reason: str = Field(
        description="When and why the user should escalate to support."
    )


class TicketBody(BaseModel):
    category: str
    description: str
    interview_minutes: int
    readiness_score: Optional[int] = None
    system_report: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_priority: Optional[Literal["Low", "Medium", "High"]] = None


# ---------- FRONTEND ----------

@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/brand")
def brand():
    return {
        "name": APP_NAME,
        "tagline": BRAND_TAGLINE,
        "version": "V7",
        "prototype_notice": "Independent unofficial concept prototype",
    }


# ---------- AUTH ROUTES ----------

@app.post("/api/register")
def register(body: RegisterBody, response: Response):
    name = body.name.strip()
    email = body.email.strip().lower()
    password = body.password

    if len(name) < 2:
        raise HTTPException(status_code=400, detail="Enter your full name")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    salt = secrets.token_hex(16)
    try:
        with get_db() as db:
            cur = db.execute(
                """INSERT INTO users
                (name, email, password_hash, salt, role, created_at)
                VALUES (?, ?, ?, ?, 'candidate', ?)""",
                (
                    name, email, hash_password(password, salt),
                    salt, utc_now().isoformat()
                ),
            )
            token = create_session(db, cur.lastrowid)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Email is already registered")

    response.set_cookie(
        "hireready_session", token,
        httponly=True, samesite="lax",
        max_age=7 * 24 * 60 * 60
    )
    return {"ok": True, "name": name, "email": email, "role": "candidate"}


@app.post("/api/login")
def login(body: LoginBody, response: Response):
    email = body.email.strip().lower()

    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or not verify_password(
            body.password, user["salt"], user["password_hash"]
        ):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = create_session(db, user["id"])

    response.set_cookie(
        "hireready_session", token,
        httponly=True, samesite="lax",
        max_age=7 * 24 * 60 * 60
    )
    return {
        "ok": True,
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
    }


@app.post("/api/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("hireready_session")
    if token:
        with get_db() as db:
            db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            db.commit()
    response.delete_cookie("hireready_session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
    }


# ---------- REAL AI ----------

@app.get("/api/ai/status")
def ai_status(user=Depends(current_user)):
    return {
        "configured": bool(os.getenv("GEMINI_API_KEY")),
        "model": os.getenv("GEMINI_MODEL", "gemini-3.7-flash"),
    }


@app.post("/api/ai/troubleshoot", response_model=AIAnalysis)
def ai_troubleshoot(body: AIRequest, user=Depends(current_user)):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key is not configured on the backend."
        )

    issue = body.issue.strip()
    if len(issue) < 5:
        raise HTTPException(status_code=400, detail="Describe the technical problem in more detail.")

    try:
        from google import genai
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="google-genai is not installed. Run pip install -r requirements.txt."
        )

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")

    system_instruction = """
You are HireReady TechCheck, a cautious IT support assistant for job candidates
preparing for legitimate online interviews and assessments.

Diagnose ordinary end-user technical problems involving:
camera, microphone, speakers, browser permissions, connectivity, performance,
or interview/assessment pages.

Rules:
- Give safe, reversible troubleshooting only.
- Do not suggest bypassing employer security, proctoring, monitoring, authentication,
  access controls, assessment restrictions, or anti-cheating systems.
- Never ask for passwords, OTPs, tokens, private keys, or confidential employer data.
- Prefer simple checks before advanced steps.
- Keep steps clear enough for a non-expert Windows user.
- If the issue could be caused by an employer-side outage or locked policy, say to
  capture the error and contact official support rather than bypassing it.
"""

    prompt = f"""
Candidate issue:
{issue}

Interview starts in: {body.interview_minutes} minutes.
Current readiness score: {body.readiness_score if body.readiness_score is not None else "not available"}.

System report:
{body.system_report or "not available"}

Return a concise technical diagnosis and support-ready recommendation.
"""

    try:
        interaction = client.interactions.create(
            model=model,
            system_instruction=system_instruction,
            input=prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": AIAnalysis.model_json_schema(),
            },
        )
        return AIAnalysis.model_validate_json(interaction.output_text)

    except Exception as exc:
        # Keep detailed provider errors out of the browser while still making local debugging useful.
        print("Gemini API error:", repr(exc))
        raise HTTPException(
            status_code=502,
            detail="The AI service could not complete the request. Check the API key, model, quota, and internet connection."
        )


# ---------- TICKETS ----------

@app.post("/api/tickets")
def create_ticket(body: TicketBody, user=Depends(current_user)):
    if user["role"] != "candidate":
        raise HTTPException(status_code=403, detail="Candidate account required")

    description = body.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Issue description is required")

    time_priority = (
        "High" if body.interview_minutes <= 30
        else "Medium" if body.interview_minutes <= 180
        else "Low"
    )

    rank = {"Low": 1, "Medium": 2, "High": 3}
    final_priority = time_priority
    if body.ai_priority and rank[body.ai_priority] > rank[final_priority]:
        final_priority = body.ai_priority

    ticket_code = "HR-" + datetime.now().strftime("%H%M%S") + secrets.token_hex(2).upper()

    with get_db() as db:
        db.execute(
            """INSERT INTO tickets (
                ticket_code, candidate_id, candidate_name, candidate_email,
                category, description, priority, status, interview_minutes,
                readiness_score, system_report, ai_summary, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Open', ?, ?, ?, ?, ?)""",
            (
                ticket_code,
                user["id"],
                user["name"],
                user["email"],
                body.category,
                description,
                final_priority,
                body.interview_minutes,
                body.readiness_score,
                body.system_report,
                body.ai_summary,
                utc_now().isoformat(),
            ),
        )
        db.commit()

    return {
        "ok": True,
        "ticket_code": ticket_code,
        "priority": final_priority
    }


@app.get("/api/tickets")
def list_tickets(
    status: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user=Depends(current_user),
):
    clauses = []
    params = []

    if user["role"] != "admin":
        clauses.append("candidate_id = ?")
        params.append(user["id"])
    if status:
        clauses.append("status = ?")
        params.append(status)
    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    if category:
        clauses.append("category = ?")
        params.append(category)
    if search:
        clauses.append("(ticket_code LIKE ? OR candidate_name LIKE ? OR candidate_email LIKE ? OR description LIKE ?)")
        q = f"%{search}%"
        params.extend([q, q, q, q])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_db() as db:
        rows = db.execute(
            f"SELECT * FROM tickets{where} ORDER BY id DESC",
            tuple(params),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/tickets/{ticket_code}/resolve")
def resolve_ticket(ticket_code: str, admin=Depends(require_admin)):
    with get_db() as db:
        result = db.execute(
            """UPDATE tickets
            SET status = 'Resolved', resolved_at = ?
            WHERE ticket_code = ?""",
            (utc_now().isoformat(), ticket_code),
        )
        db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Ticket not found")

    return {"ok": True}


@app.get("/api/admin/stats")
def admin_stats(admin=Depends(require_admin)):
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) n FROM tickets").fetchone()["n"]
        open_count = db.execute("SELECT COUNT(*) n FROM tickets WHERE status='Open'").fetchone()["n"]
        high = db.execute("SELECT COUNT(*) n FROM tickets WHERE priority='High' AND status='Open'").fetchone()["n"]
        resolved = db.execute("SELECT COUNT(*) n FROM tickets WHERE status='Resolved'").fetchone()["n"]
        avg_score = db.execute("SELECT AVG(readiness_score) v FROM tickets WHERE readiness_score IS NOT NULL").fetchone()["v"]
        categories = db.execute("SELECT category, COUNT(*) count FROM tickets GROUP BY category ORDER BY count DESC").fetchall()
        priorities = db.execute("SELECT priority, COUNT(*) count FROM tickets GROUP BY priority ORDER BY count DESC").fetchall()

    return {
        "total": total,
        "open": open_count,
        "high": high,
        "resolved": resolved,
        "resolution_rate": round((resolved / total * 100), 1) if total else 0,
        "average_readiness": round(avg_score, 1) if avg_score is not None else None,
        "categories": [dict(r) for r in categories],
        "priorities": [dict(r) for r in priorities],
    }


@app.get("/api/admin/export.csv")
def export_csv(admin=Depends(require_admin)):
    with get_db() as db:
        rows = db.execute(
            """SELECT ticket_code, candidate_name, candidate_email, category, priority,
            status, interview_minutes, readiness_score, ai_summary, description, created_at, resolved_at
            FROM tickets ORDER BY id DESC"""
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ticket_code", "candidate_name", "candidate_email", "category", "priority",
        "status", "interview_minutes", "readiness_score", "ai_summary", "description",
        "created_at", "resolved_at"
    ])
    for row in rows:
        writer.writerow(list(row))
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hireready_tickets.csv"},
    )


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8005, reload=False)
