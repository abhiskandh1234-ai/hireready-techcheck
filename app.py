from fastapi import FastAPI, HTTPException, Request, Response, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from typing import Optional, List, Literal
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, String, Integer, Text, ForeignKey, select, func, or_
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from sqlalchemy.exc import IntegrityError
import hashlib
import hmac
import secrets
import os
import csv
import io

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
APP_NAME = os.getenv("HIREREADY_BRAND_NAME", "HireReady TechCheck")
BRAND_TAGLINE = os.getenv("HIREREADY_BRAND_TAGLINE", "AI-assisted technical readiness and support")


def normalize_database_url(url: str) -> str:
    """Use psycopg v3 for PostgreSQL URLs supplied by Neon/Render."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


raw_database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'hireready.db'}")
DATABASE_URL = normalize_database_url(raw_database_url)
IS_POSTGRES = DATABASE_URL.startswith("postgresql+")
engine_kwargs = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite://"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class SessionToken(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(String(180), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expires_at: Mapped[str] = mapped_column(String(64), nullable=False)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_code: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    candidate_name: Mapped[str] = mapped_column(String(160), nullable=False)
    candidate_email: Mapped[str] = mapped_column(String(320), nullable=False)
    category: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="Open")
    interview_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    readiness_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    system_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


app = FastAPI(title=f"{APP_NAME} V11")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def utc_now():
    return datetime.now(timezone.utc)


def hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()


def verify_password(password: str, salt_hex: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_password(password, salt_hex), expected_hash)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(engine)

    # Production admin credentials should come from Render environment variables.
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_name = os.getenv("ADMIN_NAME", "HireReady Admin")

    # Convenient local-only fallback. These values are never shown in the UI.
    if not admin_email and not os.getenv("RENDER"):
        admin_email = "admin@hireready.local"
    if not admin_password and not os.getenv("RENDER"):
        admin_password = "HireReady@123"

    if admin_email and admin_password:
        with SessionLocal() as db:
            existing = db.scalar(select(User).where(User.email == admin_email.strip().lower()))
            if not existing:
                salt = secrets.token_hex(16)
                db.add(User(
                    name=admin_name,
                    email=admin_email.strip().lower(),
                    password_hash=hash_password(admin_password, salt),
                    salt=salt,
                    role="admin",
                    created_at=utc_now().isoformat(),
                ))
                db.commit()


def create_session(db: Session, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(days=7)
    db.add(SessionToken(token=token, user_id=user_id, expires_at=expires.isoformat()))
    return token


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("hireready_session")
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")

    row = db.execute(
        select(User, SessionToken.expires_at)
        .join(SessionToken, User.id == SessionToken.user_id)
        .where(SessionToken.token == token)
    ).first()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid session")

    user, expires_at = row
    if datetime.fromisoformat(expires_at) < utc_now():
        session_row = db.get(SessionToken, token)
        if session_row:
            db.delete(session_row)
            db.commit()
        raise HTTPException(status_code=401, detail="Session expired")

    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


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
        "Camera", "Microphone", "Internet / Wi-Fi", "Browser",
        "Speaker / Audio", "Slow laptop", "Interview / Assessment", "Other",
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
    escalation_reason: str = Field(description="When and why the user should escalate to support.")


class TicketBody(BaseModel):
    category: str
    description: str
    interview_minutes: int
    readiness_score: Optional[int] = None
    system_report: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_priority: Optional[Literal["Low", "Medium", "High"]] = None


def ticket_dict(t: Ticket):
    return {
        "id": t.id,
        "ticket_code": t.ticket_code,
        "candidate_id": t.candidate_id,
        "candidate_name": t.candidate_name,
        "candidate_email": t.candidate_email,
        "category": t.category,
        "description": t.description,
        "priority": t.priority,
        "status": t.status,
        "interview_minutes": t.interview_minutes,
        "readiness_score": t.readiness_score,
        "system_report": t.system_report,
        "ai_summary": t.ai_summary,
        "created_at": t.created_at,
        "resolved_at": t.resolved_at,
    }


@app.get("/")
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(select(1))
    return {
        "ok": True,
        "app": APP_NAME,
        "version": "V11",
        "database": "PostgreSQL" if IS_POSTGRES else "SQLite",
    }


@app.get("/api/brand")
def brand():
    return {
        "name": APP_NAME,
        "tagline": BRAND_TAGLINE,
        "version": "V11",
        "prototype_notice": "Independent portfolio prototype",
        "database": "PostgreSQL" if IS_POSTGRES else "SQLite",
    }


@app.post("/api/register")
def register(body: RegisterBody, response: Response, db: Session = Depends(get_db)):
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
    user = User(
        name=name, email=email,
        password_hash=hash_password(password, salt), salt=salt,
        role="candidate", created_at=utc_now().isoformat(),
    )
    try:
        db.add(user)
        db.flush()
        token = create_session(db, user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email is already registered")

    response.set_cookie(
        "hireready_session", token,
        httponly=True, samesite="lax", secure=bool(os.getenv("RENDER")),
        max_age=7 * 24 * 60 * 60,
    )
    return {"ok": True, "name": name, "email": email, "role": "candidate"}


@app.post("/api/login")
def login(body: LoginBody, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user or not verify_password(body.password, user.salt, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_session(db, user.id)
    db.commit()
    response.set_cookie(
        "hireready_session", token,
        httponly=True, samesite="lax", secure=bool(os.getenv("RENDER")),
        max_age=7 * 24 * 60 * 60,
    )
    return {"ok": True, "name": user.name, "email": user.email, "role": user.role}


@app.post("/api/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("hireready_session")
    if token:
        session_row = db.get(SessionToken, token)
        if session_row:
            db.delete(session_row)
            db.commit()
    response.delete_cookie("hireready_session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


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
        raise HTTPException(status_code=503, detail="Gemini API key is not configured on the backend.")

    issue = body.issue.strip()
    if len(issue) < 5:
        raise HTTPException(status_code=400, detail="Describe the technical problem in more detail.")

    try:
        from google import genai
    except ImportError:
        raise HTTPException(status_code=500, detail="google-genai is not installed. Run pip install -r requirements.txt.")

    client = genai.Client(api_key=api_key)
    model = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
    system_instruction = """
