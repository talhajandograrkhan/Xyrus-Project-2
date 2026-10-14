from core.diag import swallowed as _swallowed
import json
import re
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
_lock            = Lock()
MAX_VALUE_LENGTH = 380

# ── Why there are two very different numbers here ────────────────────────────
#
# There used to be one: MEMORY_MAX_CHARS = 2200, applied to the whole store. It
# was a *storage* limit, and it existed only because the entire memory was
# pasted into the system prompt on every connect — so growing the memory grew
# every single request. When it filled, _trim_to_limit() deleted the oldest
# entries and printed one line to a console nobody reads. A memory described as
# "deeply remembers projects, preferences and personal context" was in practice
# two pages long, and quietly forgot your sister's name after a few weeks.
#
# Storage and prompt budget are now separate concerns:
#
#   MEMORY_MAX_CHARS  — a runaway guard, not a feature limit. Nothing normal
#                       reaches it; a bug writing in a loop does.
#   PROMPT_CORE_CHARS — what actually rides in the system prompt every session.
#                       Smaller than the old whole-memory dump, so sessions
#                       start *faster* than before, not slower.
#
# Everything above the core stays on disk and is fetched on demand by the
# recall_memory tool — see search_memory() and format_memory_for_prompt().
MEMORY_MAX_CHARS  = 200_000
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
# Most entries any one category may contribute to the core block, so a person
# with forty stored preferences still gets their sister into the prompt.
PROMPT_MAX_PER_CATEGORY = 6

def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {},
        "profile":       {},
        "tasks":         {},
        "sessions":      [],
    }

def load_memory() -> dict:
    if not MEMORY_PATH.exists():
        return _empty_memory()
    with _lock:
        try:
            data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base = _empty_memory()
                for key in base:
                    if key not in data:
                        data[key] = {}
                return data
            return _empty_memory()
        except Exception as e:
            print(f"[Memory] ⚠️ Load error: {e}")
            return _empty_memory()

def _all_entries(memory: dict) -> list[tuple]:
    entries = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                entries.append((cat, key, entry))
    return entries


# Set by main.py so a trim can reach the activity log. Deleting something a
# person told you and mentioning it only on stdout is how a memory loses trust.
_trim_notifier = None


def set_trim_notifier(fn) -> None:
    """Register a callable(str) that surfaces trims to the user."""
    global _trim_notifier
    _trim_notifier = fn


def _trim_to_limit(memory: dict) -> dict:
    if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
        return memory
    entries = _all_entries(memory)
    entries.sort(key=lambda t: t[2].get("updated", "0000-00-00"))
    dropped = []
    for cat, key, _ in entries:
        if len(json.dumps(memory, ensure_ascii=False)) <= MEMORY_MAX_CHARS:
            break
        del memory[cat][key]
        dropped.append(f"{cat}/{key}")
        print(f"[Memory] 🗑️  Trimmed {cat}/{key}")
    if dropped and _trim_notifier:
        try:
            _trim_notifier(
                f"SYS: Memory full — forgot {len(dropped)} oldest entries "
                f"({', '.join(dropped[:3])}{'…' if len(dropped) > 3 else ''})"
            )
        except Exception as _exc:
            _swallowed(__name__, _exc)
    return memory

def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    memory = _trim_to_limit(memory)
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _normalize_tags(tags) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        raw = [t.strip() for t in tags.split(",")]
    elif isinstance(tags, (list, tuple, set)):
        raw = list(tags)
    else:
        raw = [str(tags)]
    norm: list[str] = []
    for item in raw:
        tag = str(item).strip().lower().replace("_", " ")
        tag = re.sub(r"\s+", " ", tag)
        if tag and tag not in norm:
            norm.append(tag)
    return norm


def _confidence_value(confidence) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, value))


