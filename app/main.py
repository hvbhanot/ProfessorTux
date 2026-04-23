"""Professor Tux — cybersecurity teaching API. Chat, modes, lecture RAG, admin."""

import os
import json
import re
import shlex
import time
import random
import shutil
import secrets
import logging
import threading
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from contextlib import asynccontextmanager
from typing import Optional
import requests as _requests
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
from app.chat_logger import ChatLogger, ChatLogEntry
from app.llm_backends import (
    BackendError,
    OllamaBackend,
    WebSearchConfigurationError,
    configure_ollama_web_search,
    ollama_web_search,
    ollama_web_search_base_url,
    ollama_web_search_configured,
)

LOG_FILE_DIR = Path(os.getenv("CHAT_LOG_DIR", "./data/logs"))
RUNTIME_SETTINGS_PATH = Path("./data/admin_runtime.json")

logger = logging.getLogger("professor_tux")
logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(name)s  %(message)s")

os.makedirs(LOG_FILE_DIR, exist_ok=True)
_file_handler = logging.FileHandler(LOG_FILE_DIR / "professor_tux.log", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter("%(asctime)s  %(name)s  %(levelname)s  %(message)s"))
logging.getLogger().addHandler(_file_handler)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "professortux")

mode_loader = ModeLoader()
professor: ProfessorTux | None = None
sessions = SessionManager()
knowledge_base = LectureKnowledgeBase()
chat_logger = ChatLogger()
admin_tokens: set[str] = set()
model_operation_lock = threading.Lock()
model_operation: dict = {
    "state": "idle",
    "provider": "",
    "model": "",
    "status": "",
    "error": "",
    "progress": None,
    "started_at": "",
    "updated_at": "",
}
runtime_settings_lock = threading.Lock()
runtime_settings: dict = {
    "ollama_base_url": "",
    "ollama_api_key": "",
    "ollama_web_search_base_url": "",
    "max_tokens": None,
}

WRONG_MODE_ERROR_RATE = 0.10

# Admin-controlled defaults pushed to the student page
admin_config: dict = {
    "mode": "recall",
    "topic": "",
    "courseFilter": "",
    "useLectures": True,
    "maxTokens": int(os.getenv("MAX_TOKENS", "1024")),
}

STATIC_DIR = Path(__file__).parent / "static"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_runtime_settings():
    if not RUNTIME_SETTINGS_PATH.exists():
        return
    try:
        data = json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to load runtime settings: %s", exc)
        return

    if not isinstance(data, dict):
        return

    with runtime_settings_lock:
        runtime_settings["ollama_base_url"] = str(data.get("ollama_base_url", "") or "").strip()
        runtime_settings["ollama_api_key"] = str(data.get("ollama_api_key", "") or "").strip()
        runtime_settings["ollama_web_search_base_url"] = str(data.get("ollama_web_search_base_url", "") or "").strip()
        saved_max_tokens = data.get("max_tokens")
        try:
            runtime_settings["max_tokens"] = int(saved_max_tokens) if saved_max_tokens is not None else None
        except (TypeError, ValueError):
            runtime_settings["max_tokens"] = None

    _sync_web_search_runtime_config()


def _save_runtime_settings():
    with runtime_settings_lock:
        payload = {
            "ollama_base_url": runtime_settings.get("ollama_base_url", "").strip(),
            "ollama_api_key": runtime_settings.get("ollama_api_key", "").strip(),
            "ollama_web_search_base_url": runtime_settings.get("ollama_web_search_base_url", "").strip(),
            "max_tokens": runtime_settings.get("max_tokens"),
        }

    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _effective_max_tokens() -> int:
    with runtime_settings_lock:
        saved_max_tokens = runtime_settings.get("max_tokens")
    if isinstance(saved_max_tokens, int) and saved_max_tokens > 0:
        return saved_max_tokens
    return int(os.getenv("MAX_TOKENS", "1024"))


def _sync_web_search_runtime_config():
    with runtime_settings_lock:
        api_key = runtime_settings.get("ollama_api_key", "").strip()
        base_url = runtime_settings.get("ollama_web_search_base_url", "").strip()
    configure_ollama_web_search(api_key=api_key, base_url=base_url)


def _web_search_api_key_source() -> str:
    with runtime_settings_lock:
        ui_key = runtime_settings.get("ollama_api_key", "").strip()
    if ui_key:
        return "ui"
    if os.getenv("OLLAMA_API_KEY", "").strip():
        return "env"
    return ""


def _web_search_base_url_source() -> str:
    with runtime_settings_lock:
        ui_url = runtime_settings.get("ollama_web_search_base_url", "").strip()
    if ui_url:
        return "ui"
    if os.getenv("OLLAMA_WEB_SEARCH_BASE_URL", "").strip():
        return "env"
    return "default"


