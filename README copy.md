# AI Workbench – Workspace Agent

Workspace Agent is the “hub” service in the AI Workbench stack.

It sits in front of:

- **Study RAG** – document ingestion + retrieval (`/query`)
- **Lab Copilot** – LLM chat head that is *already* grounded in Study RAG

and gives you a single UI + API where an agent can:

- Call **raw RAG** and show the chunks
- Call **Lab Copilot** over those chunks
- Run a **manager-style auto loop** that chooses tools and stitches a final answer
- Generate **downloadable study guides** (Markdown, and optionally PDF) from RAG context

---

## Architecture

This service is a small FastAPI app with:

- `app/service.py` – FastAPI app + HTML routes
- `app/backend.py` – tool logic (RAG, Copilot, manager, study-guide generator)
- `app/api.py` – thin wrapper that exposes `run_workspace_query`
- `templates/` – `base.html` + `index.html` (dark UI)
- `static/css/main.css` – shared styling
- `data/` – runtime files (saved study guides, etc.)

It talks to the other services over HTTP:

- **Study RAG** – `POST {STUDY_RAG_BASE_URL}/query`
- **Lab Copilot** – `POST {LAB_COPILOT_BASE_URL}/chat`

Both base URLs are configurable via environment variables.

---

## Modes

All modes go through a single entry point:

```python
run_workspace_query(question: str, top_k: int = 8, mode: str = "copilot")
````

Supported `mode` values:

### 1. `rag_only`

* Calls **Study RAG** directly.
* Returns:

  * `answer`: a short summary (if available)
  * `rag`: raw JSON from Study RAG, including `chunks`
* UI shows the chunks as compact cards (“Study RAG” column on the bottom card).

Use this when you just want to see *exactly* what RAG retrieved.

---

### 2. `copilot`

* Calls **Study RAG** first to get top-K chunks.
* Passes those chunks into **Lab Copilot**, which:

  * builds a context-aware prompt
  * calls Ollama behind the scenes
* Returns:

  * `answer`: Copilot’s LLM answer
  * `rag`: the chunks from Study RAG
  * `copilot`: the chunks Copilot saw (for transparency)

Use this as the default “chat over your library” mode.

---

### 3. `manager_auto`

* Treats **RAG** and **Copilot** as tools.
* A “manager” LLM gets:

  * the original question
  * a budget of up to **4 tool calls**
* It can:

  1. Call `rag_only` to inspect context
  2. Call `copilot` one or more times for drafted answers
  3. Decide when to **stop and answer**
* Returns:

  * `answer`: manager’s final, stitched answer
  * `agent_trace`: list of `{step, tool, summary}` describing what it did
  * `rag` / `copilot` as appropriate

The UI shows this in the **Manager trace** section.

---

### 4. `study_guide`

* Calls **Study RAG** for top-K chunks.

* Asks a dedicated **study-guide LLM** to turn the context into a markdown learning plan:

  * overview + key concepts
  * sections / headings
  * exercises and checkpoints

* Saves the result under `data/study_guides/` as:

  * `*.md` – raw markdown
  * optionally `*.pdf` – if PDF support is installed

* Returns:

  * `answer`: the markdown text
  * `markdown_url`: `/static/...` style download URL
  * `pdf_url` (if generated)

The UI shows “Download markdown / Download PDF” buttons when this mode is used.

---

## HTTP Endpoints

All routes are defined in `app/service.py`.

### HTML UI

* `GET /`
  Renders `templates/index.html` – the Workspace Agent dashboard.

* `POST /workspace/query`
  Handles form submission from the UI.
  Reads `question`, `top_k`, and `mode`, then calls `run_workspace_query`.

### JSON API

* `GET /healthz`
  Lightweight health check. Returns service status and a simple payload.

* `POST /chat`
  JSON wrapper around `run_workspace_query`:

  ```jsonc
  POST /chat
  {
    "question": "What is MCP?",
    "top_k": 5,
    "mode": "copilot"  // or rag_only, manager_auto, study_guide
  }
  ```

  Response shape:

  ```jsonc
  {
    "mode": "copilot",
    "question": "What is MCP?",
    "top_k": 5,
    "answer": "...",
    "rag": { "chunks": [...] },
    "copilot": { "chunks": [...] },
    "agent_trace": [],     // non-empty only for manager_auto
    "markdown_url": null,  // non-null for study_guide
    "pdf_url": null
  }
  ```

---

## Configuration

Environment variables (with typical defaults):

* `STUDY_RAG_BASE_URL`
  Base URL for the Study RAG service (e.g. `http://study-rag:8080`).