def _merge_entry_metadata(entry: dict, *, value, tags=None, confidence=None, source=None, editable=None, created=None, updated=None) -> dict:
    if not isinstance(entry, dict):
        entry = {}
    base = dict(entry)
    new_val = _truncate_value(str(value))
    if "value" in base and new_val == base.get("value") and value is not None and not isinstance(value, dict):
        pass
    now = updated or _now_iso()
    base["value"] = new_val
    if created is not None:
        base["created"] = str(created)
    elif "created" not in base:
        base["created"] = now
    if updated is not None:
        base["updated"] = str(updated)
    else:
        base["updated"] = now
    if tags is not None:
        base["tags"] = _normalize_tags(tags)
    elif "tags" in base and base["tags"] is not None:
        base["tags"] = _normalize_tags(base["tags"])
    if confidence is not None:
        base["confidence"] = _confidence_value(confidence)
    elif "confidence" in base and base["confidence"] is not None:
        base["confidence"] = _confidence_value(base["confidence"])
    if source is not None:
        base["source"] = str(source)
    if editable is not None:
        base["editable"] = bool(editable)
    if "value" in base and base.get("value") == "":
        base["value"] = _truncate_value(str(value or ""))
    return base


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, dict) and "value" not in value and not any(k in value for k in ("tags", "confidence", "source", "editable", "created", "updated")):
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            existing = target.get(key, {})
            if isinstance(value, dict):
                raw_value = value.get("value")
                if raw_value is None and "value" not in value and value:
                    if key in target and isinstance(target[key], dict):
                        raw_value = target[key].get("value")
                entry = _merge_entry_metadata(
                    existing,
                    value=raw_value if raw_value is not None else "",
                    tags=value.get("tags"),
                    confidence=value.get("confidence"),
                    source=value.get("source"),
                    editable=value.get("editable"),
                    created=value.get("created"),
                    updated=value.get("updated"),
                )
            else:
                entry = _merge_entry_metadata(existing, value=value)
            if not isinstance(existing, dict) or existing != entry:
                target[key] = entry
                changed = True
    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()
    memory = load_memory()
    if _recursive_update(memory, memory_update):
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory

def _entry_value(entry) -> str:
    """Accept both the {'value': ..., 'updated': ...} shape and a bare string,
    because early versions of the store wrote plain strings."""
    if isinstance(entry, dict):
        return str(entry.get("value", "") or "").strip()
    return str(entry or "").strip()


def _entry_tags(entry) -> list[str]:
    if isinstance(entry, dict):
        return _normalize_tags(entry.get("tags"))
    return []


def _entry_confidence(entry) -> float:
    if isinstance(entry, dict):
        return _confidence_value(entry.get("confidence", 0.5))
    return 0.5


_SEMANTIC_ALIASES = {
    "favorite": {"favorite", "favourite", "prefer", "prefers", "preferred", "likes", "like", "choice", "chosen"},
    "preference": {"preference", "preferences", "favorite", "favourite", "prefer", "preferred", "likes", "like"},
    "color": {"color", "colour", "hue", "shade", "tone", "paint", "pigment"},
    "name": {"name", "named", "call", "called", "title", "username"},
    "person": {"person", "people", "friend", "friends", "contact", "contacts", "buddy", "stranger", "acquaintance"},
    "remember": {"remember", "recall", "know", "knows"},
    "food": {"food", "meal", "drink", "snack", "dish"},
    "music": {"music", "song", "artist", "genre", "playlist"},
}


def _semantic_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    if not text:
        return tokens
    for token in re.split(r"[^a-z0-9]+", str(text).lower()):
        token = token.strip()
        if not token:
            continue
        tokens.add(token)
        for canonical, aliases in _SEMANTIC_ALIASES.items():
            if token in aliases:
                tokens.add(canonical)
                tokens.update(aliases)
    return tokens


def _semantic_overlap_score(query_words: list[str], key: str, value: str, entry: dict | None = None) -> int:
    if not query_words:
        return 0
    key_tokens = _semantic_tokens(key)
    value_tokens = _semantic_tokens(value)
    query_tokens = set()
    for word in query_words:
        query_tokens |= _semantic_tokens(word)
    overlap = query_tokens & (key_tokens | value_tokens)
    score = len(overlap) * 7
    if overlap:
        score += 4
    if query_tokens & {"favorite", "favourite", "prefer", "preferred"} and (key_tokens & {"favorite", "favourite", "prefer", "preferred", "preference"} or value_tokens & {"favorite", "favourite", "prefer", "preferred", "preference"}):
        score += 8
    if query_tokens & {"color", "colour", "hue", "shade", "tone"} and (key_tokens & {"color", "colour", "hue", "shade", "tone"} or value_tokens & {"color", "colour", "hue", "shade", "tone"}):
        score += 8
    if isinstance(entry, dict):
        score += int(_entry_confidence(entry) * 5)
    return score