def _effective_local_base_url() -> str:
    with runtime_settings_lock:
        ui_url = runtime_settings.get("ollama_base_url", "").strip()
    env_url = os.getenv("OLLAMA_BASE_URL", "").strip()
    if ui_url:
        return ui_url
    if env_url:
        return env_url
    if Path("/.dockerenv").exists():
        return "http://host.docker.internal:11434"
    return "http://127.0.0.1:11434"


def _local_base_url_source() -> str:
    with runtime_settings_lock:
        ui_url = runtime_settings.get("ollama_base_url", "").strip()
    if ui_url:
        return "ui"
    if os.getenv("OLLAMA_BASE_URL", "").strip():
        return "env"
    if Path("/.dockerenv").exists():
        return "docker-default"
    return "default"


def _get_model_operation() -> dict:
    with model_operation_lock:
        return dict(model_operation)


def _update_model_operation(**updates):
    with model_operation_lock:
        model_operation.update(updates)
        model_operation["updated_at"] = _now_iso()


def _reset_model_operation():
    with model_operation_lock:
        model_operation.update({
            "state": "idle",
            "provider": "",
            "model": "",
            "status": "",
            "error": "",
            "progress": None,
            "started_at": "",
            "updated_at": _now_iso(),
        })


@asynccontextmanager
async def lifespan(app: FastAPI):
    global professor
    _load_runtime_settings()
    n = mode_loader.discover()
    logger.info("%d teaching mode(s) available: %s",
                n, ", ".join(mode_loader.available_modes))
    if not mode_loader.is_valid_mode(admin_config["mode"]):
        if mode_loader.available_modes:
            admin_config["mode"] = mode_loader.available_modes[0]
    admin_config["maxTokens"] = _effective_max_tokens()
    # Model is loaded later via the admin panel.
    professor = ProfessorTux(mode_loader)
    professor.configure_backend(base_url=_effective_local_base_url())
    professor.configure_generation(max_tokens=_effective_max_tokens())
    if professor.active_model:
        logger.info(
            "Professor Tux ready — default Ollama model target is %s.",
            professor.active_model,
        )
    else:
        logger.info("Professor Tux ready — no model target configured. Select one from the admin panel.")
    knowledge_base.initialize()
    chat_logger.initialize()
    yield
    del professor
    professor = None


app = FastAPI(
    title="Professor Tux",
    description="Cybersecurity teaching assistant with pluggable teaching modes and RAG.",
    version="3.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)



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



@app.get("/", include_in_schema=False)
async def student_page():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/docs", include_in_schema=False)
async def docs_page():
    return FileResponse(STATIC_DIR / "docs.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")



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
    try:
        max_tokens = int(body.get("maxTokens", admin_config["maxTokens"]))
    except (TypeError, ValueError):
        raise HTTPException(400, "maxTokens must be an integer")
    if max_tokens < 1 or max_tokens > 32768:
        raise HTTPException(400, "maxTokens must be between 1 and 32768")
    admin_config.update({
        "mode": new_mode,
        "topic": body.get("topic", admin_config["topic"]),
        "courseFilter": body.get("courseFilter", admin_config["courseFilter"]),
        "useLectures": body.get("useLectures", admin_config["useLectures"]),
        "maxTokens": max_tokens,
    })
    with runtime_settings_lock:
        runtime_settings["max_tokens"] = max_tokens
    _save_runtime_settings()
    if professor:
        professor.configure_generation(max_tokens=max_tokens)
    return admin_config


@app.get("/admin/config/public", tags=["Admin"])
async def get_public_config():
    """Student page reads this to auto-configure sessions."""
    return admin_config



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



@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    kb_stats = knowledge_base.get_stats() if knowledge_base.is_loaded else {}
    model_loaded = professor.is_loaded if professor else False
    operation = _get_model_operation()
    status = "online" if model_loaded else ("no_model" if professor else "loading")
    if operation.get("state") == "downloading":
        status = "downloading_model"
    return HealthResponse(
        status=status,
        model_loaded=model_loaded,
        knowledge_base_loaded=knowledge_base.is_loaded,
        total_lecture_chunks=kb_stats.get("total_chunks", 0),
        available_modes=mode_loader.available_modes,
        status_detail=operation.get("status", ""),
    )



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



def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _normalize_model_name(model: str) -> str:
    normalized = model.strip()
    lowered = normalized.lower()
    for prefix in ("ollama:", "cloud:"):
        if lowered.startswith(prefix):
            return normalized[len(prefix):].strip()
    return normalized


def _empty_response_fallback() -> str:
    return "⚠️ I couldn't finish that answer. Please ask again."


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _start_local_model_pull(model: str):
    backend = professor.get_backend("ollama") if professor else None
    if not isinstance(backend, OllamaBackend):
        _update_model_operation(
            state="error",
            provider="ollama",
            model=model,
            status="Local Ollama backend is not available",
            error="Local Ollama backend is not available",
            progress=None,
        )
        return

    def _progress(data: dict):
        completed = data.get("completed")
        total = data.get("total")
        progress = None
        if isinstance(completed, int) and isinstance(total, int) and total > 0:
            progress = round((completed / total) * 100, 1)
        _update_model_operation(
            state="downloading",
            provider="ollama",
            model=model,
            status=data.get("status", "Downloading model…"),
            error="",
            progress=progress,
        )

    def _worker():
        try:
            _update_model_operation(
                state="downloading",
                provider="ollama",
                model=model,
                status="Starting download…",
                error="",
                progress=0.0,
                started_at=_now_iso(),
            )
            backend.pull_model(model, progress_callback=_progress)
            professor.switch_model("ollama", model)
            _update_model_operation(
                state="completed",
                provider="ollama",
                model=model,
                status="Model ready",
                error="",
                progress=100.0,
            )
            time.sleep(1.5)
            _reset_model_operation()
        except Exception as exc:
            logger.error("Local model pull failed: %s", exc, exc_info=True)
            _update_model_operation(
                state="error",
                provider="ollama",
                model=model,
                status=f"Download failed: {exc}",
                error=str(exc),
                progress=None,
            )

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def _lecture_search_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "search_lectures",
            "description": (
                "Search the student's uploaded lecture slides and notes. "
                "Call this FIRST for any question that could touch course material "
                "(concepts, names, definitions, examples, people, projects). "
                "The uploaded lectures are the course of record — prefer their "
                "content over your training knowledge. Only skip for pure "
                "greetings or small talk."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Focused search query for the lecture material.",
                    },
                },
            },
        },
    }


