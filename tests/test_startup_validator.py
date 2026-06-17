from config.startup_validator import validate_startup_config


def _base(tmp_path, **overrides):
    config = {
        "DATABASE_PATH": str(tmp_path / "startup.db"),
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
        "ENABLE_GEMINI": "false",
        "ENABLE_PINECONE_MEMORY": "false",
        "ENABLE_SEC_RESEARCH": "false",
    }
    config.update(overrides)
    return config


def test_valid_stock_only_config_returns_ready_with_warnings(tmp_path):
    result = validate_startup_config(_base(tmp_path))

    assert result["ok"] is True
    assert result["readiness"] in {"ready", "ready_with_warnings"}
    assert result["safe_to_run_paper_cycle"] is True
    assert result["safe_to_run_options"] is False


def test_missing_database_parent_blocks(tmp_path):
    result = validate_startup_config(_base(tmp_path, DATABASE_PATH=str(tmp_path / "missing" / "db.sqlite")))

    assert result["ok"] is False
    assert any("parent directory" in error for error in result["errors"])


def test_invalid_concurrency_blocks(tmp_path):
    result = validate_startup_config(_base(tmp_path, SCAN_MAX_CONCURRENCY="0"))

    assert result["ok"] is False
    assert any("SCAN_MAX_CONCURRENCY" in error for error in result["errors"])


def test_invalid_timeout_blocks(tmp_path):
    result = validate_startup_config(_base(tmp_path, SCAN_TOTAL_TIMEOUT_SECONDS="-1"))

    assert result["ok"] is False
    assert any("SCAN_TOTAL_TIMEOUT_SECONDS" in error for error in result["errors"])


def test_ibkr_read_only_false_blocks(tmp_path):
    result = validate_startup_config(_base(tmp_path, IBKR_READ_ONLY="false"))

    assert result["ok"] is False
    assert any("IBKR_READ_ONLY" in error for error in result["errors"])


def test_allow_options_without_quotes_blocks(tmp_path):
    result = validate_startup_config(_base(tmp_path, ALLOW_OPTIONS_WITHOUT_QUOTES="true"))

    assert result["ok"] is False
    assert any("ALLOW_OPTIONS_WITHOUT_QUOTES" in error for error in result["errors"])


def test_missing_gemini_key_warns_when_optional(tmp_path):
    result = validate_startup_config(_base(tmp_path, GEMINI_API_KEY=""))

    assert result["ok"] is True
    assert any("GEMINI_API_KEY" in warning for warning in result["warnings"])


def test_missing_pinecone_warns_when_optional(tmp_path):
    result = validate_startup_config(_base(tmp_path, MEMORY_ENABLED="true", MEMORY_REQUIRED="false", PINECONE_API_KEY="", PINECONE_INDEX_NAME=""))

    assert result["ok"] is True
    assert any("Pinecone" in warning or "Memory" in warning for warning in result["warnings"])


def test_required_pinecone_memory_blocks_when_missing(tmp_path):
    result = validate_startup_config(_base(tmp_path, MEMORY_ENABLED="true", MEMORY_REQUIRED="true", PINECONE_API_KEY="", PINECONE_INDEX_NAME=""))

    assert result["ok"] is False
    assert any("Memory is required" in error for error in result["errors"])


def test_sec_user_agent_required_only_when_sec_research_enabled(tmp_path):
    optional = validate_startup_config(_base(tmp_path, SEC_USER_AGENT="", ENABLE_SEC_RESEARCH="false"))
    enabled_optional = validate_startup_config(_base(tmp_path, SEC_USER_AGENT="", SEC_RESEARCH_ENABLED="true", SEC_RESEARCH_REQUIRED="false"))
    required = validate_startup_config(_base(tmp_path, SEC_USER_AGENT="", SEC_RESEARCH_ENABLED="true", SEC_RESEARCH_REQUIRED="true"))

    assert optional["ok"] is True
    assert enabled_optional["ok"] is True
    assert enabled_optional["safe_to_run_paper_cycle"] is True
    assert enabled_optional["safe_to_run_sec_research"] is False
    assert any("SEC_USER_AGENT" in error for error in enabled_optional["errors"])
    assert required["ok"] is False
    assert any("SEC_USER_AGENT" in error for error in required["errors"])


