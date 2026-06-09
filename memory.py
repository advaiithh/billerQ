import re
from collections import defaultdict, deque

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

_SESSION_TURNS: dict[str, deque] = defaultdict(lambda: deque(maxlen=8))
_PENDING_DISAMBIGUATION: dict[str, dict] = {}

# Words that indicate a follow-up filter on the previous result set
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
    "filter",
    "among",
    "from those",
    "of those",
    "of them",
    "sort",
    "order",
    "by amount",
    "by date",
)

# Pronouns that refer back to an entity named in a prior turn
_PRONOUN_REFS = (
    "he",
    "she",
    "her",
    "him",
    "his",
    "they",
    "their",
    "them",
    "it",
    "this person",
    "that person",
    "this customer",
    "that customer",
    "the same",
    "same person",
    "same customer",
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


def _extract_entity_name_from_payload(payload: dict) -> str | None:
    """Pull the last mentioned customer/entity name from a previous turn's payload."""
    # From customer details service
    narrative = payload.get("narrative") or ""
    # Look for bold names like **John Doe**
    bold_match = re.search(r"\*\*([A-Za-z][A-Za-z .'\-]{1,50})\*\*", narrative)
    if bold_match:
        candidate = bold_match.group(1).strip()
        # Skip generic phrases
        if not re.match(r"^\d+\b|^(found|no |customer #|showing|there are)", candidate, re.IGNORECASE):
            return candidate

    summary = payload.get("summary") or ""
    # "Customer details found for John Doe"
    name_in_summary = re.search(r"(?:details? (?:found )?for|customer:)\s+([A-Za-z][A-Za-z .'\-]{1,50})", summary, re.IGNORECASE)
    if name_in_summary:
        return name_in_summary.group(1).strip()

    return None


def _extract_entity_name_from_query(query: str) -> str | None:
    """Pull a customer name from the original user query in a prior turn."""
    patterns = [
        r"\b(?:details?|info|profile)\s+(?:of|for)\s+([A-Za-z][A-Za-z .'\-]{2,50})",
        r"\b(?:show|get|find|give)\s+(?:me\s+)?([A-Za-z][A-Za-z .'\-]{2,50})(?:'s)?\s+(?:details?|info|profile)",
        r"\b([A-Za-z][A-Za-z .'\-]{2,50})(?:'s)?\s+(?:details?|info|profile|payment|invoice)",
    ]
    for pattern in patterns:
        m = re.search(pattern, query, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def remember_turn(session_id: str, user_query: str, effective_query: str, payload: dict) -> None:
    session_key = str(session_id)

    # Extract and store the entity name referenced in this turn
    entity_name = (
        _extract_entity_name_from_payload(payload)
        or _extract_entity_name_from_query(user_query)
    )

    _SESSION_TURNS[session_key].append(
        {
            "user_query": user_query,
            "effective_query": effective_query,
            "intent": payload.get("intent"),
            "service_used": payload.get("service_used") or payload.get("method"),
            "payload": payload,
            "entity_name": entity_name,
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


def get_last_entity_name(session_id: str) -> str | None:
    """Return the most recently mentioned customer/entity name across all recent turns."""
    turns = _SESSION_TURNS.get(str(session_id))
    if not turns:
        return None
    for turn in reversed(list(turns)):
        name = turn.get("entity_name")
        if name:
            return name
    return None


def get_conversation_context(session_id: str, max_turns: int = 4) -> list[dict]:
    """Return the last N turns as a context list for prompt injection."""
    turns = _SESSION_TURNS.get(str(session_id))
    if not turns:
        return []
    result = []
    for turn in list(turns)[-max_turns:]:
        result.append({
            "user": turn["user_query"],
            "entity": turn.get("entity_name"),
            "intent": turn.get("intent"),
        })
    return result


def get_pending_disambiguation(session_id: str) -> dict | None:
    return _PENDING_DISAMBIGUATION.get(str(session_id))


def clear_pending_disambiguation(session_id: str) -> None:
    _PENDING_DISAMBIGUATION.pop(str(session_id), None)


def resolve_followup_query(session_id: str, user_query: str) -> tuple[str, bool]:
    """
    Resolves pronouns and short follow-ups by injecting prior context into the query.
    Returns (resolved_query, was_modified).
    """
    q = user_query.lower().strip()
    previous = get_recent_context(session_id)
    if not previous:
        return user_query, False

    # --- Pronoun resolution: "her", "him", "she", "he", "same customer", etc. ---
    has_pronoun = any(
        re.search(r"\b" + re.escape(p) + r"\b", q)
        for p in _PRONOUN_REFS
    )

    if has_pronoun:
        entity_name = get_last_entity_name(session_id)
        if entity_name:
            # Replace the pronoun with the actual name
            resolved = user_query
            for p in _PRONOUN_REFS:
                resolved = re.sub(
                    r"\b" + re.escape(p) + r"\b",
                    entity_name,
                    resolved,
                    flags=re.IGNORECASE,
                )
            # If the resolved query mentions a data action, keep it as-is
            if resolved.lower() != user_query.lower():
                return resolved, True

    has_data_word = any(word in q for word in _DATA_WORDS)
    looks_like_followup = any(
        re.search(r"\b" + re.escape(marker) + r"\b", q)
        for marker in _FOLLOWUP_MARKERS
    )
    is_short_question = len(q.split()) <= 4 and re.search(r"\b(how many|count|total)\b", q)

    if (looks_like_followup or is_short_question) and not has_data_word:
        return f"{previous['effective_query']} {user_query}", True

    return user_query, False