def _lecture_tool_hint() -> str:
    if not knowledge_base.is_loaded:
        return ""
    docs = knowledge_base.list_documents()
    if not docs:
        return ""
    lines = []
    for d in docs[:20]:
        label = d.get("lecture_title") or d.get("filename") or "document"
        course = d.get("course")
        lines.append(f"- {label}" + (f" ({course})" if course else ""))
    names = "\n".join(lines)
    return (
        "Uploaded lecture material available via the `search_lectures` tool:\n"
        f"{names}\n"
        "Call `search_lectures` first for any content question — these lectures "
        "are the student's course of record and take precedence over your "
        "training knowledge."
    )


def _lecture_tools_for_session(session: dict) -> list[dict]:
    if not session.get("use_lectures", True):
        return []
    if not knowledge_base.is_loaded:
        return []
    stats = knowledge_base.get_stats()
    if stats.get("total_documents", 0) <= 0:
        return []
    return [_lecture_search_tool_schema()]


def _run_lecture_search(query: str, session: dict) -> tuple[str, list[str]]:
    search_query = query.strip()
    if session.get("topic"):
        search_query = f"{session['topic']}: {search_query}"

    contexts = knowledge_base.search(
        query=search_query,
        top_k=3,
        course_filter=session.get("course_filter"),
    )
    relevant = [c for c in contexts if c.relevance_score >= 0.3]
    sources_used = list(dict.fromkeys(
        f"{c.source_filename} (slide {c.page_or_slide})"
        for c in relevant
    ))
    payload = {
        "query": query,
        "results": [
            {
                "source": c.source_filename,
                "slide": c.page_or_slide,
                "lecture_title": c.lecture_title,
                "course": c.course,
                "relevance": c.relevance_score,
                "excerpt": c.text[:400],
            }
            for c in relevant
        ],
        "message": "No relevant lecture material found." if not relevant else "",
    }
    return json.dumps(payload, ensure_ascii=False), sources_used


def _web_search_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Live web search. Use this for ANY question whose answer depends on current "
                "or post-training information — news, today's date or events, recent releases, "
                "CVEs, writeups, payloads, tool docs, leaderboards, prices. "
                "You HAVE real-time web access via this tool; do NOT claim otherwise. "
                "If unsure whether your training data is current enough, call this tool first."
            ),
            "parameters": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "Focused search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "How many results to return (1-10, default 5).",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
            },
        },
    }


def _ctf_agent_command_tool_schema() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "ctf_agent_command",
            "description": (
                "Build a shell command the student can run with their local CTF-Agent "
                "(github.com/hvbhanot/CTF-Agent) to autonomously attempt a CTF challenge. "
                "Call this whenever the student has a concrete challenge they want to hand to the agent."
            ),
            "parameters": {
                "type": "object",
                "required": ["name", "category", "desc"],
                "properties": {
                    "name": {"type": "string", "description": "Short challenge name, e.g. 'robots'."},
                    "category": {
                        "type": "string",
                        "description": "CTF category.",
                        "enum": ["web", "crypto", "pwn", "forensics", "misc", "rev"],
                    },
                    "desc": {"type": "string", "description": "One-sentence description of the objective."},
                    "url": {"type": "string", "description": "Target URL for web/network challenges. Optional."},
                    "model": {
                        "type": "string",
                        "description": "Ollama model the agent should use.",
                        "default": "qwen2.5:7b",
                    },
                    "verbose": {"type": "boolean", "description": "Enable verbose logging.", "default": False},
                },
            },
        },
    }