def _pretty(key: str) -> str:
    return key.replace("_", " ").strip()


# Identity is always in the prompt; these categories compete for the remaining
# budget by recency.
_CATEGORY_LABELS = {
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
    "profile":       "Profile / stored facts",
    "tasks":         "Tasks / follow-ups",
}

_IDENTITY_FIELDS = ["name", "age", "birthday", "city", "job",
                    "language", "school", "nationality"]


def format_memory_for_prompt(memory: dict | None) -> str:
    """Build the memory block that goes into the system prompt.

    This used to dump everything. It now sends three things:

      1. IDENTITY  - always, in full. It is small, and it is wrong for the
         assistant to have to look up your name.
      2. RECENT    - the most recently updated entries from every other
         category, up to PROMPT_CORE_CHARS. Recency is the cheapest useful
         relevance signal available without embeddings.
      3. AN INDEX  - the *keys* of everything else, values omitted.

    Point 3 is what makes recall work at all. A model cannot decide to look
    something up if it does not know the thing exists: with only points 1 and 2,
    "who is Ayse?" would get "I don't know" while ayse_sister sat on disk
    unread. The index costs a few hundred characters and turns recall from a
    gamble into a lookup.

    Net effect on latency: this block is SMALLER than the old full dump, so
    every session connects with fewer tokens. Occasionally the model spends one
    extra round trip on recall_memory - covered by the acknowledgment it
    already speaks before any slow step."""
    if not memory:
        return ""

    core_lines: list[str] = []

    # 1. Identity - always, in full
    identity = memory.get("identity", {}) or {}
    for field in _IDENTITY_FIELDS:
        val = _entry_value(identity.get(field))
        if not val:
            continue
        if field == "language":
            # Labelled as an observation, not a setting. A bare "Language:
            # English" line written months ago reads like a standing order and
            # was one of the reasons a Turkish question came back in English.
            core_lines.append(
                f"Has spoken to you in: {val} (an observation about the past — "
                f"always answer in the language of their CURRENT message)")
        else:
            core_lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in _IDENTITY_FIELDS:
            continue
        val = _entry_value(entry)
        if val:
            core_lines.append(f"{_pretty(key).title()}: {val}")

    # 2. Everything else, most recently updated first
    rest: list[tuple[str, str, str, str]] = []   # (updated, cat, key, value)
    for cat in _CATEGORY_LABELS:
        for key, entry in (memory.get(cat, {}) or {}).items():
            val = _entry_value(entry)
            if not val:
                continue
            updated = (entry.get("updated", "") if isinstance(entry, dict) else "") or "0000-00-00"
            rest.append((updated, cat, key, val))
    rest.sort(key=lambda t: t[0], reverse=True)

    used    = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}

    # Recency decides order, but no single category may take the whole budget.
    # Without the cap, someone with forty stored preferences gets a prompt that
    # is forty preferences and not one person's name — the categories that
    # matter most in conversation are also the ones that change least often, so
    # pure recency systematically buries them.
    per_cat_used: dict[str, int] = {}
    for _updated, cat, key, val in rest:
        line = f"  - {_pretty(key).title()}: {val}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY
                and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(_pretty(key))

    # The index is a table of contents, so it is interleaved across categories
    # rather than continuing in recency order. Sorted by recency it would list
    # twenty-four preferences before the first relationship, and the one entry
    # the index exists for — the old fact the model has no other way to know
    # about — would fall off the end.
    indexed: list[str] = []
    if overflow:
        cats  = [c for c in _CATEGORY_LABELS if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    for cat, label in _CATEGORY_LABELS.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    if not core_lines and not indexed:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]",
        *core_lines,
    ]

    # 3. The index of what is on disk but not in this prompt
    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append(
                "[ALSO REMEMBERED — values not shown here. Call recall_memory "
                "with a keyword to read any of these before saying you do not know]"
            )
            out.append(", ".join(names)
                       + (f" (+{len(indexed) - len(names)} more)"
                          if len(indexed) > len(names) else ""))

    return "\n".join(out) + "\n"


