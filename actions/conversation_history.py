"""actions/conversation_history.py: look back through past conversations."""
from __future__ import annotations


def search_history(parameters: dict, response=None, player=None, session_memory=None) -> str:
    from core import history
    p = parameters or {}
    query = str(p.get("query", "") or "").strip()
    try:
        limit = int(p.get("limit", 8))
    except (TypeError, ValueError):
        limit = 8
    days = p.get("days")
    try:
        days = float(days) if days not in (None, "") else None
    except (TypeError, ValueError):
        days = None
    return history.format_rows(history.search(query, limit=limit, days=days))


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "search_history",
    "description": ("Searches our past conversations, for example 'what did I ask you about the "
                    "invoice yesterday?'. Returns matching lines with their date and time. "
                    "Use it when the user refers to something said in an earlier session."),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {"type": "STRING", "description": "Words to look for. Empty returns the latest turns."},
            "days": {"type": "NUMBER", "description": "Only look this many days back (optional)"},
            "limit": {"type": "INTEGER", "description": "Most results to return (default 8)"},
        },
        "required": [],
    },
    "handler": search_history,
}