def _run_web_search(query: str, max_results: int = 5) -> tuple[str, list[str]]:
    base_url = ollama_web_search_base_url()
    try:
        results = ollama_web_search(query, max_results=max_results)
    except WebSearchConfigurationError as exc:
        logger.warning("Web search is not configured: %s", exc)
        return json.dumps({
            "query": query,
            "results": [],
            "message": "Web search is not configured. Save an Ollama API key in the admin page or set OLLAMA_API_KEY.",
        }, ensure_ascii=False), []
    except _requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (401, 403):
            logger.warning("Web search auth failed via %s: %s", base_url, exc)
            return json.dumps({
                "query": query,
                "results": [],
                "message": "Web search is not authorized. Check the saved web search key or OLLAMA_API_KEY.",
            }, ensure_ascii=False), []
        if status == 404:
            logger.warning("Web search endpoint missing on %s: %s", base_url, exc)
            return json.dumps({
                "query": query,
                "results": [],
                "message": "The configured Ollama web-search endpoint was not found. Remove OLLAMA_WEB_SEARCH_BASE_URL or set it to https://ollama.com.",
            }, ensure_ascii=False), []
        logger.warning("Web search HTTP error: %s", exc)
        return json.dumps({
            "query": query,
            "results": [],
            "message": "Web search request failed. Try again or rephrase the query.",
        }, ensure_ascii=False), []
    except _requests.RequestException as exc:
        logger.warning("Web search transport error: %s", exc)
        return json.dumps({
            "query": query,
            "results": [],
            "message": "Web search request failed. Try again or rephrase the query.",
        }, ensure_ascii=False), []

    compact = [
        {"title": r["title"], "url": r["url"], "content": r["content"][:600]}
        for r in results[:10]
    ]
    sources = [f"{r['title']} — {r['url']}" for r in compact if r.get("url")]
    return json.dumps({"query": query, "results": compact}, ensure_ascii=False), sources


def _run_ctf_agent_command(args: dict) -> tuple[str, list[str]]:
    name = (args.get("name") or "").strip()
    category = (args.get("category") or "").strip().lower()
    desc = (args.get("desc") or "").strip()
    url = (args.get("url") or "").strip()
    model = (args.get("model") or "qwen2.5:7b").strip()
    verbose = bool(args.get("verbose", False))

    if not name or not category or not desc:
        return json.dumps({"message": "Missing required field: name, category, and desc are required."}, ensure_ascii=False), []

    parts = ["python", "-m", "ctf_agent", "--model", shlex.quote(model)]
    if verbose:
        parts.append("--verbose")
    parts += [
        "solve",
        "--name", shlex.quote(name),
        "--category", shlex.quote(category),
        "--desc", shlex.quote(desc),
    ]
    if url:
        parts += ["--url", shlex.quote(url)]

    command = " ".join(parts)
    payload = {
        "command": command,
        "note": "Run this from your local CTF-Agent checkout. If Ollama runs on a different host, pass --ollama-url accordingly.",
    }
    return json.dumps(payload, ensure_ascii=False), []


def _handle_tool_call(call: dict, session: dict) -> tuple[Optional[dict], list[str]]:
    function = call.get("function") or {}
    name = function.get("name")
    arguments = function.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}

    if name == "search_lectures":
        query = (arguments.get("query") or "").strip()
        if not query:
            return {
                "role": "tool",
                "tool_name": "search_lectures",
                "content": json.dumps({"message": "Missing required argument: query"}, ensure_ascii=False),
            }, []
        content, sources_used = _run_lecture_search(query, session)
        return {"role": "tool", "tool_name": "search_lectures", "content": content}, sources_used

    if name == "web_search":
        query = (arguments.get("query") or "").strip()
        if not query:
            return {
                "role": "tool",
                "tool_name": "web_search",
                "content": json.dumps({"message": "Missing required argument: query"}, ensure_ascii=False),
            }, []
        max_results = arguments.get("max_results")
        if not isinstance(max_results, int) or not (1 <= max_results <= 10):
            max_results = 5
        content, sources_used = _run_web_search(query, max_results=max_results)
        return {"role": "tool", "tool_name": "web_search", "content": content}, sources_used

    if name == "ctf_agent_command":
        content, sources_used = _run_ctf_agent_command(arguments)
        return {"role": "tool", "tool_name": "ctf_agent_command", "content": content}, sources_used

    return {
        "role": "tool",
        "tool_name": name or "unknown",
        "content": json.dumps({"message": "Unknown tool"}, ensure_ascii=False),
    }, []