* `LAB_COPILOT_BASE_URL`
  Base URL for the Lab Copilot service (e.g. `http://lab-copilot:8081`).

You’re expected to have:

* Study RAG service running and reachable at `STUDY_RAG_BASE_URL`
* Lab Copilot service running and reachable at `LAB_COPILOT_BASE_URL`
* Lab Copilot itself already wired to Ollama or whatever LLM backend you choose

Workspace Agent never talks to Ollama directly – it only calls Lab Copilot.

---

## Requirements

`requirements.txt` (conceptually):

```txt
fastapi
uvicorn
requests
jinja2
python-multipart
markdown2        # for study guide markdown handling
reportlab        # if you enable PDF export
```

If you don’t care about PDFs, you can drop `reportlab` and the related code.

---

## Running with Docker

The repo includes a `Dockerfile` and `docker-compose.yml` sized just for this service.

Example `docker-compose.yml` snippet:

```yaml
services:
  workspace-agent:
    build: .
    ports:
      - "8082:8082"
    environment:
      STUDY_RAG_BASE_URL: "http://study-rag:8080"
      LAB_COPILOT_BASE_URL: "http://lab-copilot:8081"
    volumes:
      - ./data:/app/data
```

With the other services running on the same Docker network:

```bash
docker compose up
```

Open:

* `http://localhost:8082` → Workspace Agent UI

---

## Running Locally (without Docker)

```bash
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

export STUDY_RAG_BASE_URL="http://localhost:8080"
export LAB_COPILOT_BASE_URL="http://localhost:8081"

uvicorn app.service:app --reload --port 8082
```

Then browse to `http://localhost:8082`.

---

## Typical Workflows

### 1. Inspect what RAG sees

1. Select **Mode: RAG only**.
2. Ask: `What is MCP?`
3. Look at the **Retrieved context → Study RAG** card.
4. You’ll see the exact chunks being retrieved from your library.

### 2. Get a grounded answer

1. Select **Mode: Copilot**.
2. Ask: `Explain MCP in simple terms.`
3. Top card shows Copilot’s answer.
4. Bottom card shows both:

   * the chunks Study RAG retrieved
   * the chunks Copilot saw

### 3. Let the manager decide

1. Select **Mode: Manager auto**.
2. Ask something open-ended: `Compare MCP to traditional API integrations.`
3. Watch the **Manager trace** to see:

   * which tools it called
   * in what order
   * and why it stopped

### 4. Generate a study guide

1. Select **Mode: Study guide**.
2. Ask: `Create a study guide about this question: what is an MCP?`
3. The answer pane will show the markdown guide.
4. Use the **Download markdown / PDF** buttons to save it.

---

## Folder Layout

```text
workspace-agent-service/
  app/
    api.py
    backend.py
    service.py
  templates/
    base.html
    index.html
  static/
    css/
      main.css
  data/
    study_guides/        # generated .md / .pdf files
  Dockerfile
  docker-compose.yml
  requirements.txt
  README.md
```

---

## Notes / Future Ideas

* Add authentication (simple token or OAuth) for multi-user setups.
* Persist agent traces and study guides with metadata for later reuse.
* Add per-mode configuration (temperature, max_tokens) via UI.