# ── Recall ────────────────────────────────────────────────────────────────────

def _score(query_words: list[str], cat: str, key: str, value: str, entry: dict | None = None) -> int:
    """Cheap lexical relevance with metadata boosts.

    This keeps the recall path local and fast while recognizing the most useful
    signals: exact key hits, tag matches, higher-confidence facts, and real text
    overlap from the value itself. It is still a deterministic rule-based scan,
    not a remote embedding lookup, so it remains cheap enough to call during a
    live assistant turn without blocking the conversation."""
    hay_key = _pretty(key).lower()
    hay_val = value.lower()
    score = 0
    tags = _entry_tags(entry) if isinstance(entry, dict) else []
    tag_text = " ".join(tags)
    sanitized_query = {w.strip() for w in query_words if w.strip()}
    for w in query_words:
        if not w:
            continue
        key_variants = {hay_key, hay_key.replace(" ", "_"), hay_key.replace("_", " ")}
        if w in key_variants or w == hay_key or w == hay_key.replace(" ", "_"):
            score += 20
        elif w in hay_key or w in hay_key.replace(" ", "_"):
            score += 9
        if w in hay_val:
            score += 6
        if w in tag_text:
            score += 12
        if w in cat.lower():
            score += 2
        if w in {"favorite", "favourite", "likes", "love", "pref"} and "prefer" in hay_key:
            score += 3
        if w in {"name", "person", "people", "contact"} and "relationship" in cat:
            score += 3
    if sanitized_query and any(w in hay_key for w in sanitized_query):
        score += 4
    if sanitized_query and any(w in tag_text for w in sanitized_query):
        score += 6
    if isinstance(entry, dict):
        score += int(_entry_confidence(entry) * 10)
    return score


def search_memory(query: str, limit: int = 8) -> str:
    """Find stored facts matching `query`. Backs the recall_memory tool.

    The lookup combines fast lexical scoring with an alias-based semantic pass so
    variants like "favorite" / "favourite" or "hue" / "color" still resolve to
    the same stored fact. This keeps the recall path local, deterministic and
    cheap enough to run during a live turn.
    """
    memory = load_memory()
    words  = [w for w in re.split(r"[\W_]+", (query or "").lower()) if len(w) > 1]

    rows: list[tuple[int, str, str, str, dict | None]] = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            base_score = _score(words, cat, key, val, entry if isinstance(entry, dict) else None) if words else 1
            semantic_score = _semantic_overlap_score(words, key, val, entry if isinstance(entry, dict) else None) if words else 0
            total_score = max(base_score, semantic_score)
            if total_score > 0:
                rows.append((total_score, cat, key, val, entry if isinstance(entry, dict) else None))

    if not rows:
        return (f"Nothing stored about '{query}'." if query
                else "I have not stored anything about this person yet.")

    rows.sort(key=lambda r: (-r[0], r[2]))
    lines = []
    for _s, cat, key, val, entry in rows[:max(1, limit)]:
        tags = _entry_tags(entry) if isinstance(entry, dict) else []
        conf = _entry_confidence(entry) if isinstance(entry, dict) else 0.5
        suffix = ""
        if tags or conf:
            tag_str = ", ".join(tags) if tags else "no tags"
            suffix = f" (confidence {conf:.2f}, tags: {tag_str})"
        lines.append(f"{cat}/{key}: {val}{suffix}")
    head  = (f"Stored facts matching '{query}':" if query
             else "Everything currently stored:")
    more  = (f"\n(+{len(rows) - len(lines)} more — search with a narrower keyword)"
             if len(rows) > len(lines) else "")
    return head + "\n" + "\n".join(lines) + more