def _is_recall_like_mode(mode_id: str) -> bool:
    normalized = (mode_id or "").strip().lower()
    return normalized == "recall" or normalized.startswith("recall_")


def _is_wrong_mode(mode_id: str) -> bool:
    normalized = (mode_id or "").strip().lower()
    return normalized.endswith("_wrong")


def _is_ctf_mode(mode_id: str) -> bool:
    return (mode_id or "").strip().lower() == "ctf"


def _should_apply_wrongness(mode_id: str) -> bool:
    return _is_wrong_mode(mode_id) and random.random() < WRONG_MODE_ERROR_RATE


def _mode_uses_lecture_support(mode_id: str, apply_wrongness: bool) -> bool:
    # Recall-like modes stay minimal — no lecture tool, no citations.
    # CTF mode uses web + agent tools instead of lectures.
    # Wrong turns stay ungrounded so the model can drift slightly off course.
    if _is_recall_like_mode(mode_id):
        return False
    if _is_ctf_mode(mode_id):
        return False
    if apply_wrongness:
        return False
    return True


def _tools_for_mode(session: dict, mode_id: str, apply_wrongness: bool) -> list[dict]:
    if _is_ctf_mode(mode_id):
        tools = [_ctf_agent_command_tool_schema()]
        if ollama_web_search_configured():
            tools.insert(0, _web_search_tool_schema())
        return tools
    if _mode_uses_lecture_support(mode_id, apply_wrongness):
        return _lecture_tools_for_session(session)
    return []


def _tool_hint_for_mode(mode_id: str, tools: list[dict]) -> str:
    if not tools:
        return ""
    if _is_ctf_mode(mode_id):
        names = ", ".join(t["function"]["name"] for t in tools)
        if any(t["function"]["name"] == "web_search" for t in tools):
            return (
                f"CTF tools available this session: {names}.\n"
                "You have live web access via web_search. Do NOT claim you cannot fetch "
                "real-time information or cite a training cutoff. For any question about "
                "current events, news, dates, recent releases, CVEs, writeups, or tool "
                "docs, CALL web_search first. "
                "Call ctf_agent_command whenever the student wants a ready-to-run CTF-Agent command."
            )
        return (
            f"CTF tools available this session: {names}.\n"
            "Live web search is not configured for this server, so do NOT claim you searched "
            "the web or have real-time information. If current CVE details, writeups, or tool "
            "docs are required, tell the student that an admin must configure an Ollama API key first. "
            "Call ctf_agent_command whenever the student wants a ready-to-run CTF-Agent command."
        )
    # Non-CTF path uses the lecture hint.
    return _lecture_tool_hint()


def _generate_response_with_tools(
    *,
    student_message: str,
    active_mode: str,
    session: dict,
    apply_wrongness: bool,
) -> tuple[str, list[str], str]:
    tools = _tools_for_mode(session, active_mode, apply_wrongness)
    tool_hint = _tool_hint_for_mode(active_mode, tools)
    messages = professor.build_messages(
        student_message=student_message,
        mode_id=active_mode,
        topic=session["topic"],
        history=session["history"],
        lecture_context="",
        apply_wrongness=apply_wrongness,
        lecture_tool_hint=tool_hint,
    )
    system_prompt = messages[0]["content"] if messages else ""
    sources_used: list[str] = []
    last_content = ""

    if not tools:
        response_text = professor.generate(
            student_message=student_message,
            mode_id=active_mode,
            topic=session["topic"],
            history=session["history"],
            lecture_context="",
            apply_wrongness=apply_wrongness,
        )
        if response_text.strip():
            return response_text, list(dict.fromkeys(sources_used)), system_prompt
        return "⚠️ I couldn't finish that answer. Please ask again.", sources_used, system_prompt

    for _ in range(3):
        assistant_message = professor.chat_once(
            messages=messages,
            tools=tools,
            mode_id=active_mode,
            apply_wrongness=apply_wrongness,
        )
        messages.append(assistant_message)
        last_content = (assistant_message.get("content") or "").strip()
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            if last_content:
                return last_content, sources_used, system_prompt
            return "⚠️ I couldn't finish that answer. Please ask again.", sources_used, system_prompt

        executed_any = False
        for call in tool_calls:
            tool_message, tool_sources = _handle_tool_call(call, session)
            if tool_message:
                messages.append(tool_message)
                sources_used.extend(tool_sources)
                executed_any = True
        if not executed_any:
            break

    return last_content or "⚠️ I had trouble pulling up the lecture material. Please try again.", list(dict.fromkeys(sources_used)), system_prompt


