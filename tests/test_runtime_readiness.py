from db.schema_manager import apply_pending_migrations
from config.runtime_readiness import check_runtime_readiness


def _base(tmp_path, **overrides):
    config = {
        "DATABASE_PATH": str(tmp_path / "readiness.db"),
        "MARKET_DATA_PROVIDER": "ibkr",
        "OPTIONS_DATA_PROVIDER": "ibkr",
        "MARKET_DATA_MODE": "paper",
        "IBKR_HOST": "127.0.0.1",
        "IBKR_PORT": "7496",
        "IBKR_CLIENT_ID": "123",
        "IBKR_READ_ONLY": "true",
        "IBKR_TIMEOUT_SECONDS": "10",
        "SCAN_MAX_CONCURRENCY": "5",
        "SCAN_TICKER_TIMEOUT_SECONDS": "15",
        "SCAN_TOTAL_TIMEOUT_SECONDS": "180",
        "IBKR_MAX_CONCURRENT_REQUESTS": "3",
        "IBKR_REQUESTS_PER_SECOND": "2",
        "ALLOW_HISTORICAL_BAR_FALLBACK": "true",
        "ALLOW_LIVE_QUOTE_REQUIRED": "false",
        "ALLOW_OPTIONS_WITHOUT_QUOTES": "false",
        "INCLUDE_OPTIONS": "false",
    }
    config.update(overrides)
    return config


def test_runtime_readiness_without_live_checks_uses_non_mutating_schema_validation(tmp_path):
    config = _base(tmp_path)
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is True
    assert result["live_checks"] is None
    assert result["categories"]["database_ready"]["ok"] is True
    assert result["categories"]["scan_runtime_ready"]["ok"] is True
    assert result["categories"]["scheduler_ready"]["ok"] is True
    assert result["categories"]["alerts_ready"]["ok"] is True
    assert result["categories"]["stress_testing_ready"]["ok"] is True


def test_runtime_readiness_warns_when_database_not_migrated(tmp_path):
    config = _base(tmp_path)
    db_path = tmp_path / "readiness.db"
    db_path.write_text("")

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is False
    assert result["categories"]["database_ready"]["ok"] is False
    assert any("db-migrate" in warning for warning in result["warnings"])


def test_runtime_readiness_include_live_checks_can_be_mocked(monkeypatch, tmp_path):
    config = _base(tmp_path)
    apply_pending_migrations(config["DATABASE_PATH"])

    monkeypatch.setattr(
        "diagnostics.live_dry_run.run_provider_dry_run",
        lambda **kwargs: {"ok": True, "warnings": ["mock live check"], "errors": [], "checks": {}},
    )

    result = check_runtime_readiness(config, include_live_checks=True)

    assert result["ok"] is True
    assert result["live_checks"]["ok"] is True
    assert "mock live check" in result["warnings"]


def test_sec_research_not_blocking_unless_required(tmp_path):
    config = _base(tmp_path, SEC_RESEARCH_ENABLED="true", SEC_USER_AGENT="", SEC_RESEARCH_REQUIRED="false")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is True
    assert result["categories"]["research_ready"]["ok"] is False
    assert result["categories"]["scan_runtime_ready"]["ok"] is True


def test_sec_research_required_blocks_runtime(tmp_path):
    config = _base(tmp_path, SEC_RESEARCH_ENABLED="true", SEC_USER_AGENT="", SEC_RESEARCH_REQUIRED="true")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is False
    assert result["categories"]["research_ready"]["ok"] is False


def test_news_research_required_blocks_runtime(tmp_path):
    config = _base(tmp_path, NEWS_RESEARCH_ENABLED="false", NEWS_RESEARCH_REQUIRED="true")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is False
    assert result["categories"]["research_ready"]["ok"] is False


def test_short_interest_required_blocks_runtime_when_disabled(tmp_path):
    config = _base(tmp_path, SHORT_INTEREST_ENABLED="false", SHORT_INTEREST_REQUIRED="true")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is False
    assert result["categories"]["research_ready"]["ok"] is False


def test_optional_memory_missing_is_ready_with_warnings(tmp_path):
    config = _base(tmp_path, MEMORY_ENABLED="true", MEMORY_REQUIRED="false", PINECONE_API_KEY="", PINECONE_INDEX_NAME="")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is True
    assert result["categories"]["memory_ready"]["ok"] is True
    assert result["categories"]["memory_ready"]["status"] == "ready_with_warnings"


def test_required_memory_missing_blocks_runtime(tmp_path):
    config = _base(tmp_path, MEMORY_ENABLED="true", MEMORY_REQUIRED="true", PINECONE_API_KEY="", PINECONE_INDEX_NAME="")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is False
    assert result["categories"]["memory_ready"]["ok"] is False


def test_stress_testing_disabled_is_reported_without_blocking_scan(tmp_path):
    config = _base(tmp_path, STRESS_TESTING_ENABLED="false")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is True
    assert result["categories"]["stress_testing_ready"]["ok"] is False
    assert result["categories"]["scan_runtime_ready"]["ok"] is True


def test_options_unvalidated_does_not_block_stock_scan_runtime(tmp_path):
    config = _base(tmp_path, INCLUDE_OPTIONS="true", OPTION_QUOTES_VALIDATED="false")
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is True
    assert result["categories"]["scan_runtime_ready"]["ok"] is True
    assert result["categories"]["options_ready"]["ok"] is False
    assert any("option quotes have not been validated" in warning.lower() for warning in result["warnings"])


def test_stock_only_runtime_ignores_globally_enabled_unvalidated_options(tmp_path):
    config = _base(
        tmp_path,
        ENABLE_OPTIONS="true",
        INCLUDE_OPTIONS="false",
        STOCK_ONLY="true",
        OPTION_QUOTES_VALIDATED="false",
    )
    apply_pending_migrations(config["DATABASE_PATH"])

    result = check_runtime_readiness(config, include_live_checks=False)

    assert result["ok"] is True
    assert result["categories"]["scan_runtime_ready"]["ok"] is True
    assert result["categories"]["options_ready"]["ok"] is False
    assert not any("option quotes have not been validated" in error.lower() for error in result["errors"])