def all_entries_for_ui() -> list[dict]:
    """Flat list for the memory panel: what JARVIS knows, and when it learned it.
    Sorted newest first so the panel opens on what changed most recently."""
    memory = load_memory()
    rows = []
    for cat, items in memory.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            val = _entry_value(entry)
            if not val:
                continue
            rows.append({
                "category": cat,
                "key":      key,
                "value":    val,
                "updated":  (entry.get("updated", "") if isinstance(entry, dict) else ""),
                "tags":     _entry_tags(entry) if isinstance(entry, dict) else [],
                "confidence": _entry_confidence(entry) if isinstance(entry, dict) else 0.5,
                "editable": bool((entry.get("editable") if isinstance(entry, dict) else True)),
            })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows


def remember(key: str, value: str, category: str = "notes", *, tags=None, confidence: float | int = 0.5, source: str = "user", editable: bool = True) -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes", "profile", "tasks"}
    if category not in valid:
        category = "notes"
    memory = load_memory()
    cat = memory.get(category, {})
    if not isinstance(cat, dict):
        cat = {}
    entry = _merge_entry_metadata(
        cat.get(key, {}),
        value=value,
        tags=tags,
        confidence=confidence,
        source=source,
        editable=editable,
    )
    cat[key] = entry
    memory[category] = cat
    save_memory(memory)
    return f"Remembered: {category}/{key} = {value}"


def update_memory_entry(key: str, value: str, category: str = "notes", *, tags=None, confidence: float | int = 0.5, source: str = "user", editable: bool = True) -> dict:
    """Update an existing memory record while preserving/adding metadata."""
    memory = load_memory()
    cat = memory.get(category, {})
    if not isinstance(cat, dict):
        cat = {}
    entry = _merge_entry_metadata(
        cat.get(key, {}),
        value=value,
        tags=tags,
        confidence=confidence,
        source=source,
        editable=editable,
    )
    cat[key] = entry
    memory[category] = cat
    save_memory(memory)
    return entry


def merge_memory_entry(key: str, value: str, category: str = "notes", *, alias_key: str | None = None, tags=None, confidence: float | int = 0.5, source: str = "user", editable: bool = True) -> dict:
    """Merge a memory update into an existing record and optionally collapse an alias key.

    This keeps duplicate, near-identical facts from drifting apart when the user
    edits a memory or adds a variant spelling such as favorite_color vs
    favourite_colour.
    """
    memory = load_memory()
    cat = memory.get(category, {})
    if not isinstance(cat, dict):
        cat = {}

    canonical_key = key
    if alias_key and alias_key in cat and alias_key != key:
        canonical_key = alias_key
    elif alias_key and alias_key != key and key not in cat and alias_key not in cat:
        canonical_key = key

    existing = cat.get(canonical_key, {}) if isinstance(cat.get(canonical_key), dict) else {}
    merged = _merge_entry_metadata(
        existing,
        value=value,
        tags=tags,
        confidence=confidence,
        source=source,
        editable=editable,
    )
    cat[canonical_key] = merged

    if alias_key and alias_key != canonical_key and alias_key in cat:
        alias_entry = cat.get(alias_key)
        alias_value = _entry_value(alias_entry)
        if alias_value == value:
            del cat[alias_key]

    if key != canonical_key and key in cat and key != canonical_key and cat.get(key) == merged:
        del cat[key]

    memory[category] = cat
    save_memory(memory)
    return merged


def edit_memory(key: str, value: str, category: str = "notes", **kwargs) -> dict:
    """Compatibility alias for user-editable memory updates."""
    alias_key = kwargs.pop("alias_key", None)
    if alias_key is None and "key" in kwargs:
        alias_key = kwargs.pop("key")
    return merge_memory_entry(key, value, category, alias_key=alias_key, **kwargs)


def remember_user_fact(key: str, value: str) -> str:
    """Persist a user fact in the profile bucket without disturbing older categories."""
    return remember(key, value, category="profile")


