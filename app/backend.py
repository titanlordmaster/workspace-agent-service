# app/backend.py
from __future__ import annotations

import json
import os
import textwrap
from typing import Any, Dict, List, Optional
from pathlib import Path
import requests


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STUDY_RAG_BASE_URL = os.getenv(
    "STUDY_RAG_BASE_URL", "http://host.docker.internal:8080"
)
LAB_COPILOT_BASE_URL = os.getenv(
    "LAB_COPILOT_BASE_URL", "http://host.docker.internal:8081"
)
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
)

# You can point these at different models if you want
WORKSPACE_CHAT_MODEL = os.getenv("WORKSPACE_CHAT_MODEL", "llama3.1")
WORKSPACE_MANAGER_MODEL = os.getenv("WORKSPACE_MANAGER_MODEL", WORKSPACE_CHAT_MODEL)
WORKSPACE_STUDY_MODEL = os.getenv("WORKSPACE_STUDY_MODEL", WORKSPACE_CHAT_MODEL)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


class WorkspaceBackendError(RuntimeError):
    pass


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise WorkspaceBackendError(f"HTTP error calling {url}: {e}") from e

    try:
        return resp.json()
    except Exception as e:
        raise WorkspaceBackendError(f"Non-JSON response from {url}: {e}") from e


