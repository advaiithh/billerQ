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

_SESSION_TURNS = defaultdict(lambda: deque(maxlen=5))
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


def remember_turn(session_id: str, user_query: str, effective_query: str, payload: dict) -> None:
    session_key = str(session_id)
    _SESSION_TURNS[str(session_id)].append(
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


def resolve_followup_query(session_id: str, user_query: str) -> tuple[str, bool]:
    q = user_query.lower().strip()
    previous = get_recent_context(session_id)
    if not previous:
        return user_query, False

    has_data_word = any(word in q for word in _DATA_WORDS)
    looks_like_followup = any(marker in q for marker in _FOLLOWUP_MARKERS)
    is_short_question = len(q.split()) <= 4 and re.search(r"\b(how many|count|total)\b", q)

    if (looks_like_followup or is_short_question) and not has_data_word:
        return f"{previous['effective_query']} {user_query}", True

    return user_query, False
