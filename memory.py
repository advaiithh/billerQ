import re
from collections import defaultdict, deque
from typing import Any

try:
    from langchain.memory import ConversationBufferMemory
except Exception:
    ConversationBufferMemory = None


class _FallbackMemory:
    def save_context(self, inputs, outputs):
        return None


memory = (
    ConversationBufferMemory(return_messages=True)
    if ConversationBufferMemory
    else _FallbackMemory()
)

# Each session keeps the last few turns of conversation
_SESSION_TURNS = defaultdict(lambda: deque(maxlen=5))

# Each session keeps the last few result snapshots (table, columns, rows)
# so follow-ups can filter from the cached result instead of hitting the DB.
_SESSION_RESULT_CACHE: dict[str, deque] = defaultdict(lambda: deque(maxlen=3))

_PENDING_DISAMBIGUATION = {}

_FOLLOWUP_MARKERS = (
    "only",
    "just",
    "those",
    "them",
    "ones",
    "premium",
    "standard",
    "active",
    "inactive",
    "how many",
)

_DATA_WORDS = (
    "customer",
    "customers",
    "subscriber",
    "subscribers",
    "payment",
    "payments",
    "invoice",
    "invoices",
    "complaint",
    "complaints",
    "collection",
    "revenue",
    "dashboard",
)

# Pronouns that should be replaced with the previous turn's customer name
_PRONOUNS = (
    "her", "him", "them", "they", "their", "theirs",
    "she", "he", "his", "hers",
)

# Phrases that strongly suggest "this is a follow-up to the previous turn"
_FOLLOWUP_PHRASES = (
    "give her",
    "give him",
    "give them",
    "show her",
    "show him",
    "show them",
    "find her",
    "find him",
    "find them",
    "get her",
    "get him",
    "get them",
    "her details",
    "him details",
    "their details",
    "his details",
    "her profile",
    "his profile",
    "their profile",
    "more about her",
    "more about him",
    "more about them",
    "about her",
    "about him",
    "about them",
    "for her",
    "for him",
    "for them",
    "her number",
    "his number",
    "their number",
    "her phone",
    "his phone",
    "their phone",
    "her email",
    "his email",
    "their email",
)


# Status filter phrases (used when filtering from cache)
_STATUS_FILTERS = {
    "active", "inactive", "pending", "paid", "unpaid", "open", "closed",
    "suspended", "terminated", "expired", "archived", "archive",
    "overdue", "partially paid", "failed", "cancelled", "completed",
}


def _extract_name_from_payload(payload: dict | None) -> str | None:
    """Try to recover a customer name from the previous response payload."""
    if not payload:
        return None
    dis = payload.get("disambiguation")
    if isinstance(dis, dict) and dis.get("name"):
        return str(dis["name"]).strip()
    title = str(payload.get("report_title") or "")
    m = re.search(r"-\s*([^-]{1,80})$", title)
    if m:
        candidate = m.group(1).strip()
        if candidate:
            return candidate
    for key in ("narrative", "summary"):
        text = str(payload.get(key) or "")
        m = re.search(r"\*\*([^*]{1,80}?)\*\*", text)
        if m:
            candidate = m.group(1).strip()
            if candidate and not candidate.lower().startswith(
                ("sensitive", "open", "pending", "active", "inactive", "no matching")
            ):
                return candidate
    return None


def _previous_customer_name(session_id: str) -> str | None:
    turns = _SESSION_TURNS.get(str(session_id))
    if not turns:
        return None
    for turn in reversed(list(turns)):
        candidate = _extract_name_from_payload(turn.get("payload") or {})
        if candidate:
            return candidate
    return None


# ------------------------------------------------------------
# RESULT CACHE — filter from the last query's rows when possible
# ------------------------------------------------------------