@app.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(req: ChatRequest, request: Request):
    if not professor or not professor.is_loaded:
        raise HTTPException(503, "No active model backend is available")

    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    active_mode = req.mode_override or session["mode"]
    if req.mode_override:
        if not mode_loader.is_valid_mode(req.mode_override):
            raise HTTPException(400, f"Unknown mode: {req.mode_override}")
        sessions.update_mode(req.session_id, req.mode_override)

    is_social = professor.is_social_message(req.message)
    apply_wrongness = _should_apply_wrongness(active_mode) if not is_social else False
    sources_used: list[str] = []
    system_prompt = ""

    t0 = time.perf_counter()
    if is_social:
        response_text = professor.generate(
            student_message=req.message,
            mode_id=active_mode,
            topic=session["topic"],
            history=session["history"],
            lecture_context="",
            apply_wrongness=apply_wrongness,
        )
    else:
        response_text, sources_used, system_prompt = _generate_response_with_tools(
            student_message=req.message,
            active_mode=active_mode,
            session=session,
            apply_wrongness=apply_wrongness,
        )
    duration_ms = int((time.perf_counter() - t0) * 1000)

    sessions.add_message(req.session_id, role="student", content=req.message)
    sessions.add_message(req.session_id, role="professor_tux", content=response_text)

    chat_logger.log(ChatLogEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        ip=_get_client_ip(request),
        session_id=req.session_id,
        mode=active_mode,
        topic=session.get("topic"),
        question=req.message,
        system_prompt=system_prompt,
        response=response_text,
        sources_used=sources_used,
        duration_ms=duration_ms,
        model=professor.active_model,
    ))

    return ChatResponse(
        session_id=req.session_id,
        mode=active_mode,
        response=response_text,
        hint=None if is_social else mode_loader.get_hint(active_mode),
        sources_used=sources_used,
    )


@app.post("/chat/stream", tags=["Chat"])
async def chat_stream(req: ChatRequest, request: Request):
    """SSE streaming endpoint backed by Ollama /api/chat streaming."""
    if not professor or not professor.is_loaded:
        raise HTTPException(503, "No active model backend is available")

    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    active_mode = req.mode_override or session["mode"]
    if req.mode_override:
        if not mode_loader.is_valid_mode(req.mode_override):
            raise HTTPException(400, f"Unknown mode: {req.mode_override}")
        sessions.update_mode(req.session_id, req.mode_override)

    is_social = professor.is_social_message(req.message)
    apply_wrongness = _should_apply_wrongness(active_mode) if not is_social else False
    client_ip = _get_client_ip(request)

    def _event_stream():
        t0 = time.perf_counter()
        sources_used: list[str] = []
        system_prompt = ""
        response_parts: list[str] = []

        try:
            if is_social:
                for token in professor.generate_stream(
                    student_message=req.message,
                    mode_id=active_mode,
                    topic=session["topic"],
                    history=session["history"],
                    lecture_context="",
                    apply_wrongness=apply_wrongness,
                ):
                    if not token:
                        continue
                    response_parts.append(token)
                    yield _sse({"token": token})
            else:
                tools = _tools_for_mode(session, active_mode, apply_wrongness)
                if not tools:
                    messages = professor.build_messages(
                        student_message=req.message,
                        mode_id=active_mode,
                        topic=session["topic"],
                        history=session["history"],
                        lecture_context="",
                        apply_wrongness=apply_wrongness,
                    )
                    system_prompt = messages[0]["content"] if messages else ""
                    for token in professor.generate_stream(
                        student_message=req.message,
                        mode_id=active_mode,
                        topic=session["topic"],
                        history=session["history"],
                        lecture_context="",
                        apply_wrongness=apply_wrongness,
                    ):
                        if not token:
                            continue
                        response_parts.append(token)
                        yield _sse({"token": token})
                else:
                    tool_hint = _tool_hint_for_mode(active_mode, tools)
                    messages = professor.build_messages(
                        student_message=req.message,
                        mode_id=active_mode,
                        topic=session["topic"],
                        history=session["history"],
                        lecture_context="",
                        apply_wrongness=apply_wrongness,
                        lecture_tool_hint=tool_hint,
                    )
                    system_prompt = messages[0]["content"] if messages else ""

                    for _ in range(3):
                        turn_parts: list[str] = []
                        assistant_role = "assistant"
                        tool_calls: list[dict] = []

                        for chunk in professor.chat_stream_once(
                            messages=messages,
                            tools=tools,
                            mode_id=active_mode,
                            apply_wrongness=apply_wrongness,
                        ):
                            token = chunk.get("content") or ""
                            if token:
                                turn_parts.append(token)
                                yield _sse({"token": token})
                            assistant_role = chunk.get("role", assistant_role)
                            if chunk.get("tool_calls"):
                                tool_calls = chunk["tool_calls"]

                        assistant_content = "".join(turn_parts)
                        if turn_parts:
                            response_parts.extend(turn_parts)
                        assistant_message = {
                            "role": assistant_role,
                            "content": assistant_content,
                        }
                        if tool_calls:
                            assistant_message["tool_calls"] = tool_calls
                        messages.append(assistant_message)

                        if not tool_calls:
                            break

                        executed_any = False
                        for call in tool_calls:
                            tool_message, tool_sources = _handle_tool_call(call, session)
                            if not tool_message:
                                continue
                            messages.append(tool_message)
                            sources_used.extend(tool_sources)
                            executed_any = True
                        if not executed_any:
                            break
                    else:
                        if not response_parts:
                            fallback = "⚠️ I had trouble pulling up the lecture material. Please try again."
                            response_parts.append(fallback)
                            yield _sse({"token": fallback})
        except BackendError as exc:
            logger.error("Streaming chat failed: %s", exc)
            error_text = "⚠️ The teaching engine hit an error. Please try again."
            yield _sse({"error": error_text})
            yield _sse({"done": True, "mode": active_mode, "hint": None if is_social else mode_loader.get_hint(active_mode), "sources_used": list(dict.fromkeys(sources_used))})
            return

        response_text = "".join(response_parts).strip()
        if not response_text:
            response_text = _empty_response_fallback()
            yield _sse({"token": response_text})

        sources_used = list(dict.fromkeys(sources_used))
        duration_ms = int((time.perf_counter() - t0) * 1000)
        sessions.add_message(req.session_id, role="student", content=req.message)
        sessions.add_message(req.session_id, role="professor_tux", content=response_text)

        chat_logger.log(ChatLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            ip=client_ip,
            session_id=req.session_id,
            mode=active_mode,
            topic=session.get("topic"),
            question=req.message,
            system_prompt=system_prompt,
            response=response_text,
            sources_used=sources_used,
            duration_ms=duration_ms,
            model=professor.active_model,
        ))

        yield _sse({
            "done": True,
            "mode": active_mode,
            "hint": None if is_social else mode_loader.get_hint(active_mode),
            "sources_used": sources_used,
        })

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/models", tags=["Models"])
async def list_models(token: str = Depends(verify_admin)):
    """List model targets visible from the configured Ollama endpoint."""
    return {"models": professor.list_available_models() if professor else []}


