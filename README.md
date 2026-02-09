# 🐧 Professor Tux

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> AI-powered cybersecurity teaching assistant with **pluggable teaching modes**, **lecture slide RAG**, and a split **student/admin** web interface.

![Professor Tux Screenshot](https://via.placeholder.com/800x400/0a0e14/00e5ff?text=Professor+Tux+Cybersecurity+Lab)

## ✨ Features

- 🧠 **Pluggable Teaching Modes** — Create custom teaching styles via markdown files
- 📚 **Lecture RAG Pipeline** — Upload PDFs/PPTX and ground answers in course materials
- 🎨 **Modern Web UI** — Terminal-themed student interface + admin panel
- 💻 **Terminal CLI Client** — Hackers-style command line interface
- 🔄 **Hot Reload** — Add new teaching modes without restarting
- 🔐 **Admin Panel** — Manage modes, uploads, and configuration

## 🚀 Quick Start

### Prerequisites

- Python 3.10+
- A GGUF model file (e.g., `DASD-4B-Thinking.Q4_K_M.gguf` or similar)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/professor-tux.git
cd professor-tux

# Install dependencies
pip install -r requirements.txt

# Download a GGUF model and place it in the models/ directory
# Recommended: DASD-4B-Thinking (4B parameter cybersecurity model)

# Configure environment
cp .env.example .env
# Edit .env and set MODEL_PATH to your .gguf file

# Run the server
python run.py
```

### Access Points

| Endpoint | URL | Description |
|----------|-----|-------------|
| Student Chat | http://localhost:8000 | Main learning interface |
| Admin Panel | http://localhost:8000/admin | Mode & lecture management |
| API Docs | http://localhost:8000/docs | Swagger/OpenAPI documentation |

**Default admin credentials:** `admin` / `professortux`

### Terminal Client

```bash
python client.py
```

A hacker-themed CLI with spinner animations, terminal prompts, and typing effects.

## 🤖 Using Different Models

Professor Tux works with **any GGUF format model**. Simply download a `.gguf` file and update your `.env`:

```bash
# .env
MODEL_PATH=./models/llama-3.1-8b.Q4_K_M.gguf
```

### Recommended Models

| Model | Size | Best For | Download |
|-------|------|----------|----------|
| **DASD-4B-Thinking** | 2.5-4GB | Cybersecurity teaching (recommended) | [Hugging Face](https://huggingface.co/MaziyarPanahi/DASD-4B-Thinking-GGUF) |
| **Llama 3.1 8B** | 4.5GB | General purpose | [Hugging Face](https://huggingface.co/TheBloke/Llama-3.1-8B-GGUF) |
| **Mistral 7B** | 4GB | Reasoning & coding | [Hugging Face](https://huggingface.co/TheBloke/Mistral-7B-v0.1-GGUF) |
| **Phi-3 Mini** | 1.8GB | Fast, low RAM usage | [Hugging Face](https://huggingface.co/TheBloke/Phi-3-mini-4k-instruct-GGUF) |
| **CodeLlama 7B** | 4GB | Code-heavy explanations | [Hugging Face](https://huggingface.co/TheBloke/CodeLlama-7B-GGUF) |

### Quick Download

```bash
# Example: Download DASD-4B-Thinking (Q4_K_M quantization, ~2.5GB)
wget https://huggingface.co/MaziyarPanahi/DASD-4B-Thinking-GGUF/resolve/main/DASD-4B-Thinking.Q4_K_M.gguf -P models/

# Or download via HuggingFace CLI
huggingface-cli download MaziyarPanahi/DASD-4B-Thinking-GGUF DASD-4B-Thinking.Q4_K_M.gguf --local-dir models/
```

> **Note:** Models are **not included** in the repository (4GB+ files). Users must download their own.

## 🏗️ Architecture

```
professor-tux/
├── app/
│   ├── main.py              # FastAPI routes & endpoints
│   ├── professor.py         # LLM wrapper (llama-cpp-python)
│   ├── mode_loader.py       # Auto-discovers teaching modes
│   ├── rag.py               # RAG pipeline (ChromaDB)
│   ├── sessions.py          # Session management
│   ├── models.py            # Pydantic schemas
│   ├── modes/               # Teaching mode definitions
│   │   ├── recall.md        # 🧠 Socratic mode
│   │   └── guided.md        # 📖 Guided learning
│   └── static/              # Web UI assets
├── models/                  # GGUF model files (not in git)
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
| **Recall** | 🧠 | Socratic questioning — student retrieves answers |
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
6. **Cite** → Sources shown as purple tags

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
| `MODEL_PATH` | `./models/*.gguf` | Path to GGUF model |
| `N_CTX` | `4096` | Context window size |
| `N_GPU_LAYERS` | `0` | GPU layers (0=CPU, -1=all) |
| `MAX_TOKENS` | `1024` | Max response tokens |
| `TEMPERATURE` | `0.7` | Sampling temperature |
| `ADMIN_USERNAME` | `admin` | Admin login |
| `ADMIN_PASSWORD` | `professortux` | Admin password |

See `.env.example` for all options.

## 🐳 Docker

```bash
docker build -t professor-tux .
docker run -p 8000:8000 -v ./models:/app/models professor-tux
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

- Built with [FastAPI](https://fastapi.tiangolo.com) and [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)
- UI inspired by terminal aesthetics and cyberpunk themes
- RAG powered by [ChromaDB](https://www.trychroma.com) and [Sentence Transformers](https://www.sbert.net)

---

<p align="center">Made with 💻 by cybersecurity educators, for cybersecurity learners</p>