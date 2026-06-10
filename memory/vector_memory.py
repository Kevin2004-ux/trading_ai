from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


SUPPORTED_ITEM_TYPES = {
    "trade_decision",
    "research_brief",
    "post_trade_review",
    "catalyst_summary",
    "option_mispricing",
    "manual_note",
}
DEFAULT_INDEX_NAME = "trading-ai-memory"
DEFAULT_NAMESPACE = "trading_ai"
LEGACY_INDEX_NAMES = {"trading-patterns", "feature-vector-library"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return "; ".join(_safe_text(item) for item in value if _safe_text(item))
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_safe_text(item)}" for key, item in value.items() if _safe_text(item))
    return str(value).strip()


def _nested(payload: dict, *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _metadata_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return str(value)


def _mock_embedding(text: str, dimensions: int = 64) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    while len(values) < dimensions:
        for byte in digest:
            values.append((byte / 255.0) * 2.0 - 1.0)
            if len(values) >= dimensions:
                break
        digest = hashlib.sha256(digest).digest()
    return values


def get_memory_config(config: dict | None = None) -> dict:
    supplied = config if isinstance(config, dict) else {}
    explicit_index = supplied.get("pinecone_index_name") or supplied.get("index_name") or os.getenv("PINECONE_INDEX_NAME")
    index_name = explicit_index or DEFAULT_INDEX_NAME
    warnings: list[str] = []
    if index_name in LEGACY_INDEX_NAMES and not explicit_index:
        warnings.append(f"Ignoring legacy Pinecone index name '{index_name}' because it was not explicitly configured.")
        index_name = DEFAULT_INDEX_NAME

    api_key = supplied.get("pinecone_api_key") or os.getenv("PINECONE_API_KEY")
    namespace = supplied.get("namespace") or os.getenv("PINECONE_NAMESPACE") or DEFAULT_NAMESPACE
    embedding_provider = supplied.get("embedding_provider") or os.getenv("MEMORY_EMBEDDING_PROVIDER") or "unavailable"
    embedding_function = supplied.get("embedding_function")
    pinecone_index = supplied.get("pinecone_index")

    return {
        "pinecone_api_key": api_key,
        "pinecone_index_name": index_name,
        "namespace": namespace,
        "embedding_provider": embedding_provider,
        "embedding_function": embedding_function,
        "pinecone_index": pinecone_index,
        "pinecone_configured": bool(api_key and index_name),
        "embedding_configured": callable(embedding_function) or str(embedding_provider).lower() == "mock",
        "warnings": warnings,
    }


def build_memory_text(item: dict, item_type: str) -> str:
    if not isinstance(item, dict):
        return ""

    normalized_type = str(item_type or "").strip().lower()
    if normalized_type == "trade_decision":
        source_candidate = item.get("source_candidate") if isinstance(item.get("source_candidate"), dict) else {}
        market_regime = item.get("market_regime_context") or source_candidate.get("market_regime_context") or {}
        relative_strength = item.get("relative_strength_context") or source_candidate.get("relative_strength_context") or {}
        option_context = item.get("preferred_option_mispricing_context") or item.get("option_mispricing_context") or {}
        parts = [
            f"Ticker: {_normalize_ticker(item.get('ticker') or source_candidate.get('ticker'))}",
            f"Decision: {_safe_text(item.get('decision'))}",
            f"Setup type: {_safe_text(source_candidate.get('setup_type') or item.get('setup_type'))}",
            f"Thesis: {_safe_text(item.get('thesis'))}",
            f"Invalidation: {_safe_text(item.get('invalidation'))}",
            f"Risks: {_safe_text(item.get('risks'))}",
            f"Market regime: {_safe_text(market_regime.get('regime') if isinstance(market_regime, dict) else market_regime)}",
            f"Relative strength: {_safe_text(relative_strength.get('relative_strength_label') if isinstance(relative_strength, dict) else relative_strength)}",
            f"Research conviction: {_safe_text(item.get('research_conviction'))}",
            f"Option context: {_safe_text(option_context)}",
            f"Outcome: {_safe_text(item.get('outcome'))}",
        ]
        return "\n".join(part for part in parts if not part.endswith(": "))

    if normalized_type == "research_brief":
        evidence_rows = item.get("evidence_table", [])
        evidence_summary = []
        if isinstance(evidence_rows, list):
            evidence_summary = [
                f"{row.get('category')}: {row.get('claim')} ({row.get('source')})"
                for row in evidence_rows[:8]
                if isinstance(row, dict)
            ]
        data_quality = item.get("data_quality", {}) if isinstance(item.get("data_quality"), dict) else {}
        parts = [
            f"Ticker: {_normalize_ticker(item.get('ticker'))}",
            f"Research summary: {_safe_text(item.get('research_summary'))}",
            f"Bull case: {_safe_text(_nested(item, 'bull_case', 'points'))}",
            f"Bear case: {_safe_text(_nested(item, 'bear_case', 'points'))}",
            f"Key risks: {_safe_text(item.get('key_risks'))}",
            f"Evidence: {_safe_text(evidence_summary)}",
            f"Research conviction: {_safe_text(item.get('research_conviction'))}",
            f"Data quality warnings: {_safe_text(data_quality.get('missing_sections'))} {_safe_text(data_quality.get('stale_data_flags'))}",
        ]
        return "\n".join(part for part in parts if not part.endswith(": "))

    if normalized_type == "manual_note":
        parts = [
            f"Ticker: {_normalize_ticker(item.get('ticker'))}",
            f"Note: {_safe_text(item.get('note') or item.get('text') or item.get('summary'))}",
            f"Tags: {_safe_text(item.get('tags'))}",
        ]
        return "\n".join(part for part in parts if not part.endswith(": "))

    return _safe_text(item)


def build_memory_metadata(
    item: dict,
    item_type: str,
    extra_metadata: dict | None = None,
) -> dict:
    normalized_type = str(item_type or "").strip().lower()
    source_candidate = item.get("source_candidate") if isinstance(item, dict) and isinstance(item.get("source_candidate"), dict) else {}
    research_conviction = item.get("research_conviction") if isinstance(item, dict) and isinstance(item.get("research_conviction"), dict) else {}

    metadata = {
        "ticker": _normalize_ticker(item.get("ticker") or source_candidate.get("ticker")) if isinstance(item, dict) else "",
        "item_type": normalized_type,
        "created_at": _now_iso(),
        "asset_type": item.get("asset_type") or source_candidate.get("asset_type") if isinstance(item, dict) else None,
        "setup_type": item.get("setup_type") or source_candidate.get("setup_type") if isinstance(item, dict) else None,
        "scan_profile": item.get("scan_profile") or source_candidate.get("scan_profile") or source_candidate.get("selected_profile") if isinstance(item, dict) else None,
        "decision": item.get("decision") if isinstance(item, dict) else None,
        "outcome": item.get("outcome") if isinstance(item, dict) else None,
        "source_db_path": None,
        "tags": _as_list(item.get("tags")) if isinstance(item, dict) else [],
        "confidence_label": item.get("confidence_label") or source_candidate.get("confidence_label") if isinstance(item, dict) else None,
        "research_conviction_label": research_conviction.get("label"),
    }
    if isinstance(extra_metadata, dict):
        metadata.update(extra_metadata)
    return {key: _metadata_value(value) for key, value in metadata.items() if value is not None}


def _embed_text(text: str, memory_config: dict) -> tuple[list[float] | None, str | None]:
    embedding_function = memory_config.get("embedding_function")
    if callable(embedding_function):
        try:
            return list(embedding_function(text)), None
        except Exception as exc:
            return None, f"Embedding provider failed: {exc}"
    if str(memory_config.get("embedding_provider", "")).lower() == "mock":
        return _mock_embedding(text), None
    return None, "No embedding provider is configured."


def _get_pinecone_index(memory_config: dict) -> tuple[Any | None, str, str | None]:
    if memory_config.get("pinecone_index") is not None:
        return memory_config["pinecone_index"], "mock", None
    if not memory_config.get("pinecone_configured"):
        return None, "unavailable", "Pinecone is not configured."
    try:
        from pinecone import Pinecone
    except Exception as exc:
        return None, "unavailable", f"Pinecone client is unavailable: {exc}"
    try:
        client = Pinecone(api_key=memory_config["pinecone_api_key"])
        return client.Index(memory_config["pinecone_index_name"]), "pinecone", None
    except Exception as exc:
        return None, "unavailable", f"Failed to initialize Pinecone index: {exc}"


def store_memory_item(
    item: dict,
    item_type: str,
    namespace: str = DEFAULT_NAMESPACE,
    memory_id: str | None = None,
    extra_metadata: dict | None = None,
    config: dict | None = None,
) -> dict:
    normalized_type = str(item_type or "").strip().lower()
    if normalized_type not in SUPPORTED_ITEM_TYPES:
        return {
            "ok": False,
            "source": "unavailable",
            "memory_id": memory_id,
            "namespace": namespace,
            "item_type": normalized_type,
            "metadata": {},
            "error": f"Unsupported memory item_type: {item_type}",
        }

    memory_config = get_memory_config(config)
    resolved_namespace = namespace or memory_config["namespace"]
    text = build_memory_text(item, normalized_type)
    metadata = build_memory_metadata(
        item,
        normalized_type,
        extra_metadata={**(extra_metadata or {}), "text": text},
    )
    resolved_id = memory_id or f"{normalized_type}:{metadata.get('ticker', 'UNKNOWN')}:{uuid4().hex}"

    vector, embedding_error = _embed_text(text, memory_config)
    if vector is None:
        return {
            "ok": False,
            "source": "unavailable",
            "memory_id": resolved_id,
            "namespace": resolved_namespace,
            "item_type": normalized_type,
            "metadata": metadata,
            "error": embedding_error,
        }

    index, source, index_error = _get_pinecone_index(memory_config)
    if index is None:
        return {
            "ok": False,
            "source": source,
            "memory_id": resolved_id,
            "namespace": resolved_namespace,
            "item_type": normalized_type,
            "metadata": metadata,
            "error": index_error,
        }

    try:
        index.upsert(
            vectors=[{"id": resolved_id, "values": vector, "metadata": metadata}],
            namespace=resolved_namespace,
        )
    except TypeError:
        index.upsert(vectors=[(resolved_id, vector, metadata)], namespace=resolved_namespace)
    except Exception as exc:
        return {
            "ok": False,
            "source": source,
            "memory_id": resolved_id,
            "namespace": resolved_namespace,
            "item_type": normalized_type,
            "metadata": metadata,
            "error": f"Failed to store memory item: {exc}",
        }

    return {
        "ok": True,
        "source": source,
        "memory_id": resolved_id,
        "namespace": resolved_namespace,
        "item_type": normalized_type,
        "metadata": metadata,
        "error": None,
    }


def search_memory(
    query: str,
    namespace: str = DEFAULT_NAMESPACE,
    top_k: int = 5,
    filters: dict | None = None,
    config: dict | None = None,
) -> dict:
    memory_config = get_memory_config(config)
    resolved_namespace = namespace or memory_config["namespace"]
    vector, embedding_error = _embed_text(query, memory_config)
    if vector is None:
        return {
            "ok": False,
            "source": "unavailable",
            "query": query,
            "namespace": resolved_namespace,
            "matches": [],
            "error": embedding_error,
        }

    index, source, index_error = _get_pinecone_index(memory_config)
    if index is None:
        return {
            "ok": False,
            "source": source,
            "query": query,
            "namespace": resolved_namespace,
            "matches": [],
            "error": index_error,
        }

    try:
        result = index.query(
            vector=vector,
            top_k=top_k,
            namespace=resolved_namespace,
            filter=filters,
            include_metadata=True,
        )
    except TypeError:
        result = index.query(vector=vector, top_k=top_k, namespace=resolved_namespace, include_metadata=True)
    except Exception as exc:
        return {
            "ok": False,
            "source": source,
            "query": query,
            "namespace": resolved_namespace,
            "matches": [],
            "error": f"Failed to search memory: {exc}",
        }

    raw_matches = result.get("matches", []) if isinstance(result, dict) else getattr(result, "matches", [])
    matches = []
    for match in raw_matches:
        metadata = match.get("metadata", {}) if isinstance(match, dict) else getattr(match, "metadata", {})
        matches.append(
            {
                "memory_id": match.get("id") if isinstance(match, dict) else getattr(match, "id", None),
                "score": match.get("score") if isinstance(match, dict) else getattr(match, "score", None),
                "metadata": metadata,
                "text": metadata.get("text", "") if isinstance(metadata, dict) else "",
            }
        )

    return {
        "ok": True,
        "source": source,
        "query": query,
        "namespace": resolved_namespace,
        "matches": matches,
        "error": None,
    }


def store_trade_decision_memory(
    trade_decision: dict,
    db_path: str = "strategy_library.db",
    config: dict | None = None,
) -> dict:
    return store_memory_item(
        trade_decision,
        item_type="trade_decision",
        namespace=get_memory_config(config)["namespace"],
        extra_metadata={"source_db_path": db_path},
        config=config,
    )


def store_research_brief_memory(
    research_brief: dict,
    db_path: str = "strategy_library.db",
    config: dict | None = None,
) -> dict:
    return store_memory_item(
        research_brief,
        item_type="research_brief",
        namespace=get_memory_config(config)["namespace"],
        extra_metadata={"source_db_path": db_path},
        config=config,
    )


def find_similar_setups(
    candidate_or_trade: dict,
    top_k: int = 5,
    config: dict | None = None,
) -> dict:
    query = build_memory_text(candidate_or_trade, "trade_decision")
    if not query:
        query = _safe_text(candidate_or_trade)
    result = search_memory(
        query=query,
        namespace=get_memory_config(config)["namespace"],
        top_k=top_k,
        filters={"item_type": {"$in": ["trade_decision", "research_brief"]}},
        config=config,
    )
    warnings = ["Semantic memory is qualitative context only and does not replace SQLite performance statistics."]
    if not result.get("ok"):
        warnings.append(result.get("error", "Semantic memory is unavailable."))
    return {
        "ok": bool(result.get("ok")),
        "source": result.get("source", "unavailable"),
        "query": query,
        "matches": result.get("matches", []),
        "warnings": warnings,
        "label": "qualitative_context_only",
        "error": None if result.get("ok") else result.get("error"),
    }