def test_sec_research_required_blocks_if_disabled(tmp_path):
    result = validate_startup_config(_base(tmp_path, SEC_RESEARCH_ENABLED="false", SEC_RESEARCH_REQUIRED="true"))

    assert result["ok"] is False
    assert any("SEC_RESEARCH_REQUIRED" in error for error in result["errors"])


def test_news_research_required_blocks_only_when_required(tmp_path):
    optional = validate_startup_config(_base(tmp_path, NEWS_RESEARCH_ENABLED="false", NEWS_RESEARCH_REQUIRED="false"))
    required = validate_startup_config(_base(tmp_path, NEWS_RESEARCH_ENABLED="false", NEWS_RESEARCH_REQUIRED="true"))

    assert optional["ok"] is True
    assert required["ok"] is False
    assert any("NEWS_RESEARCH_REQUIRED" in error for error in required["errors"])


def test_short_interest_required_blocks_only_when_disabled_and_required(tmp_path):
    optional = validate_startup_config(_base(tmp_path, SHORT_INTEREST_ENABLED="false", SHORT_INTEREST_REQUIRED="false"))
    required = validate_startup_config(_base(tmp_path, SHORT_INTEREST_ENABLED="false", SHORT_INTEREST_REQUIRED="true"))

    assert optional["ok"] is True
    assert required["ok"] is False
    assert any("SHORT_INTEREST_REQUIRED" in error for error in required["errors"])


def test_scheduler_disabled_warns_but_does_not_block(tmp_path):
    result = validate_startup_config(_base(tmp_path, SCHEDULER_ENABLED="false"))

    assert result["ok"] is True
    assert result["safe_to_use_scheduler"] is True
    assert any("Scheduler is disabled" in warning for warning in result["warnings"])


def test_invalid_scheduler_timezone_blocks_startup(tmp_path):
    result = validate_startup_config(_base(tmp_path, SCHEDULER_TIMEZONE="Nope/Nowhere"))

    assert result["ok"] is False
    assert any("SCHEDULER_TIMEZONE" in error for error in result["errors"])


def test_alerts_disabled_warns_but_does_not_block(tmp_path):
    result = validate_startup_config(_base(tmp_path, ALERTS_ENABLED="false"))

    assert result["ok"] is True
    assert result["safe_to_use_alerts"] is False
    assert any("Alerts are disabled" in warning for warning in result["warnings"])


def test_webhook_alert_channel_without_url_warns(tmp_path):
    result = validate_startup_config(_base(tmp_path, ALERT_CHANNELS="local,webhook", ALERT_WEBHOOK_URL=""))

    assert result["ok"] is True
    assert any("ALERT_WEBHOOK_URL" in warning for warning in result["warnings"])


def test_stress_testing_disabled_warns_but_does_not_block(tmp_path):
    result = validate_startup_config(_base(tmp_path, STRESS_TESTING_ENABLED="false"))

    assert result["ok"] is True
    assert result["safe_to_use_stress_testing"] is False
    assert any("Stress testing is disabled" in warning for warning in result["warnings"])


def test_stress_job_disabled_by_default_warns(tmp_path):
    result = validate_startup_config(_base(tmp_path, STRESS_TEST_JOB_ENABLED="false"))

    assert result["ok"] is True
    assert any("Stress-test scheduled job is disabled" in warning for warning in result["warnings"])


def test_invalid_stress_loss_threshold_blocks(tmp_path):
    result = validate_startup_config(_base(tmp_path, STRESS_MAX_ACCEPTABLE_LOSS_R="0"))

    assert result["ok"] is False
    assert any("STRESS_MAX_ACCEPTABLE_LOSS_R" in error for error in result["errors"])
