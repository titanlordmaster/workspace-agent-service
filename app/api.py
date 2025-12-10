# app/api.py
from __future__ import annotations

from typing import Dict

from .backend import run_workspace_query


def ask_workspace(
    question: str,
    top_k: int = 8,
    mode: str = "copilot",
) -> Dict:
    """
    Thin wrapper so the rest of the app doesn't need to know backend details.
    """
    return run_workspace_query(
        question=question,
        top_k=top_k,
        mode=mode,
    )
