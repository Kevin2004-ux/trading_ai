from diagnostics import healthcheck
from diagnostics.healthcheck import check_environment


def test_check_environment_returns_package_env_and_database_sections(monkeypatch, tmp_path):
    monkeypatch.setattr(
        healthcheck,
        "_package_status",
        lambda distribution_name, import_name: {"available": True, "version": "1.0"},
    )
    monkeypatch.setattr(
        healthcheck,
        "_import_status",
        lambda module_name: {"ok": True, "module": module_name, "error": None, "details": {}},
    )
    for env_name in healthcheck.OPTIONAL_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    result = check_environment(db_path=str(tmp_path / "healthcheck.db"))

    assert result["ok"] is True
    assert "python_version" in result
    assert "fastapi" in result["packages"]
    assert result["env_vars"]["GEMINI_API_KEY"] == "missing"
    assert result["database"]["ok"] is True
    assert result["app"]["ok"] is True
    assert result["cli"]["ok"] is True


def test_missing_optional_env_vars_create_warnings_not_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(
        healthcheck,
        "_package_status",
        lambda distribution_name, import_name: {"available": True, "version": "1.0"},
    )
    monkeypatch.setattr(
        healthcheck,
        "_import_status",
        lambda module_name: {"ok": True, "module": module_name, "error": None, "details": {}},
    )
    for env_name in healthcheck.OPTIONAL_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    result = check_environment(db_path=str(tmp_path / "missing_env.db"))

    assert result["ok"] is True
    assert result["errors"] == []
    assert any("GEMINI_API_KEY" in warning for warning in result["warnings"])
    assert any("POLYGON_API_KEY" in warning for warning in result["warnings"])


def test_missing_required_package_is_fatal(monkeypatch, tmp_path):
    def fake_package_status(distribution_name, import_name):
        if distribution_name == "fastapi":
            return {"available": False, "version": None}
        return {"available": True, "version": "1.0"}

    monkeypatch.setattr(healthcheck, "_package_status", fake_package_status)
    monkeypatch.setattr(
        healthcheck,
        "_import_status",
        lambda module_name: {"ok": True, "module": module_name, "error": None, "details": {}},
    )

    result = check_environment(db_path=str(tmp_path / "missing_package.db"))

    assert result["ok"] is False
    assert any("fastapi" in error for error in result["errors"])


def test_package_status_handles_missing_parent_package(monkeypatch):
    def raise_missing_parent(import_name):
        raise ModuleNotFoundError("No module named 'google'")

    monkeypatch.setattr(healthcheck.importlib.util, "find_spec", raise_missing_parent)

    result = healthcheck._package_status("google-generativeai", "google.generativeai")

    assert result == {"available": False, "version": None}


def test_healthcheck_reports_ibkr_provider_config(monkeypatch, tmp_path):
    monkeypatch.setattr(
        healthcheck,
        "_package_status",
        lambda distribution_name, import_name: {"available": True, "version": "1.0"},
    )
    monkeypatch.setattr(
        healthcheck,
        "_import_status",
        lambda module_name: {"ok": True, "module": module_name, "error": None, "details": {}},
    )
    monkeypatch.setenv("MARKET_DATA_PROVIDER", "ibkr")
    monkeypatch.setenv("OPTIONS_DATA_PROVIDER", "ibkr")
    monkeypatch.setenv("IBKR_HOST", "127.0.0.1")
    monkeypatch.setenv("IBKR_PORT", "7496")
    monkeypatch.setenv("IBKR_CLIENT_ID", "123")
    monkeypatch.setenv("IBKR_READ_ONLY", "true")
    monkeypatch.setenv("IBKR_USE_DELAYED_DATA", "true")

    result = check_environment(db_path=str(tmp_path / "ibkr_health.db"))

    assert result["ok"] is True
    assert result["selected_providers"]["market_data_provider"] == "ibkr"
    assert result["selected_providers"]["options_data_provider"] == "ibkr"
    assert result["ibkr"]["host"] == "127.0.0.1"
    assert result["ibkr"]["port"] == "7496"
    assert result["ibkr"]["client_id"] == "123"
    assert result["ibkr"]["read_only"] == "true"
    assert result["ibkr"]["use_delayed_data"] == "true"
    assert result["ibkr"]["ib_insync_available"] is True
