# 🐧 Professor Tux

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> AI-powered cybersecurity teaching assistant with **pluggable teaching modes**, **lecture slide RAG**, and a split **student/admin** web interface. The runtime uses a single **Ollama-compatible chat endpoint** with local Ollama as the default.

![Professor Tux Screenshot](https://via.placeholder.com/800x400/0a0e14/00e5ff?text=Professor+Tux+Cybersecurity+Lab)

## ✨ Features

- 🧠 **Pluggable Teaching Modes** — Create custom teaching styles via markdown files
- 📚 **Lecture RAG Pipeline** — Upload PDFs/PPTX and ground answers in course materials
- 🛠️ **Lecture-Grounded Guided Mode** — Guided Learning prefetches relevant uploaded lecture context and can still use lecture search tools when needed
- 🔌 **Single Ollama Backend** — Point Professor Tux at any Ollama-compatible `/api/chat` endpoint
- ⬇️ **Auto Pull Local Models** — For local Ollama endpoints, type a model name in admin and Professor Tux will pull it automatically if it is not installed yet
- 🎨 **Modern Web UI** — Terminal-themed student interface + admin panel
- 💻 **Terminal CLI Client** — Hackers-style command line interface
- 🔄 **Hot Reload** — Add new teaching modes without restarting
- 🔐 **Admin Panel** — Manage modes, uploads, and configuration

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) running locally or on a reachable host
- At least one pulled Ollama model, such as `llama3.1:8b`

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/professor-tux.git
cd professor-tux

# Install dependencies
pip install -r requirements.txt

# Start Ollama and pull a model
ollama serve
ollama pull llama3.1:8b

# Configure environment
cp .env.example .env
# Edit .env if you want a different default model or Ollama endpoint

# Run the server
python run.py
```

### Access Points

| Endpoint | URL | Description |
|----------|-----|-------------|
| Student Chat | http://localhost:8000 | Main learning interface |
| Admin Panel | http://localhost:8000/admin | Mode & lecture management |
| Product Docs | http://localhost:8000/docs | Full setup and usage guide |
| API Docs | http://localhost:8000/api/docs | Swagger/OpenAPI documentation |

**Default admin credentials:** `admin` / `professortux`

### Terminal Client

```bash
python client.py
```

A hacker-themed CLI with spinner animations, terminal prompts, and typing effects.

## 🤖 Ollama Endpoint

Professor Tux routes generation through a single **Ollama-compatible chat endpoint** instead of loading `.gguf` files directly.

### Default: Local Ollama

```bash
# .env
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1:8b
```

Recommended Ollama models:

| Model | Best For | Command |
|-------|----------|---------|
| **llama3.1:8b** | Strong general-purpose teaching | `ollama pull llama3.1:8b` |
| **qwen2.5:7b** | Fast local reasoning | `ollama pull qwen2.5:7b` |
| **mistral:7b** | Lightweight explanations | `ollama pull mistral:7b` |

### Cloud Models

To run Ollama Cloud models, sign in on the host once:

```bash
ollama signin
```

The local daemon then transparently forwards any `:*-cloud` model (e.g. `gpt-oss:120b-cloud`) to Ollama Cloud — Professor Tux keeps pointing at your normal local `OLLAMA_BASE_URL`, no API key needed. See [docs.ollama.com/cloud](https://docs.ollama.com/cloud).

## 🏗️ Architecture

```
professor-tux/
├── app/
│   ├── main.py              # FastAPI routes & endpoints
│   ├── professor.py         # Prompt builder + backend orchestration
│   ├── llm_backends.py      # Ollama-compatible backend adapter
│   ├── mode_loader.py       # Auto-discovers teaching modes
│   ├── rag.py               # RAG pipeline (ChromaDB)
│   ├── sessions.py          # Session management
│   ├── models.py            # Pydantic schemas
│   ├── modes/               # Teaching mode definitions
│   │   ├── recall.md        # 🧠 Socratic mode
│   │   └── guided.md        # 📖 Guided learning
│   └── static/              # Web UI assets
├── data/                    # ChromaDB & uploads (not in git)
├── run.py                   # Server entry point
├── client.py                # Terminal CLI client
├── requirements.txt
└── Dockerfile
```

## 🎓 Teaching Modes

Modes are markdown files in `app/modes/` with YAML frontmatter:

```markdown
---
id: recall
name: Socratic Recall
icon: 🧠
color: "#00e5ff"
description: Guide students through questions
hint_message: 💡 What do you remember?
---

You are in Socratic mode. Never give direct answers...
```

### Built-in Modes

| Mode | Icon | Description |
|------|------|-------------|
| **Recall** | 🧠 | Minimal in-exam cues and hint-only nudges |
| **Guided** | 📖 | Full explanations with examples |

### Creating Custom Modes

1. Create `app/modes/mymode.md`
2. Add frontmatter + system prompt
3. Reload via admin panel or restart server

See [`app/modes/README.md`](app/modes/README.md) for full guide.

## 📚 RAG Pipeline

Upload lecture materials via the admin panel:

1. **Upload** → PDF, PPTX, TXT, or MD files
2. **Extract** → Text + speaker notes extracted
3. **Chunk** → 500-char overlapping chunks
4. **Embed** → all-MiniLM-L6-v2 embeddings
5. **Retrieve** → Top-5 relevant chunks per query
6. **Call tool when needed** → The model can invoke lecture search only when course context is actually useful
7. **Cite** → Sources shown as purple tags

## 🔌 API Endpoints

### Chat
```bash
POST /sessions          # Create session
POST /chat              # Send message
GET  /sessions/{id}     # Get history
```

### Modes
```bash
GET  /modes             # List modes
POST /modes/reload      # Hot-reload (admin)
```

### Lectures
```bash
POST /lectures/upload   # Upload file
GET  /lectures          # List documents
POST /lectures/search   # Semantic search
```

### Admin
```bash
POST /admin/login       # Authenticate
GET  /admin/config      # Get config
PUT  /admin/config      # Update config
```

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint URL |
| `OLLAMA_MODEL` | `llama3.1:8b` | Default model target |
| `MAX_TOKENS` | `1024` | Max response tokens |
| `TEMPERATURE` | `0.7` | Sampling temperature |
| `ADMIN_USERNAME` | `admin` | Admin login |
| `ADMIN_PASSWORD` | `professortux` | Admin password |

See `.env.example` for all options.

## 🐳 Docker

```bash
docker build -t professor-tux .
docker run -p 8000:8000 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  -e OLLAMA_MODEL=llama3.1:8b \
  professor-tux
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open a Pull Request

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com) and [Ollama](https://ollama.com)
- UI inspired by terminal aesthetics and cyberpunk themes
- RAG powered by [ChromaDB](https://www.trychroma.com) and [Sentence Transformers](https://www.sbert.net)

---

<p align="center">Made with 💻 by cybersecurity educators, for cybersecurity learners</p>
