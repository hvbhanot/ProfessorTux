# 🐧 Professor Tux — Cybersecurity Teaching Assistant

AI-powered cybersecurity teaching assistant with **pluggable teaching modes**, **lecture slide RAG**, and a split **student/admin** web interface.

## Architecture

```
professor_tux/
├── app/
│   ├── main.py              # FastAPI routes, admin auth, all endpoints
│   ├── professor.py          # LLM wrapper (llama-cpp-python)
│   ├── mode_loader.py        # Auto-discovers teaching modes from .md files
│   ├── models.py             # Pydantic request/response schemas
│   ├── sessions.py           # In-memory session manager
│   ├── rag.py                # RAG pipeline (extract → chunk → embed → retrieve)
│   ├── modes/                # ← TEACHING MODES (skill files)
│   │   ├── README.md         # How to create new modes
│   │   ├── recall.md         # 🧠 Socratic recall mode
│   │   └── guided.md         # 📖 Guided learning mode
│   └── static/
│       ├── index.html        # Student chat interface
│       ├── admin.html        # Admin panel (login-protected)
│       └── logo.png          # Professor Tux logo
├── run.py                    # Entry point
├── client.py                 # CLI test client
├── requirements.txt
├── Dockerfile
└── .env.example
```

## Quick Start

```bash
# 1. Clone & install
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# Edit .env → set MODEL_PATH to your .gguf file

# 3. Run
python run.py
```

- **Student chat**: http://localhost:8000
- **Admin panel**: http://localhost:8000/admin (default: `admin` / `professortux`)
- **API docs**: http://localhost:8000/docs

## Pluggable Teaching Modes

Modes are defined as `.md` files in `app/modes/`. Each file uses a **frontmatter + body** structure (inspired by Anthropic's SKILL.md pattern). They are auto-discovered at startup.

### Creating a New Mode

Create `app/modes/challenge.md`:

```markdown
---
id: challenge
name: CTF Challenge
icon: 🏁
color: "#ff6b6b"
description: Capture-the-flag style puzzles and challenges.
hint_message: 🏁 Think like a hacker!
---

You are in **CTF Challenge Mode**. Present the student with
capture-the-flag style cybersecurity challenges.

## Rules
1. Present a scenario or puzzle
2. Give encoded clues the student must decode
3. Validate their answers step by step
4. Award "flags" for correct solutions
```

That's it — restart the server (or hit `POST /modes/reload` from admin) and the new mode appears in both the admin panel and API.

### Mode File Format

| Field | Required | Description |
|-------|----------|-------------|
| `id` | ✅ | Unique identifier (used in API) |
| `name` | ✅ | Display name |
| `icon` | | Emoji icon |
| `color` | | Hex color for UI badges/cards |
| `description` | | Short description for admin panel |
| `hint_message` | | Shown after each response (empty = none) |
| **Body** | ✅ | Full system prompt injected into the LLM |

### Built-in Modes

| Mode | Description |
|------|-------------|
| 🧠 **recall** | Socratic method — hints and questions, student must retrieve answers |
| 📖 **guided** | Full explanations with examples and comprehension checks |

### Mode Ideas

- `challenge.md` — CTF puzzles
- `exam_prep.md` — Practice exam questions with grading
- `lab.md` — Hands-on tool walkthroughs (nmap, Wireshark, etc.)
- `debate.md` — Security tradeoff debates
- `incident_response.md` — IR scenario simulations
- `red_team.md` — Offensive mindset training
- `blue_team.md` — Defensive analysis focus

## API Endpoints

### System
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Server status, loaded modes, chunk count |

### Modes
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/modes` | List all available teaching modes |
| `POST` | `/modes/reload` | Hot-reload modes from disk (admin auth) |

### Sessions
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create a session (specify mode, topic, etc.) |
| `GET` | `/sessions/{id}` | Get session history |
| `PATCH` | `/sessions/{id}/mode?mode=X` | Switch mode mid-session |

### Chat
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | Send a message, get a response |

### Lectures (RAG)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/lectures/upload` | Upload a PDF/PPTX/TXT/MD |
| `GET` | `/lectures` | List all uploaded documents |
| `DELETE` | `/lectures/{doc_id}` | Delete a document |
| `POST` | `/lectures/search` | Semantic search across slides |
| `GET` | `/lectures/stats/overview` | RAG pipeline stats |

### Admin
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/login` | Authenticate |
| `GET` | `/admin/verify` | Verify token |
| `GET` | `/admin/config` | Get admin config (auth required) |
| `PUT` | `/admin/config` | Update config (auth required) |
| `GET` | `/admin/config/public` | Public config (student page reads this) |

## Admin Panel

The admin panel at `/admin` provides:

- **Mode selection** — dynamically rendered from discovered `.md` files
- **Hot reload** — reload modes without restarting the server
- **Session config** — set default topic, course filter, enable/disable RAG
- **Lecture management** — drag-drop upload, file table, delete
- **Stats dashboard** — server status, document count, chunk count

Changes made in admin are immediately reflected for new student sessions.

## RAG Pipeline

1. **Upload** → PDF/PPTX/TXT/MD via admin panel or API
2. **Extract** → PyMuPDF (PDF), python-pptx (PPTX incl. speaker notes & tables)
3. **Chunk** → 500-char chunks with 100-char overlap, sentence-boundary aware
4. **Embed** → all-MiniLM-L6-v2 (384-dim, CPU-friendly)
5. **Store** → ChromaDB (persisted to disk)
6. **Retrieve** → Top-5 semantic search per query, injected into system prompt
7. **Cite** → Sources shown as purple tags in the chat UI

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PATH` | `./models/DASD-4B-Thinking.Q4_K_M.gguf` | Path to GGUF model |
| `N_CTX` | `4096` | Context window |
| `N_GPU_LAYERS` | `0` | GPU layers (-1 = all) |
| `MAX_TOKENS` | `1024` | Max response tokens |
| `TEMPERATURE` | `0.7` | Sampling temperature |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence transformer model |
| `CHROMA_PERSIST_DIR` | `./data/chromadb` | Vector DB storage |
| `UPLOAD_DIR` | `./data/uploads` | Uploaded files |
| `CHUNK_SIZE` | `500` | Characters per chunk |
| `CHUNK_OVERLAP` | `100` | Overlap between chunks |
| `TOP_K_RESULTS` | `5` | Chunks retrieved per query |
| `ADMIN_USERNAME` | `admin` | Admin login username |
| `ADMIN_PASSWORD` | `professortux` | Admin login password |
| `HOST` | `0.0.0.0` | Server host |
| `PORT` | `8000` | Server port |