You are HireReady TechCheck, a cautious IT support assistant for job candidates
preparing for legitimate online interviews and assessments.

Diagnose ordinary end-user technical problems involving camera, microphone,
speakers, browser permissions, connectivity, performance, or interview/assessment pages.

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
                "type": "text", "mime_type": "application/json",
                "schema": AIAnalysis.model_json_schema(),
            },
        )
        return AIAnalysis.model_validate_json(interaction.output_text)
    except Exception as exc:
        print("Gemini API error:", repr(exc))
        raise HTTPException(
            status_code=502,
            detail="The AI service could not complete the request. Check the API key, model, quota, and internet connection."
        )


@app.post("/api/tickets")
def create_ticket(body: TicketBody, user=Depends(current_user), db: Session = Depends(get_db)):
    if user["role"] != "candidate":
        raise HTTPException(status_code=403, detail="Candidate account required")
    description = body.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Issue description is required")

    time_priority = "High" if body.interview_minutes <= 30 else "Medium" if body.interview_minutes <= 180 else "Low"
    rank = {"Low": 1, "Medium": 2, "High": 3}
    final_priority = time_priority
    if body.ai_priority and rank[body.ai_priority] > rank[final_priority]:
        final_priority = body.ai_priority

    ticket_code = "HR-" + datetime.now().strftime("%H%M%S") + secrets.token_hex(2).upper()
    ticket = Ticket(
        ticket_code=ticket_code,
        candidate_id=user["id"], candidate_name=user["name"], candidate_email=user["email"],
        category=body.category.strip() or "Other", description=description,
        priority=final_priority, status="Open", interview_minutes=body.interview_minutes,
        readiness_score=body.readiness_score, system_report=body.system_report,
        ai_summary=body.ai_summary, created_at=utc_now().isoformat(), resolved_at=None,
    )
    db.add(ticket)
    db.commit()
    return {"ok": True, "ticket_code": ticket_code, "priority": final_priority}


@app.get("/api/tickets")
def list_tickets(
    status: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user=Depends(current_user), db: Session = Depends(get_db),
):
    stmt = select(Ticket)
    if user["role"] != "admin":
        stmt = stmt.where(Ticket.candidate_id == user["id"])
    if status:
        stmt = stmt.where(Ticket.status == status)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if category:
        stmt = stmt.where(Ticket.category == category)
    if search:
        q = f"%{search}%"
        stmt = stmt.where(or_(
            Ticket.ticket_code.ilike(q), Ticket.candidate_name.ilike(q),
            Ticket.candidate_email.ilike(q), Ticket.description.ilike(q),
        ))
    tickets = db.scalars(stmt.order_by(Ticket.id.desc())).all()
    return [ticket_dict(t) for t in tickets]


@app.post("/api/tickets/{ticket_code}/resolve")
def resolve_ticket(ticket_code: str, admin=Depends(require_admin), db: Session = Depends(get_db)):
    ticket = db.scalar(select(Ticket).where(Ticket.ticket_code == ticket_code))
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket.status = "Resolved"
    ticket.resolved_at = utc_now().isoformat()
    db.commit()
    return {"ok": True}


@app.get("/api/admin/stats")
def admin_stats(admin=Depends(require_admin), db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(Ticket.id))) or 0
    open_count = db.scalar(select(func.count(Ticket.id)).where(Ticket.status == "Open")) or 0
    high = db.scalar(select(func.count(Ticket.id)).where(Ticket.priority == "High", Ticket.status == "Open")) or 0
    resolved = db.scalar(select(func.count(Ticket.id)).where(Ticket.status == "Resolved")) or 0
    avg_score = db.scalar(select(func.avg(Ticket.readiness_score)).where(Ticket.readiness_score.is_not(None)))
    category_rows = db.execute(select(Ticket.category, func.count(Ticket.id)).group_by(Ticket.category).order_by(func.count(Ticket.id).desc())).all()
    priority_rows = db.execute(select(Ticket.priority, func.count(Ticket.id)).group_by(Ticket.priority).order_by(func.count(Ticket.id).desc())).all()
    return {
        "total": total, "open": open_count, "high": high, "resolved": resolved,
        "resolution_rate": round((resolved / total * 100), 1) if total else 0,
        "average_readiness": round(float(avg_score), 1) if avg_score is not None else None,
        "categories": [{"category": r[0], "count": r[1]} for r in category_rows],
        "priorities": [{"priority": r[0], "count": r[1]} for r in priority_rows],
    }


@app.get("/api/admin/export.csv")
def export_csv(admin=Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(Ticket).order_by(Ticket.id.desc())).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ticket_code", "candidate_name", "candidate_email", "category", "priority",
        "status", "interview_minutes", "readiness_score", "ai_summary", "description",
        "created_at", "resolved_at"
    ])
    for t in rows:
        writer.writerow([
            t.ticket_code, t.candidate_name, t.candidate_email, t.category, t.priority,
            t.status, t.interview_minutes, t.readiness_score, t.ai_summary, t.description,
            t.created_at, t.resolved_at,
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=hireready_tickets.csv"},
    )


init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8006")), reload=False)