def remember_result(
    session_id: str,
    *,
    table: str,
    columns: list[str],
    rows: list[list[Any]],
    user_query: str,
) -> None:
    """Store the latest result rows so follow-up questions can filter locally."""
    _SESSION_RESULT_CACHE[str(session_id)].append(
        {
            "table": table,
            "columns": list(columns or []),
            "rows": [list(r) for r in (rows or [])],
            "user_query": user_query,
        }
    )


def _column_index(columns: list[str], *candidates: str) -> int | None:
    lower = [c.lower() for c in columns]
    for cand in candidates:
        if cand.lower() in lower:
            return lower.index(cand.lower())
    return None


def _row_matches(row: list, name: str) -> bool:
    name_l = name.lower().strip()
    if not name_l:
        return False
    for value in row:
        if value is None:
            continue
        s = str(value).lower()
        if s == name_l or name_l in s:
            return True
    return False


def try_filter_from_cache(session_id: str, user_query: str) -> dict | None:
    """
    If the user's follow-up is clearly a filter on the previous query's
    cached result (e.g. "only active ones", "show me John Doe's details"),
    return the filtered rows/columns/table directly without hitting the DB.

    Returns None if the cache can't satisfy the request.
    """
    cache_q = _SESSION_RESULT_CACHE.get(str(session_id))
    if not cache_q:
        return None
    snapshot = cache_q[-1]
    rows = snapshot["rows"]
    columns = snapshot["columns"]
    table = snapshot["table"]
    if not rows or not columns:
        return None

    q = user_query.lower().strip()

    # 1) Status filter: "only active", "inactive ones", "pending payments"
    status_idx = _column_index(columns, "status", "payment_status")
    if status_idx is not None:
        for status in _STATUS_FILTERS:
            # Match "active ones", "only active", "show pending", etc.
            if re.search(r"\b" + re.escape(status) + r"\b", q):
                filtered = []
                for r in rows:
                    value = r[status_idx] if status_idx < len(r) else None
                    if value is not None and str(value).strip().lower() == status:
                        filtered.append(r)
                # If we have any match, return; if we matched nothing, the user
                # might mean a different filter, so fall through to name match
                if filtered:
                    return {
                        "table": table,
                        "columns": columns,
                        "rows": filtered,
                        "matched_by": f"status={status}",
                    }

    # 2) Name filter: "John Doe", "show me John", "give John Doe's details"
    # Extract candidate name from the query (skip known stop words)
    stop_words = {
        "show", "me", "give", "find", "get", "display", "fetch", "search",
        "the", "a", "an", "of", "for", "to", "with", "details", "detail",
        "info", "information", "profile", "customer", "customers", "subscriber",
        "subscribers", "user", "users", "his", "her", "him", "their", "them",
        "this", "that", "those", "these", "only", "just", "and", "or", "from",
        "in", "on", "please", "pls", "need", "want", "would", "like",
    }
    # Try to pull a name token sequence
    name_patterns = [
        r"(?:named|called|for|about|of)\s+([A-Za-z][A-Za-z0-9' .\-]{1,60})",
        r"\b([A-Z][A-Za-z0-9' \-]{1,60})\b",  # any Capitalized phrase
    ]
    candidate_name = None
    for pat in name_patterns:
        m = re.search(pat, user_query)
        if m:
            text = m.group(1).strip(" .'\"-")
            # Filter to alpha-heavy tokens, drop stop words
            tokens = [t for t in re.split(r"\s+", text) if t and t.lower() not in stop_words]
            if tokens and len(" ".join(tokens)) >= 2:
                candidate_name = " ".join(tokens)
                break

    if candidate_name:
        # Build a list of searchable strings per row:
        #   1) each cell on its own (substring match)
        #   2) a concatenation of the name-like columns joined with spaces
        #      so "Princy 4 va4" can match first_name="Princy" + last_name="4 va4"
        name_col_pairs = (
            ("first_name", "last_name"),
            ("name",),
            ("customer_name",),
            ("full_name",),
        )
        candidate_l = candidate_name.lower()

        matches = []
        for r in rows:
            if not r:
                continue
            cell_strings = [str(v) for v in r if v is not None]
            # Per-cell substring match
            if any(candidate_l in s.lower() for s in cell_strings):
                matches.append(r)
                continue
            # Concatenated name-like match (e.g. first_name + ' ' + last_name)
            for combo in name_col_pairs:
                idxs = [_column_index(columns, c) for c in combo]
                idxs = [i for i in idxs if i is not None]
                if not idxs:
                    continue
                values = [str(r[i]) for i in idxs if i < len(r) and r[i] is not None]
                joined = " ".join(values).strip()
                if joined and candidate_l in joined.lower():
                    matches.append(r)
                    break
        if matches:
            return {
                "table": table,
                "columns": columns,
                "rows": matches,
                "matched_by": f"name~{candidate_name}",
            }


    # 3) Same prompt repeated — return the cached result as-is
    prev_q = (snapshot.get("user_query") or "").lower().strip()
    if prev_q and prev_q == q:
        return {
            "table": table,
            "columns": columns,
            "rows": rows,
            "matched_by": "repeat",
        }

    return None


