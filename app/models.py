from typing import Optional

from pydantic import BaseModel, Field

# ── Requests ─────────────────────────────────────────────────────────


class SessionCreateRequest(BaseModel):
    mode: str = Field(
        ...,
        description="Teaching mode ID (e.g., 'recall', 'guided'). See GET /modes for available modes.",
    )
    topic: Optional[str] = Field(
        None,
        description="Optional topic to focus the session",
        examples=["SQL Injection", "Buffer Overflow", "Wireshark Packet Analysis"],
    )
    course_filter: Optional[str] = Field(
        None,
        description="Only retrieve context from lectures tagged with this course",
    )
    use_lectures: bool = Field(
        True,
        description="Whether to augment responses with lecture slide content (RAG)",
    )


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Session ID from POST /sessions")
    message: str = Field(..., min_length=1, description="The student's message")
    mode_override: Optional[str] = Field(
        None,
        description="Switch mode for this message (persists for the session)",
    )


# ── Responses ────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    knowledge_base_loaded: bool = False
    total_lecture_chunks: int = 0
    available_modes: list[str] = []
    status_detail: str = ""


class SessionCreateResponse(BaseModel):
    session_id: str
    mode: str
    topic: Optional[str]
    use_lectures: bool
    course_filter: Optional[str]
    welcome_message: str


class MessageRecord(BaseModel):
    role: str
    content: str


class SessionHistoryResponse(BaseModel):
    session_id: str
    mode: str
    topic: Optional[str]
    history: list[MessageRecord]


class ChatResponse(BaseModel):
    session_id: str
    mode: str
    response: str
    hint: Optional[str] = None
    sources_used: list[str] = Field(default_factory=list)


# ── Mode schemas ─────────────────────────────────────────────────────


class ModeInfo(BaseModel):
    id: str
    name: str
    icon: str
    color: str
    description: str
    hint_message: str


class ModeListResponse(BaseModel):
    total: int
    modes: list[ModeInfo]


# ── Lecture / RAG schemas ────────────────────────────────────────────


class LectureUploadResponse(BaseModel):
    doc_id: str
    filename: str
    course: Optional[str]
    lecture_title: Optional[str]
    file_type: str
    num_pages: int
    num_chunks: int
    message: str


class LectureDocumentInfo(BaseModel):
    doc_id: str
    filename: str
    course: Optional[str]
    lecture_title: Optional[str]
    file_type: str
    num_chunks: int
    num_pages: int
    uploaded_at: str


class LectureListResponse(BaseModel):
    total: int
    documents: list[LectureDocumentInfo]


class LectureDeleteResponse(BaseModel):
    doc_id: str
    deleted: bool
    message: str


class KnowledgeBaseStatsResponse(BaseModel):
    total_documents: int
    total_chunks: int
    embedding_model: str
    chunk_size: int
    chunk_overlap: int


class LectureSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)
    course_filter: Optional[str] = None


class RetrievedChunkResponse(BaseModel):
    text: str
    source_filename: str
    lecture_title: Optional[str]
    course: Optional[str]
    page_or_slide: Optional[int]
    relevance_score: float


class LectureSearchResponse(BaseModel):
    query: str
    results: list[RetrievedChunkResponse]
