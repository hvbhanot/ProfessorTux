"""
Professor Tux — Cybersecurity Teaching API (v3)
================================================
- Student chat at /
- Admin panel at /admin
- Dynamic teaching modes from .md skill files
- Lecture slide RAG pipeline
"""

import os
import shutil
import secrets
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from typing import Optional
from pydantic import BaseModel

from app.models import (
    ChatRequest, ChatResponse,
    SessionCreateRequest, SessionCreateResponse, SessionHistoryResponse,
    HealthResponse, ModeListResponse, ModeInfo,
    LectureUploadResponse, LectureListResponse, LectureDocumentInfo,
    LectureDeleteResponse, KnowledgeBaseStatsResponse,
    LectureSearchRequest, LectureSearchResponse, RetrievedChunkResponse,
)
from app.professor import ProfessorTux
from app.sessions import SessionManager
from app.rag import LectureKnowledgeBase, UPLOAD_DIR
from app.mode_loader import ModeLoader

logger = logging.getLogger("professor_tux")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)s  %(message)s")

# ── Admin credentials ────────────────────────────────────────────────
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "professortux")

# ── Globals ──────────────────────────────────────────────────────────
mode_loader = ModeLoader()
professor: ProfessorTux | None = None
sessions = SessionManager()
knowledge_base = LectureKnowledgeBase()
admin_tokens: set[str] = set()

# Admin-controlled defaults pushed to the student page
admin_config: dict = {
    "mode": "recall",
    "topic": "",
    "courseFilter": "",
    "useLectures": True,
}

STATIC_DIR = Path(__file__).parent / "static"


# ── Lifespan ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global professor
    # 1. Discover teaching modes
    n = mode_loader.discover()
    logger.info("📋 %d teaching mode(s) available: %s",
                n, ", ".join(mode_loader.available_modes))
    # Default admin mode to first discovered mode if current is invalid
    if not mode_loader.is_valid_mode(admin_config["mode"]):
        if mode_loader.available_modes:
            admin_config["mode"] = mode_loader.available_modes[0]
    # 2. Load model
    professor = ProfessorTux(mode_loader)
    professor.load_model()
    # 3. Init knowledge base
    knowledge_base.initialize()
    yield
    del professor
    professor = None


# ── App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Professor Tux 🐧",
    description="Cybersecurity teaching assistant with pluggable teaching modes and RAG.",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ── Auth helpers ─────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