def add_task(title: str, description: str = "", status: str = "pending", risk_level: str = "low") -> str:
    """Add a persistent task item for the assistant to complete later."""
    if not title or not title.strip():
        return "Task title is required."
    memory = load_memory()
    tasks = memory.get("tasks", {})
    if not isinstance(tasks, dict):
        tasks = {}
    slug = re.sub(r"[^a-z0-9]+", "_", (title or "task").strip().lower()).strip("_") or "task"
    task_key = slug
    counter = 1
    while task_key in tasks:
        counter += 1
        task_key = f"{slug}_{counter}"
    tasks[task_key] = {
        "value": f"{status.upper()} | {description.strip() or 'No description'} | {title.strip()}",
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "status": status,
        "title": title.strip(),
        "description": (description or "").strip(),
        "risk_level": str(risk_level or "low").strip().lower(),
    }
    memory["tasks"] = tasks
    save_memory(memory)
    return f"Task saved: {title.strip()}"


def list_tasks(limit: int = 10) -> list[dict]:
    """Return current tasks in newest-first order; safe for dashboard or agents."""
    memory = load_memory()
    tasks = memory.get("tasks", {})
    if not isinstance(tasks, dict):
        return []
    rows = []
    for key, entry in tasks.items():
        if not isinstance(entry, dict):
            continue
        rows.append({
            "key": key,
            "title": str(entry.get("title") or key),
            "description": str(entry.get("description") or ""),
            "status": str(entry.get("status") or "pending"),
            "updated": str(entry.get("updated") or ""),
            "value": str(entry.get("value") or ""),
            "risk_level": str(entry.get("risk_level") or "low").lower(),
        })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00", r["title"]), reverse=True)
    return rows[:max(1, limit)]


def complete_task(task_key: str) -> str:
    """Mark a stored task complete without deleting it, so history remains visible."""
    memory = load_memory()
    tasks = memory.get("tasks", {})
    if not isinstance(tasks, dict):
        return f"Task not found: {task_key}"
    if task_key not in tasks:
        return f"Task not found: {task_key}"
    entry = tasks[task_key]
    if not isinstance(entry, dict):
        return f"Task not found: {task_key}"
    entry["status"] = "completed"
    entry["updated"] = datetime.now().strftime("%Y-%m-%d")
    entry["value"] = f"COMPLETED | {entry.get('description') or 'No description'} | {entry.get('title') or task_key}"
    memory["tasks"] = tasks
    save_memory(memory)
    return f"Task marked complete: {entry.get('title') or task_key}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    if key in cat:
        del cat[key]
        memory[category] = cat
        save_memory(memory)
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


forget_memory = forget


# ── Session memory ─────────────────────────────────────────────────────────────

_SESSION_MAX = 3   # safety cap — in practice 0-1 entries after pop


def save_session_summary(summary: str, language: str = "") -> None:
    """Append a 1-2 sentence session summary to long_term.json['sessions']."""
    summary = (summary or "").strip()
    if not summary:
        return
    memory   = load_memory()
    sessions = memory.get("sessions", [])
    if not isinstance(sessions, list):
        sessions = []
    entry: dict = {
        "date":    datetime.now().strftime("%Y-%m-%d"),
        "summary": summary[:280],
    }
    if language:
        entry["language"] = language
    sessions.append(entry)
    memory["sessions"] = sessions[-_SESSION_MAX:]
    with _lock:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(f"[Memory] 📝 Session saved ({entry['date']}): {summary[:60]}…")


def pop_last_session() -> dict | None:
    """
    Return AND remove the most recent session entry.
    Calling this consumes the entry so it is never repeated in future briefings.
    """
    with _lock:
        if not MEMORY_PATH.exists():
            return None
        try:
            memory   = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
            sessions = memory.get("sessions", [])
            if not isinstance(sessions, list) or not sessions:
                return None
            entry = sessions.pop()          # remove the last entry
            memory["sessions"] = sessions
            MEMORY_PATH.write_text(
                json.dumps(memory, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return entry
        except Exception as e:
            print(f"[Memory] ⚠️ pop_last_session error: {e}")
            return None