@app.get("/admin/models/status", tags=["Admin"])
async def get_model_status(token: str = Depends(verify_admin)):
    active_model = professor.active_model if professor else ""
    model_loaded = professor.is_loaded if professor else False
    tool_support: Optional[bool] = None
    if professor and active_model and model_loaded:
        tool_support = professor.probe_tool_support(active_model)
    return {
        "operation": _get_model_operation(),
        "active_model": active_model,
        "model_loaded": model_loaded,
        "base_url": _effective_local_base_url(),
        "base_url_source": _local_base_url_source(),
        "tool_support": tool_support,
        "web_search_configured": ollama_web_search_configured(),
        "web_search_base_url": ollama_web_search_base_url(),
        "web_search_base_url_source": _web_search_base_url_source(),
        "web_search_api_key_source": _web_search_api_key_source(),
    }


@app.put("/admin/web-search", tags=["Admin"])
async def update_web_search_config(request: Request, token: str = Depends(verify_admin)):
    body = await request.json()
    api_key = str(body.get("api_key", "") or "").strip()
    base_url = str(body.get("base_url", "") or "").strip()
    clear_api_key = bool(body.get("clear_api_key", False))

    if base_url and not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Web search API URL must start with http:// or https://")

    with runtime_settings_lock:
        if clear_api_key:
            runtime_settings["ollama_api_key"] = ""
        elif api_key:
            runtime_settings["ollama_api_key"] = api_key
        runtime_settings["ollama_web_search_base_url"] = base_url
    _save_runtime_settings()
    _sync_web_search_runtime_config()

    api_key_source = _web_search_api_key_source()
    if clear_api_key and api_key_source == "env":
        message = "Saved web search API key cleared; environment OLLAMA_API_KEY is still active"
    elif ollama_web_search_configured():
        message = "Web search settings saved"
    else:
        message = "Web search API key cleared"

    return {
        "web_search_configured": ollama_web_search_configured(),
        "web_search_base_url": ollama_web_search_base_url(),
        "web_search_base_url_source": _web_search_base_url_source(),
        "web_search_api_key_source": api_key_source,
        "message": message,
    }