def remember_turn(session_id: str, user_query: str, effective_query: str, payload: dict) -> None:
    session_key = str(session_id)
    _SESSION_TURNS[session_key].append(
        {
            "user_query": user_query,
            "effective_query": effective_query,
            "intent": payload.get("intent"),
            "service_used": payload.get("service_used") or payload.get("method"),
            "payload": payload,
        }
    )
    if payload.get("needs_disambiguation") and payload.get("disambiguation"):
        _PENDING_DISAMBIGUATION[session_key] = payload["disambiguation"]
    elif not payload.get("needs_disambiguation"):
        _PENDING_DISAMBIGUATION.pop(session_key, None)


def get_recent_context(session_id: str) -> dict | None:
    turns = _SESSION_TURNS.get(str(session_id))
    if not turns:
        return None
    return turns[-1]


def get_pending_disambiguation(session_id: str) -> dict | None:
    return _PENDING_DISAMBIGUATION.get(str(session_id))


def clear_pending_disambiguation(session_id: str) -> None:
    _PENDING_DISAMBIGUATION.pop(str(session_id), None)


def clear_session(session_id: str) -> None:
    """Drop all cached state for a session (turns, results, disambiguation)."""
    key = str(session_id)
    _SESSION_TURNS.pop(key, None)
    _SESSION_RESULT_CACHE.pop(key, None)
    _PENDING_DISAMBIGUATION.pop(key, None)


def resolve_followup_query(session_id: str, user_query: str) -> tuple[str, bool]:
    """
    Returns (effective_query, used_memory).

    - Short chip-like follow-ups ("only", "just", "those", "active") get appended to the previous query.
    - Pronoun follow-ups ("give her details", "show him more") get the pronoun replaced with
      the previous turn's customer name so the AI/SQL understands the referent.
    """
    q = user_query.lower().strip()
    previous = get_recent_context(session_id)
    if not previous:
        return user_query, False

    has_data_word = any(word in q for word in _DATA_WORDS)
    looks_like_followup = any(marker in q for marker in _FOLLOWUP_MARKERS)
    is_short_question = len(q.split()) <= 4 and re.search(r"\b(how many|count|total)\b", q)

    if (looks_like_followup or is_short_question) and not has_data_word:
        return f"{previous['effective_query']} {user_query}", True

    contains_pronoun = any(re.search(r"\b" + p + r"\b", q) for p in _PRONOUNS)
    contains_followup_phrase = any(phrase in q for phrase in _FOLLOWUP_PHRASES)

    if contains_pronoun or contains_followup_phrase:
        prev_name = _previous_customer_name(session_id)
        if not prev_name:
            return user_query, False

        enriched = user_query
        for pronoun in sorted(_PRONOUNS, key=len, reverse=True):
            pattern = r"\b" + re.escape(pronoun) + r"\b"
            enriched = re.sub(pattern, prev_name, enriched, flags=re.IGNORECASE)
        return enriched, True

    return user_query, False
