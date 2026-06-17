"""
BillerQ Business Copilot - Query Logger
========================================
Stores all user queries, intents, responses, services used, and response times.
Purpose: Analytics, Usage Monitoring, Future Fine-Tuning, Cost Optimization.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY LOG ENTRY
# ═══════════════════════════════════════════════════════════════════════════════

class QueryLogEntry:
    """Represents a single query log entry."""

    def __init__(
        self,
        session_id: str,
        user_query: str,
        intent: str,
        response: str,
        service_used: str = "unknown",
        sql_used: Optional[str] = None,
        response_time_ms: float = 0.0,
        company_id: Optional[int] = None,
        user_id: Optional[str] = None,
        token_usage: Optional[dict] = None,
        error: Optional[str] = None,
    ):
        self.session_id = session_id
        self.user_query = user_query
        self.intent = intent
        self.response = response
        self.service_used = service_used
        self.sql_used = sql_used
        self.response_time_ms = response_time_ms
        self.company_id = company_id
        self.user_id = user_id
        self.token_usage = token_usage or {}
        self.error = error
        self.timestamp = datetime.now()

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "user_query": self.user_query,
            "intent": self.intent,
            "response": self.response[:500] if self.response else "",  # Truncate for storage
            "service_used": self.service_used,
            "sql_used": self.sql_used,
            "response_time_ms": self.response_time_ms,
            "company_id": self.company_id,
            "user_id": self.user_id,
            "token_usage": self.token_usage,
            "error": self.error,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# QUERY LOG STORE
# ═══════════════════════════════════════════════════════════════════════════════

class QueryLogStore:
    """
    Stores query logs in memory with periodic flush to disk.
    In production, replace with database-backed store.
    """

    def __init__(self, log_dir: str = "logs/queries", max_memory_logs: int = 1000):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_memory_logs = max_memory_logs
        self._logs: list[dict] = []
        self._flush_counter = 0

    def add_log(self, entry: QueryLogEntry) -> None:
        """Add a log entry and auto-flush if threshold reached."""
        self._logs.append(entry.to_dict())
        self._flush_counter += 1

        if self._flush_counter >= 100:  # Flush every 100 logs
            self.flush()

    def flush(self) -> None:
        """Flush in-memory logs to disk."""
        if not self._logs:
            return

        try:
            today = datetime.now().strftime("%Y-%m-%d")
            log_file = self.log_dir / f"queries-{today}.jsonl"

            with open(log_file, "a", encoding="utf-8") as f:
                for log_entry in self._logs:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            self._logs.clear()
            self._flush_counter = 0
            logger.debug(f"Flushed query logs to {log_file}")
        except Exception as e:
            logger.error(f"Failed to flush query logs: {e}")

    def get_recent_logs(self, limit: int = 50, company_id: Optional[int] = None) -> list[dict]:
        """Get recent log entries, optionally filtered by company_id."""
        filtered = self._logs
        if company_id:
            filtered = [log for log in self._logs if log.get("company_id") == company_id]

        # Also read from today's file if exists
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"queries-{today}.jsonl"
        file_logs = []
        if log_file.exists():
            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entry = json.loads(line)
                            if not company_id or entry.get("company_id") == company_id:
                                file_logs.append(entry)
            except Exception as e:
                logger.error(f"Failed to read query log file: {e}")

        # Merge: in-memory first (most recent), then file logs
        all_logs = filtered + file_logs
        # Sort by timestamp descending
        all_logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return all_logs[:limit]

    def get_usage_stats(self, company_id: Optional[int] = None) -> dict:
        """Get usage statistics, optionally filtered by company_id."""
        all_logs = self.get_recent_logs(limit=10000, company_id=company_id)

        if not all_logs:
            return {
                "total_queries": 0,
                "intent_breakdown": {},
                "service_breakdown": {},
                "avg_response_time_ms": 0,
                "error_count": 0,
            }

        intents = {}
        services = {}
        total_time = 0
        error_count = 0

        for log in all_logs:
            intent = log.get("intent", "unknown")
            intents[intent] = intents.get(intent, 0) + 1

            service = log.get("service_used", "unknown")
            services[service] = services.get(service, 0) + 1

            total_time += log.get("response_time_ms", 0)
            if log.get("error"):
                error_count += 1

        return {
            "total_queries": len(all_logs),
            "intent_breakdown": intents,
            "service_breakdown": services,
            "avg_response_time_ms": round(total_time / len(all_logs), 2) if all_logs else 0,
            "error_count": error_count,
        }

    def get_cost_estimate(self, company_id: Optional[int] = None) -> dict:
        """Estimate cost based on logged queries."""
        all_logs = self.get_recent_logs(limit=10000, company_id=company_id)

        # Approximate costs per 1K tokens (in USD)
        COST_PER_1K_INPUT = 0.003  # ~$0.003 per 1K input tokens
        COST_PER_1K_OUTPUT = 0.015  # ~$0.015 per 1K output tokens

        total_input_tokens = 0
        total_output_tokens = 0
        llm_calls = 0

        for log in all_logs:
            usage = log.get("token_usage", {})
            if usage:
                total_input_tokens += usage.get("input_tokens", 0)
                total_output_tokens += usage.get("output_tokens", 0)
                llm_calls += 1

        input_cost = (total_input_tokens / 1000) * COST_PER_1K_INPUT
        output_cost = (total_output_tokens / 1000) * COST_PER_1K_OUTPUT

        return {
            "total_llm_calls": llm_calls,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "estimated_cost_usd": round(input_cost + output_cost, 6),
            "estimated_cost_inr": round((input_cost + output_cost) * 83, 2),  # Approximate INR rate
        }


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL QUERY LOG STORE INSTANCE
# ═══════════════════════════════════════════════════════════════════════════════

# Singleton instance
_query_log_store: Optional[QueryLogStore] = None


def get_query_log_store(log_dir: str = "logs/queries") -> QueryLogStore:
    """Get or create the global query log store singleton."""
    global _query_log_store
    if _query_log_store is None:
        _query_log_store = QueryLogStore(log_dir=log_dir)
    return _query_log_store


def log_query(entry: QueryLogEntry) -> None:
    """Convenience function to log a query."""
    store = get_query_log_store()
    store.add_log(entry)


async def log_query_async(entry: QueryLogEntry) -> None:
    """Async wrapper for logging."""
    log_query(entry)