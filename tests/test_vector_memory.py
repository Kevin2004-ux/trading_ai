from memory.vector_memory import (
    build_memory_metadata,
    build_memory_text,
    find_similar_setups,
    get_memory_config,
    search_memory,
    store_memory_item,
)


class FakeMemoryIndex:
    def __init__(self):
        self.vectors = []

    def upsert(self, vectors, namespace=None):
        self.vectors.extend(vectors)

    def query(self, vector, top_k=5, namespace=None, filter=None, include_metadata=True):
        matches = []
        for vector_item in self.vectors[:top_k]:
            if isinstance(vector_item, dict):
                matches.append(
                    {
                        "id": vector_item["id"],
                        "score": 0.91,
                        "metadata": vector_item.get("metadata", {}),
                    }
                )
        return {"matches": matches}


def _trade_decision() -> dict:
    return {
        "ticker": "AAPL",
        "decision": "recommend",
        "confidence_label": "high",
        "thesis": "AAPL passed objective momentum breakout constraints.",
        "invalidation": "Invalid below 112.50.",
        "risks": ["Market regime may weaken."],
        "research_conviction": {"label": "high", "score": 82.0},
        "source_candidate": {
            "ticker": "AAPL",
            "asset_type": "stock",
            "setup_type": "momentum_breakout",
            "scan_profile": "momentum_breakout",
        },
    }


def _research_brief() -> dict:
    return {
        "ticker": "AAPL",
        "research_summary": "AAPL research brief summary.",
        "bull_case": {"points": ["Price is above key moving averages."]},
        "bear_case": {"points": ["Market data can become stale."]},
        "key_risks": ["Earnings risk."],
        "evidence_table": [{"category": "technical", "claim": "Setup passed", "source": "system"}],
        "research_conviction": {"label": "medium", "score": 67.0},
        "data_quality": {"missing_sections": [], "stale_data_flags": []},
    }


def test_get_memory_config_handles_missing_pinecone_cleanly(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    monkeypatch.delenv("PINECONE_INDEX_NAME", raising=False)
    monkeypatch.delenv("PINECONE_NAMESPACE", raising=False)

    config = get_memory_config()

    assert config["pinecone_index_name"] == "trading-ai-memory"
    assert config["namespace"] == "trading_ai"
    assert config["pinecone_configured"] is False
    assert config["embedding_configured"] is False


def test_build_memory_text_for_trade_decision_is_searchable():
    text = build_memory_text(_trade_decision(), "trade_decision")

    assert "AAPL" in text
    assert "momentum_breakout" in text
    assert "Invalid below" in text
    assert "Market regime" in text


def test_build_memory_text_for_research_brief_is_searchable():
    text = build_memory_text(_research_brief(), "research_brief")

    assert "AAPL research brief summary" in text
    assert "Price is above" in text
    assert "Setup passed" in text
    assert "medium" in text


def test_build_memory_metadata_includes_core_fields():
    metadata = build_memory_metadata(_trade_decision(), "trade_decision", {"source_db_path": "test.db"})

    assert metadata["ticker"] == "AAPL"
    assert metadata["item_type"] == "trade_decision"
    assert metadata["setup_type"] == "momentum_breakout"
    assert metadata["confidence_label"] == "high"
    assert metadata["source_db_path"] == "test.db"


def test_store_memory_item_returns_unavailable_when_provider_missing(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    result = store_memory_item(_trade_decision(), "trade_decision")

    assert result["ok"] is False
    assert result["source"] == "unavailable"
    assert result["metadata"]["ticker"] == "AAPL"
    assert result["error"]


def test_search_memory_returns_unavailable_when_provider_missing(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    result = search_memory("AAPL breakout")

    assert result["ok"] is False
    assert result["source"] == "unavailable"
    assert result["matches"] == []
    assert result["error"]


def test_mocked_store_and_search_return_expected_schema():
    fake_index = FakeMemoryIndex()
    config = {"pinecone_index": fake_index, "embedding_provider": "mock"}

    stored = store_memory_item(_trade_decision(), "trade_decision", config=config)
    searched = search_memory("AAPL momentum breakout", config=config)

    assert stored["ok"] is True
    assert stored["source"] == "mock"
    assert stored["memory_id"]
    assert searched["ok"] is True
    assert searched["source"] == "mock"
    assert searched["matches"][0]["metadata"]["ticker"] == "AAPL"
    assert searched["matches"][0]["text"]


def test_find_similar_setups_returns_qualitative_context():
    fake_index = FakeMemoryIndex()
    config = {"pinecone_index": fake_index, "embedding_provider": "mock"}
    store_memory_item(_trade_decision(), "trade_decision", config=config)

    result = find_similar_setups(_trade_decision(), config=config)

    assert result["ok"] is True
    assert result["label"] == "qualitative_context_only"
    assert result["matches"]
    assert "qualitative context" in result["warnings"][0]
