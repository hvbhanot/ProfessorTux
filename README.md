# Professor Tux

Professor Tux is a FastAPI-based cybersecurity teaching app with:

- a student chat UI at `/`
- an admin panel at `/admin`
- lecture upload and retrieval support
- Ollama-compatible model backends
- file-driven teaching modes in `app/modes/`

Full product docs live at `/docs` after the server is running. API reference lives at `/api/docs`.

## What it does

- `Guided Learning` teaches, explains, and walks through topics step by step.
- `Recall Mode` is a constrained hint-first mode for use during an exam.
- Admins can upload lecture material and configure the default runtime behavior.
- Guided mode can use uploaded lecture context; Recall mode intentionally stays minimal.

## Requirements

- Python `3.10+`
- `python3`, `venv`, and `pip`
- [Ollama](https://ollama.com) running locally or reachable over the network
- At least one available model, for example `qwen3.5:4b`

## Fast setup

Clone the repo and run:

```bash
git clone https://github.com/hvbhanot/ProfessorTux.git
cd ProfessorTux
./setup.sh
```

What `setup.sh` does:

- creates `.venv` if missing
- upgrades `pip`
- installs `requirements.txt`
- creates `.env` from `.env.example` if missing
- creates `data/uploads`, `data/chromadb`, and `data/logs`
- prints the next commands you need to run

If your shell blocks execution, run:

```bash
chmod +x setup.sh
./setup.sh
```

## Manual setup

If you prefer doing it by hand:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
mkdir -p data/uploads data/chromadb data/logs
```

## Configure Ollama

Start Ollama and make sure a model exists:

```bash
ollama serve
ollama pull qwen3.5:4b
```

Default `.env` values:

```bash
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3.5:4b
```

For cloud-backed Ollama models, sign in on the same host:

```bash
ollama signin
```

Then keep `OLLAMA_BASE_URL` pointed at the local Ollama daemon and switch to a `:*-cloud` model from the admin page.

If you want CTF Mode's live `web_search` tool, create an Ollama API key and either paste it into `Admin → Runtime → CTF Web Search` or add it to `.env`:

```bash
OLLAMA_API_KEY=your_ollama_api_key
OLLAMA_WEB_SEARCH_BASE_URL=https://ollama.com
```

`OLLAMA_BASE_URL` is still only for chat/model endpoints such as `/api/chat`; web search calls `https://ollama.com/api/web_search` directly.
Keys saved through the admin page are persisted in `data/admin_runtime.json`.
When CTF Mode has web search configured, Professor Tux preloads a web search for every non-social CTF turn and still lets the model call `web_search` again for narrower follow-up queries.

## Run the app

After setup:

```bash
source .venv/bin/activate
python run.py
```

Or without activating:

```bash
.venv/bin/python run.py
```

## Access points

- Student UI: `http://localhost:8000/`
- Admin UI: `http://localhost:8000/admin`
- Product docs: `http://localhost:8000/docs`
- API docs: `http://localhost:8000/api/docs`
- ReDoc: `http://localhost:8000/api/redoc`

Default admin credentials:

```text
username: admin
password: professortux
```

Change them in `.env` before using this outside a local machine.

## First-time admin flow

1. Open `/admin`.
2. Confirm the Ollama API URL.
3. Enter a model name and click `Run`.
4. Choose the default student mode.
5. Upload lecture files if you want Guided mode grounded in course material.
6. Open `/` and test both Guided and Recall behavior.

## Built-in modes

Current repo modes are loaded from `app/modes/`:

- `guided`
- `recall`
- `guided_wrong`
- `recall_wrong`

Modes are markdown files with frontmatter plus a prompt body. Add or edit files under `app/modes/`, then reload modes from admin or restart the server.

## Lecture uploads and retrieval

Supported upload types:

- `.pdf`
- `.pptx`
- `.ppt`
- `.txt`
- `.md`

Upload flow:

1. file is saved under `data/uploads`
2. text is extracted
3. content is chunked and embedded
4. embeddings are stored in `data/chromadb`

Notes:

- Guided mode can prefetch lecture context before generation.
- Recall mode intentionally does not inject uploaded lecture context.

## Important files

```text
app/main.py             FastAPI routes and runtime behavior
app/professor.py        prompt construction and generation wrapper
app/llm_backends.py     Ollama-compatible backend adapter
app/rag.py              lecture ingestion and retrieval
app/modes/              mode definitions
app/static/index.html   student UI
app/static/admin.html   admin UI
app/static/docs.html    in-app documentation page
run.py                  server entry point
setup.sh                local bootstrap script
```

## Environment variables

Core variables from `.env.example`:

| Variable | Default | Purpose |
|---|---|---|
| `HOST` | `0.0.0.0` | bind host |
| `PORT` | `8000` | bind port |
| `ADMIN_USERNAME` | `admin` | admin login |
| `ADMIN_PASSWORD` | `professortux` | admin login |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama-compatible backend |
| `OLLAMA_MODEL` | `qwen3.5:4b` | default model target |
| `OLLAMA_KEEP_ALIVE` | `5m` | Ollama keep-alive |
| `OLLAMA_API_KEY` | empty | enables Ollama cloud web search for CTF Mode; can also be saved from admin |
| `OLLAMA_WEB_SEARCH_BASE_URL` | `https://ollama.com` | Ollama web-search API base URL |
| `MAX_TOKENS` | `1024` | response cap |
| `TEMPERATURE` | `0.7` | generation temperature |
| `MODEL_REQUEST_TIMEOUT` | `60` | backend timeout |
| `CHAT_LOG_DIR` | `./data/logs` | log path |

Additional retrieval variables are handled in `app/rag.py`.

## Troubleshooting

### Student UI says no model is ready

- make sure `ollama serve` is running
- open `/admin`
- verify the Ollama URL
- switch to a valid model

### Uploads seem ignored

- test in `Guided Learning`, not Recall
- confirm the file appears in admin
- make sure lecture context is enabled

### Old chat breaks after server restart

Sessions are in memory. Refresh the page so the frontend creates a fresh session.

### Need deeper setup details

Run the app and open:

- `/docs` for the full operator guide
- `/api/docs` for the API schema