def _generate_text(
    prompt: str,
    *,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    """
    Tiny wrapper around Ollama's /api/generate.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "temperature": temperature,
        "num_ctx": 4096,
        "stream": False,
    }
    data = _post_json(f"{OLLAMA_BASE_URL}/api/generate", payload, timeout=120)
    return (data.get("response") or "").strip()


# ---------------------------------------------------------------------------
# Study RAG + Lab Copilot connectors
# ---------------------------------------------------------------------------


def _call_study_rag_query(question: str, k: int = 8) -> Dict[str, Any]:
    """
    Call Study RAG /query and return the raw JSON.
    """
    payload = {"question": question, "k": k}
    return _post_json(f"{STUDY_RAG_BASE_URL}/query", payload, timeout=60)


def _normalise_rag_query(resp: Dict[str, Any], top_k: int) -> Dict[str, Any]:
    """
    Normalise Study RAG's /query response into a simple, UI-friendly format.

    We tolerate multiple possible shapes:
      - {"answer": "...", "chunks": [ ... ]}
      - {"answer": "...", "retrieved": [ ... ]}
      - {"answer": "...", "results": [ ... ]}
    """
    raw_chunks = (
        resp.get("chunks")
        or resp.get("retrieved")
        or resp.get("results")
        or []
    )

    normalised: List[Dict[str, Any]] = []
    for i, item in enumerate(raw_chunks[:top_k]):
        metadata = item.get("metadata") or {}
        text = (
            item.get("content")
            or item.get("text")
            or item.get("page_content")
            or metadata.get("text")
            or ""
        )

        normalised.append(
            {
                "idx": i + 1,
                "source": (
                    item.get("source")
                    or metadata.get("source")
                    or metadata.get("file_name")
                    or "chunk"
                ),
                "page": metadata.get("page"),
                "chunk_id": item.get("chunk_id") or metadata.get("chunk_id"),
                "text": text,
            }
        )

    return {
        "answer": resp.get("answer") or "",
        "chunks": normalised,
        "raw": resp,
    }


def _call_lab_copilot_chat(question: str, top_k: int = 8) -> Dict[str, Any]:
    """
    Call Lab Copilot's /chat endpoint.

    Lab Copilot itself will call Study RAG internally, but we don't depend
    on that for visualisation – we still show our own RAG view.
    """
    payload = {"question": question, "top_k": top_k}
    return _post_json(f"{LAB_COPILOT_BASE_URL}/chat", payload, timeout=120)


# ---------------------------------------------------------------------------
# Mode 1: RAG only
# ---------------------------------------------------------------------------


def _run_rag_only(question: str, top_k: int) -> Dict[str, Any]:
    raw = _call_study_rag_query(question, k=top_k)
    rag_result = _normalise_rag_query(raw, top_k=top_k)

    # If Study RAG already returns a nice answer, use it.
    answer = rag_result.get("answer") or ""

    # Otherwise, do a tiny summarisation over chunks.
    if not answer and rag_result.get("chunks"):
        ctx = "\n\n".join(f"[{c['idx']}] {c['text']}" for c in rag_result["chunks"])
        prompt = textwrap.dedent(
            f"""
            The user asked:
            {question}

            Here are context snippets from their Study RAG library:
            {ctx}

            Provide a short, direct answer using ONLY this context.
            If you truly cannot answer from it, say so honestly.
            """
        ).strip()
        answer = _generate_text(
            prompt,
            model=WORKSPACE_CHAT_MODEL,
            temperature=0.2,
            max_tokens=512,
        )

    return {
        "mode": "rag_only",
        "question": question,
        "top_k": top_k,
        "answer": answer,
        "rag": rag_result,
        "copilot": None,
        "agent_trace": [],
    }


# ---------------------------------------------------------------------------
# Mode 2: Copilot (RAG visual + Copilot answer)
# ---------------------------------------------------------------------------


def _run_copilot(question: str, top_k: int) -> Dict[str, Any]:
    """
    Workspace behaviour:
      - Call Study RAG first to show chunks.
      - Call Lab Copilot /chat to get its LLM answer (and its own chunks).
    """
    raw = _call_study_rag_query(question, k=top_k)
    rag_result = _normalise_rag_query(raw, top_k=top_k)

    copilot_result = _call_lab_copilot_chat(question, top_k=top_k)
    answer = copilot_result.get("answer") or rag_result.get("answer") or ""

    # If both are empty but we have chunks, summarise them.
    if not answer and rag_result.get("chunks"):
        ctx = "\n\n".join(f"[{c['idx']}] {c['text']}" for c in rag_result["chunks"])
        prompt = textwrap.dedent(
            f"""
            The user asked:
            {question}

            Here are context snippets from their Study RAG library:
            {ctx}

            Provide a short, direct answer using ONLY this context.
            """
        ).strip()
        answer = _generate_text(
            prompt,
            model=WORKSPACE_CHAT_MODEL,
            temperature=0.2,
            max_tokens=512,
        )

    return {
        "mode": "copilot",
        "question": question,
        "top_k": top_k,
        "answer": answer,
        "rag": rag_result,
        "copilot": copilot_result,
        "agent_trace": [],
    }


# ---------------------------------------------------------------------------
# Mode 3: Manager-auto (agent that chooses tools)
# ---------------------------------------------------------------------------


def _decide_next_action(
    question: str,
    history: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Manager LLM that chooses the next tool:

      - "rag"      -> call Study RAG
      - "copilot"  -> call Lab Copilot
      - "final"    -> stop & answer

    We force JSON output for easier parsing.
    """
    hist_lines: List[str] = []
    for h in history:
        hist_lines.append(
            f"Step {h['step']} via {h['tool']}: {h['summary']}"
        )
    hist_text = "\n".join(hist_lines) if hist_lines else "(no previous steps)"

    prompt = textwrap.dedent(
        f"""
        You are the manager brain for Workspace Agent.

        The user asked:
        {question}

        Internal tool-call history so far:
        {hist_text}

        Tools you can choose:
          - "rag": call Study RAG /query to fetch top-K chunks.
          - "copilot": call Lab Copilot /chat (which itself uses RAG).
          - "final": stop calling tools and produce the final answer.

        Respond with STRICT JSON, no extra text:
        {{
          "action": "rag" | "copilot" | "final",
          "reason": "short explanation"
        }}
        """
    ).strip()

    raw = _generate_text(
        prompt,
        model=WORKSPACE_MANAGER_MODEL,
        temperature=0.1,
        max_tokens=256,
    )

    raw_str = raw.strip()
    if not raw_str.startswith("{"):
        idx = raw_str.find("{")
        if idx != -1:
            raw_str = raw_str[idx:]
    if not raw_str.endswith("}"):
        idx = raw_str.rfind("}")
        if idx != -1:
            raw_str = raw_str[: idx + 1]

    try:
        data = json.loads(raw_str)
        action = str(data.get("action", "final")).lower()
        reason = str(data.get("reason", "")).strip()
    except Exception:
        action, reason = "final", "Failed to parse JSON; defaulting to final."

    if action not in {"rag", "copilot", "final"}:
        action = "final"

    return {"action": action, "reason": reason}


def _run_manager_auto(
    question: str,
    top_k: int,
    max_tool_calls: int = 4,
) -> Dict[str, Any]:
    history: List[Dict[str, Any]] = []
    rag_result: Optional[Dict[str, Any]] = None
    copilot_result: Optional[Dict[str, Any]] = None

    for _ in range(max_tool_calls):
        decision = _decide_next_action(question, history)
        action = decision["action"]
        reason = decision["reason"]

        if action == "final":
            history.append(
                {
                    "step": len(history) + 1,
                    "tool": "manager",
                    "summary": f"Stop and answer now. Reason: {reason}",
                }
            )
            break

        if action == "rag":
            raw = _call_study_rag_query(question, k=top_k)
            rag_result = _normalise_rag_query(raw, top_k=top_k)
            summary = rag_result.get("answer") or (
                rag_result["chunks"][0]["text"] if rag_result.get("chunks") else "(no chunks)"
            )
            history.append(
                {
                    "step": len(history) + 1,
                    "tool": "rag",
                    "summary": summary[:400],
                }
            )

        elif action == "copilot":
            copilot_result = _call_lab_copilot_chat(question, top_k=top_k)
            summary = copilot_result.get("answer") or "(no answer)"
            history.append(
                {
                    "step": len(history) + 1,
                    "tool": "copilot",
                    "summary": summary[:400],
                }
            )

    hist_text = "\n".join(
        f"Step {h['step']} via {h['tool']}: {h['summary']}"
        for h in history
    ) or "(no internal steps executed)"

    prompt = textwrap.dedent(
        f"""
        You are Workspace Agent.

        The user asked:
        {question}

        Here is the internal tool-call trace:
        {hist_text}

        Using ONLY what is implied or explicitly stated in that trace,
        provide a clear, concise answer. If information is missing, say so
        instead of hallucinating.
        """
    ).strip()

    answer = _generate_text(
        prompt,
        model=WORKSPACE_MANAGER_MODEL,
        temperature=0.2,
        max_tokens=512,
    )

    return {
        "mode": "manager_auto",
        "question": question,
        "top_k": top_k,
        "answer": answer,
        "rag": rag_result,
        "copilot": copilot_result,
        "agent_trace": history,
    }


# ---------------------------------------------------------------------------
# Mode 4: Study guide LLM
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    base = "-".join(part for part in base.split("-") if part)
    return base or "guide"


def _save_study_guide_files(markdown_text: str, question: str) -> Dict[str, Optional[str]]:
    """
    Save the study guide markdown to data/study_guides and, if possible,
    also render a PDF version.

    Returns:
      {
        "markdown_path": "data/study_guides/....md",
        "markdown_url": "/guides/....md",
        "pdf_path": "data/study_guides/....pdf" or None,
        "pdf_url": "/guides/....pdf" or None,
      }
    """
    base_dir = Path("data/study_guides")
    base_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(question)[:80]
    md_path = base_dir / f"{slug}.md"

    md_path.write_text(markdown_text, encoding="utf-8")

    pdf_path: Optional[Path] = None
    try:
        import markdown as md_mod
        from weasyprint import HTML

        html = md_mod.markdown(markdown_text, output_format="html5")
        pdf_path = base_dir / f"{slug}.pdf"
        HTML(string=html).write_pdf(str(pdf_path))
    except Exception:
        pdf_path = None  # PDF is optional; don't break the flow

    return {
        "markdown_path": str(md_path),
        "markdown_url": f"/guides/{md_path.name}",
        "pdf_path": str(pdf_path) if pdf_path else None,
        "pdf_url": f"/guides/{pdf_path.name}" if pdf_path else None,
    }


def _run_study_guide(question: str, top_k: int) -> Dict[str, Any]:
    """
    Study-guide mode:

      - Call Study RAG /query.
      - Feed the retrieved context into a "study" LLM.
      - Return a structured study guide (markdown) + download links.
    """
    raw = _call_study_rag_query(question, k=top_k)
    rag_result = _normalise_rag_query(raw, top_k=top_k)

    if rag_result.get("chunks"):
        ctx = "\n\n".join(f"[{c['idx']}] {c['text']}" for c in rag_result["chunks"])
    else:
        ctx = rag_result.get("answer") or "(no context found)"

    prompt = textwrap.dedent(
        f"""
        You are a strict but helpful study planner.

        The user wants a study guide for:
        {question}

        Here is the context from their Study RAG library:
        {ctx}

        Build a clear, structured study guide that stays grounded in the context.
        Requirements:
        - Use markdown.
        - Start with a short overview.
        - Then create 5–10 sections with headings.
        - Under each section, list concrete bullet points, exercises, or checkpoints.
        - Do NOT invent facts that are not supported by the context.
        """
    ).strip()

    guide = _generate_text(
        prompt,
        model=WORKSPACE_STUDY_MODEL,
        temperature=0.3,
        max_tokens=1024,
    )

    file_info = _save_study_guide_files(guide, question)

    history = [
        {
            "step": 1,
            "tool": "rag",
            "summary": f"Fetched top-{top_k} chunks from Study RAG.",
        },
        {
            "step": 2,
            "tool": "study_guide_llm",
            "summary": "Generated a structured study guide based on RAG context.",
        },
        {
            "step": 3,
            "tool": "file_export",
            "summary": "Saved guide as markdown and optional PDF.",
        },
    ]

    return {
        "mode": "study_guide",
        "question": question,
        "top_k": top_k,
        "answer": guide,
        "rag": rag_result,
        "copilot": None,
        "agent_trace": history,
        "markdown_url": file_info["markdown_url"],
        "pdf_url": file_info["pdf_url"],
    }


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


# app/backend.py

def run_workspace_query(
    question: str,
    top_k: int = 8,
    mode: str = "copilot",
) -> Dict[str, Any]:
    """
    Unified entry used by FastAPI + JSON API.

    mode:
      - "rag_only"
      - "copilot"
      - "manager_auto"
      - "study_guide"
    """
    question = (question or "").strip()
    if not question:
        return {
            "mode": mode,
            "question": "",
            "top_k": top_k,
            "answer": "",
            "rag": None,
            "copilot": None,
            "agent_trace": [],
            "markdown_url": None,
            "pdf_url": None,
        }

    mode = (mode or "copilot").lower()

    if mode == "rag_only":
        return _run_rag_only(question, top_k=top_k)

    if mode == "study_guide":
        return _run_study_guide(question, top_k=top_k)

    if mode == "manager_auto":
        # 🔥 Hard rule: if the user explicitly asks for a study guide/plan,
        # skip the manager reasoning and delegate straight to the study_guide tool.
        q_lower = question.lower()
        if (
            "study guide" in q_lower
            or "study plan" in q_lower
            or "learning plan" in q_lower
        ):
            sg_result = _run_study_guide(question, top_k=top_k)

            # Make it clear in the UI that this was routed by the manager.
            trace = sg_result.get("agent_trace") or []
            trace.insert(
                0,
                {
                    "step": 1,
                    "tool": "study_guide (direct)",
                    "summary": "User explicitly asked for a study guide/plan, "
                               "so manager delegated directly to the study_guide tool.",
                },
            )
            sg_result["agent_trace"] = trace
            sg_result["mode"] = "manager_auto"
            return sg_result

        # Otherwise, use the normal manager loop
        return _run_manager_auto(question, top_k=top_k)

    # Default: copilot
    return _run_copilot(question, top_k=top_k)