@app.put("/admin/models/connection", tags=["Admin"])
async def update_model_connection(request: Request, token: str = Depends(verify_admin)):
    body = await request.json()
    if "base_url" not in body:
        raise HTTPException(status_code=400, detail="base_url is required")
    base_url = str(body.get("base_url", "") or "").strip()

    with runtime_settings_lock:
        runtime_settings["ollama_base_url"] = base_url
    _save_runtime_settings()

    professor.configure_backend(base_url=_effective_local_base_url())

    return {
        "base_url": _effective_local_base_url(),
        "base_url_source": _local_base_url_source(),
        "message": "Ollama URL updated" if base_url else "Ollama URL reset",
    }


@app.post("/admin/models/switch", tags=["Admin"])
async def switch_model(request: Request, token: str = Depends(verify_admin)):
    """Switch to a model on the configured Ollama endpoint."""
    body = await request.json()
    selection = (body.get("selection") or "").strip()
    model = _normalize_model_name((body.get("model") or "").strip())
    if selection and not model:
        _, separator, parsed_model = selection.partition("::")
        if separator:
            model = _normalize_model_name(parsed_model.strip())
    if not model:
        raise HTTPException(400, "Model name is required")
    operation = _get_model_operation()
    if operation.get("state") == "downloading":
        raise HTTPException(409, f"Another model is downloading: {operation.get('model')}")
    try:
        backend = professor.get_backend("ollama") if professor else None
        if not isinstance(backend, OllamaBackend):
            raise HTTPException(500, "Ollama backend is not available")

        should_auto_pull = backend.is_local_endpoint()

        if should_auto_pull and backend.has_model(model):
            professor.switch_model("ollama", model)
            _reset_model_operation()
            return {
                "active_model": professor.active_model,
                "message": f"Switched to {professor.active_model}",
            }

        if should_auto_pull:
            _start_local_model_pull(model)
            return {
                "accepted": True,
                "state": "downloading",
                "provider": "ollama",
                "model": model,
                "message": f"Downloading {model}",
            }

        professor.switch_model("ollama", model)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except BackendError as e:
        logger.error("Model switch failed: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("Model switch failed: %s", e, exc_info=True)
        raise HTTPException(500, f"Failed to load model: {e}")
    _reset_model_operation()
    return {
        "active_model": professor.active_model,
        "message": f"Switched to {professor.active_model}",
    }



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
        message=f"{doc.filename}: {doc.num_pages} pages → {doc.num_chunks} chunks",
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



@app.get("/admin/logs", tags=["Admin"])
async def get_chat_logs(
    token: str = Depends(verify_admin),
    limit: int = 100,
    offset: int = 0,
    session_id: Optional[str] = None,
    ip: Optional[str] = None,
):
    """Retrieve chat logs with optional filters."""
    return chat_logger.get_logs(
        limit=limit, offset=offset,
        session_filter=session_id, ip_filter=ip,
    )


@app.delete("/admin/logs", tags=["Admin"])
async def clear_chat_logs(token: str = Depends(verify_admin)):
    """Clear all chat logs."""
    count = chat_logger.clear()
    return {"cleared": count, "message": f"Deleted {count} log entries"}


@app.get("/admin/logs/download", tags=["Admin"])
async def download_chat_logs(token: str = Depends(verify_admin)):
    """Download the raw chat logs JSONL file."""
    log_path = LOG_FILE_DIR / "chat_logs.jsonl"
    if not log_path.exists() or log_path.stat().st_size == 0:
        raise HTTPException(404, "No chat logs to download")
    return FileResponse(
        str(log_path), media_type="application/jsonl",
        filename="chat_logs.jsonl",
    )


@app.get("/admin/logs/download/server", tags=["Admin"])
async def download_server_log(token: str = Depends(verify_admin)):
    """Download the server log file."""
    log_path = LOG_FILE_DIR / "professor_tux.log"
    if not log_path.exists() or log_path.stat().st_size == 0:
        raise HTTPException(404, "No server logs to download")
    return FileResponse(
        str(log_path), media_type="text/plain",
        filename="professor_tux.log",
    )



def _welcome_message(mode_def, topic: str | None, use_lectures: bool) -> str:
    topic_str = f" on **{topic}**" if topic else ""
    lec_str = ("\nI have access to your lecture slides and will reference them."
               if use_lectures else "")
    student_mode_def = mode_def
    if mode_def and _is_wrong_mode(mode_def.id):
        family_id = "guided" if mode_def.id.startswith("guided") else "recall"
        student_mode_def = mode_loader.get_mode(family_id) or mode_def

    name = student_mode_def.name if student_mode_def else "Unknown Mode"
    desc = student_mode_def.description if student_mode_def else ""

    return (
        f"Welcome, student! I'm Professor Tux.\n\n"
        f"We're in **{name}**{topic_str}.\n"
        f"{desc}\n"
        f"What would you like to explore?{lec_str}"
    )
