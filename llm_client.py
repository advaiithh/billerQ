"""Provider-agnostic LLM client for BillerQ.

A single ``generate()`` entry point hides whether the request is served by a
local Ollama model or Amazon Bedrock, so the rest of the codebase never needs
to know which provider/model is in use. Switch providers with the
``BILLERQ_LLM_PROVIDER`` env var (see ``config.py``).

Design goals:
- Tiered models: a cheap "fast" tier for high-volume intent/entity/summary
  work, and a stronger "smart" tier reserved for SQL generation and reports.
- Cost visibility: Bedrock token usage is logged per call.
- Resilience: any failure returns ``None`` so callers can fall back to rules,
  matching the existing behaviour of the old Ollama helpers.
"""

import logging

import requests

import config

logger = logging.getLogger("billerq.llm")

FAST = "fast"
SMART = "smart"

# Cached Bedrock client (boto3 clients are thread-safe and meant to be reused).
_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        import boto3  # imported lazily so Ollama-only setups need no boto3
        from botocore.config import Config as BotoConfig

        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=config.AWS_REGION,
            config=BotoConfig(
                read_timeout=config.BEDROCK_TIMEOUT_SEC,
                connect_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
    return _bedrock_client


def _bedrock_model_id(tier: str) -> str:
    return config.BEDROCK_MODEL_SMART if tier == SMART else config.BEDROCK_MODEL_FAST


def _generate_bedrock(
    prompt: str,
    tier: str,
    system: str | None,
    max_tokens: int,
    temperature: float,
) -> str | None:
    """Call Bedrock via the Converse API (one interface for all model families)."""
    try:
        client = _get_bedrock_client()
        kwargs = {
            "modelId": _bedrock_model_id(tier),
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            kwargs["system"] = [{"text": system}]

        resp = client.converse(**kwargs)

        usage = resp.get("usage", {})
        logger.info(
            "bedrock converse model=%s tier=%s in=%s out=%s",
            kwargs["modelId"],
            tier,
            usage.get("inputTokens"),
            usage.get("outputTokens"),
        )

        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        text = "".join(b.get("text", "") for b in blocks).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - degrade gracefully to caller fallback
        logger.warning("Bedrock call failed (%s); caller will fall back.", exc)
        return None


def _generate_ollama(
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> str | None:
    """Call a local Ollama model (preserves the original BillerQ behaviour)."""
    try:
        response = requests.post(
            config.OLLAMA_URL,
            json={
                "model": config.OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
            timeout=config.OLLAMA_TIMEOUT_SEC,
        )
        response.raise_for_status()
        text = response.json().get("response", "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001 - degrade gracefully to caller fallback
        logger.warning("Ollama call failed (%s); caller will fall back.", exc)
        return None


def generate(
    prompt: str,
    *,
    tier: str = FAST,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> str | None:
    """Generate a completion from the configured provider.

    Args:
        prompt: The user prompt.
        tier: ``"fast"`` (cheap, high volume) or ``"smart"`` (SQL/reports).
            Only affects Bedrock model selection; ignored for Ollama.
        system: Optional system instruction (Bedrock only).
        max_tokens: Max tokens to generate.
        temperature: Sampling temperature.

    Returns:
        The model's text output, or ``None`` if the call failed.
    """
    if config.LLM_PROVIDER == "bedrock":
        return _generate_bedrock(prompt, tier, system, max_tokens, temperature)
    return _generate_ollama(prompt, max_tokens, temperature)