def verify_admin(request: Request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    if auth[7:] not in admin_tokens:
        raise HTTPException(401, "Invalid or expired token")
    return auth[7:]


# ━━━━━━━━━━━━━━━━━━━━  FRONTEND  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/", include_in_schema=False)
async def student_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ━━━━━━━━━━━━━━━━━━━━  ADMIN AUTH  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/admin/login", tags=["Admin"])
async def admin_login(req: LoginRequest):
    if req.username == ADMIN_USERNAME and req.password == ADMIN_PASSWORD:
        token = secrets.token_hex(32)
        admin_tokens.add(token)
        return {"token": token}
    raise HTTPException(401, "Invalid credentials")


@app.get("/admin/verify", tags=["Admin"])
async def admin_verify(token: str = Depends(verify_admin)):
    return {"valid": True}


# ━━━━━━━━━━━━━━━━━━━━  ADMIN CONFIG  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/admin/config", tags=["Admin"])
async def get_config(token: str = Depends(verify_admin)):
    return admin_config


@app.put("/admin/config", tags=["Admin"])
async def update_config(request: Request, token: str = Depends(verify_admin)):
    global admin_config
    body = await request.json()
    new_mode = body.get("mode", admin_config["mode"])
    if not mode_loader.is_valid_mode(new_mode):
        raise HTTPException(400, f"Unknown mode: {new_mode}")
    admin_config.update({
        "mode": new_mode,
        "topic": body.get("topic", admin_config["topic"]),
        "courseFilter": body.get("courseFilter", admin_config["courseFilter"]),
        "useLectures": body.get("useLectures", admin_config["useLectures"]),
    })
    return admin_config


@app.get("/admin/config/public", tags=["Admin"])
async def get_public_config():
    """Student page reads this to auto-configure sessions."""
    return admin_config


# ━━━━━━━━━━━━━━━━━━━━  MODES  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/modes", response_model=ModeListResponse, tags=["Modes"])
async def list_modes():
    """List all available teaching modes (auto-discovered from .md files)."""
    modes = mode_loader.list_modes()
    return ModeListResponse(
        total=len(modes),
        modes=[ModeInfo(**m) for m in modes],
    )


@app.post("/modes/reload", tags=["Modes"])
async def reload_modes(token: str = Depends(verify_admin)):
    """Hot-reload mode files without restarting the server."""
    n = mode_loader.reload()
    return {"reloaded": n, "modes": mode_loader.available_modes}


# ━━━━━━━━━━━━━━━━━━━━  SYSTEM  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    kb_stats = knowledge_base.get_stats() if knowledge_base.is_loaded else {}
    return HealthResponse(
        status="online" if professor and professor.is_loaded else "loading",
        model_loaded=professor.is_loaded if professor else False,
        knowledge_base_loaded=knowledge_base.is_loaded,
        total_lecture_chunks=kb_stats.get("total_chunks", 0),
        available_modes=mode_loader.available_modes,
    )


# ━━━━━━━━━━━━━━━━━━━━  SESSIONS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/sessions", response_model=SessionCreateResponse, tags=["Sessions"])
async def create_session(req: SessionCreateRequest):
    if not mode_loader.is_valid_mode(req.mode):
        raise HTTPException(400, f"Unknown mode: {req.mode}. Available: {mode_loader.available_modes}")
    session = sessions.create(
        mode=req.mode, topic=req.topic,
        course_filter=req.course_filter, use_lectures=req.use_lectures,
    )
    mode_def = mode_loader.get_mode(req.mode)
    return SessionCreateResponse(
        session_id=session["session_id"],
        mode=session["mode"],
        topic=session["topic"],
        use_lectures=session["use_lectures"],
        course_filter=session["course_filter"],
        welcome_message=_welcome_message(mode_def, session["topic"], session["use_lectures"]),
    )


@app.get("/sessions/{session_id}", response_model=SessionHistoryResponse, tags=["Sessions"])
async def get_session(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    return SessionHistoryResponse(**session)


@app.patch("/sessions/{session_id}/mode", tags=["Sessions"])
async def switch_mode(session_id: str, mode: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    if not mode_loader.is_valid_mode(mode):
        raise HTTPException(400, f"Unknown mode: {mode}")
    sessions.update_mode(session_id, mode)
    return {"session_id": session_id, "new_mode": mode}


# ━━━━━━━━━━━━━━━━━━━━  CHAT  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(req: ChatRequest):
    if not professor or not professor.is_loaded:
        raise HTTPException(503, "Model is still loading")

    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    active_mode = req.mode_override or session["mode"]
    if req.mode_override:
        if not mode_loader.is_valid_mode(req.mode_override):
            raise HTTPException(400, f"Unknown mode: {req.mode_override}")
        sessions.update_mode(req.session_id, req.mode_override)

    # RAG retrieval
    lecture_context = ""
    sources_used = []

    if session.get("use_lectures", True) and knowledge_base.is_loaded:
        search_query = req.message
        if session.get("topic"):
            search_query = f"{session['topic']}: {search_query}"

        contexts = knowledge_base.search(
            query=search_query, top_k=5,
            course_filter=session.get("course_filter"),
        )
        if contexts:
            lecture_context = knowledge_base.format_context_for_prompt(contexts)
            sources_used = list(set(
                f"{c.source_filename} (slide {c.page_or_slide})"
                for c in contexts if c.relevance_score >= 0.3
            ))

    # Generate
    response_text = professor.generate(
        student_message=req.message,
        mode_id=active_mode,
        topic=session["topic"],
        history=session["history"],
        lecture_context=lecture_context,
    )

    sessions.add_message(req.session_id, role="student", content=req.message)
    sessions.add_message(req.session_id, role="professor_tux", content=response_text)

    return ChatResponse(
        session_id=req.session_id,
        mode=active_mode,
        response=response_text,
        hint=mode_loader.get_hint(active_mode),
        sources_used=sources_used,
    )


# ━━━━━━━━━━━━━━━━━━━━  LECTURES  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.post("/lectures/upload", response_model=LectureUploadResponse, tags=["Lectures"])
async def upload_lecture(
    file: UploadFile = File(...),
    course: Optional[str] = Form(None),
    lecture_title: Optional[str] = Form(None),
):
    if not knowledge_base.is_loaded:
        raise HTTPException(503, "Knowledge base not ready")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".pdf", ".pptx", ".ppt", ".txt", ".md"}:
        raise HTTPException(400, f"Unsupported file type: {suffix}")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_path = Path(UPLOAD_DIR) / file.filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        doc = knowledge_base.ingest_file(str(file_path), course, lecture_title)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Ingestion failed: %s", e, exc_info=True)
        raise HTTPException(500, str(e))

    return LectureUploadResponse(
        doc_id=doc.doc_id, filename=doc.filename, course=doc.course,
        lecture_title=doc.lecture_title, file_type=doc.file_type,
        num_pages=doc.num_pages, num_chunks=doc.num_chunks,
        message=f"✅ {doc.filename}: {doc.num_pages} pages → {doc.num_chunks} chunks",
    )


@app.get("/lectures", response_model=LectureListResponse, tags=["Lectures"])
async def list_lectures():
    docs = knowledge_base.list_documents()
    return LectureListResponse(total=len(docs), documents=[LectureDocumentInfo(**d) for d in docs])


@app.delete("/lectures/{doc_id}", response_model=LectureDeleteResponse, tags=["Lectures"])
async def delete_lecture(doc_id: str):
    if not knowledge_base.delete_document(doc_id):
        raise HTTPException(404, "Document not found")
    return LectureDeleteResponse(doc_id=doc_id, deleted=True, message="Deleted")


@app.post("/lectures/search", response_model=LectureSearchResponse, tags=["Lectures"])
async def search_lectures(req: LectureSearchRequest):
    if not knowledge_base.is_loaded:
        raise HTTPException(503, "Knowledge base not ready")
    contexts = knowledge_base.search(req.query, req.top_k, req.course_filter)
    return LectureSearchResponse(
        query=req.query,
        results=[RetrievedChunkResponse(
            text=c.text, source_filename=c.source_filename,
            lecture_title=c.lecture_title, course=c.course,
            page_or_slide=c.page_or_slide, relevance_score=c.relevance_score,
        ) for c in contexts],
    )


@app.get("/lectures/stats/overview", response_model=KnowledgeBaseStatsResponse, tags=["Lectures"])
async def knowledge_base_stats():
    if not knowledge_base.is_loaded:
        raise HTTPException(503, "Knowledge base not ready")
    return KnowledgeBaseStatsResponse(**knowledge_base.get_stats())


# ━━━━━━━━━━━━━━━━━━━━  HELPERS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _welcome_message(mode_def, topic: str | None, use_lectures: bool) -> str:
    topic_str = f" on **{topic}**" if topic else ""
    lec_str = ("\n📚 I have access to your lecture slides and will reference them."
               if use_lectures else "")
    icon = mode_def.icon if mode_def else "🐧"
    name = mode_def.name if mode_def else "Unknown Mode"
    desc = mode_def.description if mode_def else ""

    return (
        f"🐧 Welcome, student! I'm Professor Tux.\n\n"
        f"{icon} We're in **{name}**{topic_str}.\n"
        f"{desc}\n"
        f"What would you like to explore?{lec_str}"
    )
