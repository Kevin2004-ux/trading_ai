from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
import platform
from datetime import datetime, timezone
from typing import Any

from tracking.trade_logger import init_trade_tracking_db


DEFAULT_DB_PATH = "strategy_library.db"
REQUIRED_PACKAGES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "pytest": "pytest",
    "pandas": "pandas",
    "numpy": "numpy",
    "requests": "requests",
    "python-dotenv": "dotenv",
    "ib-insync": "ib_insync",
    "scipy": "scipy",
    "optuna": "optuna",
    "google-generativeai": "google.generativeai",
}
OPTIONAL_PACKAGES = {
    "pinecone": "pinecone",
    "torch": "torch",
    "py_vollib": "py_vollib",
    "textblob": "textblob",
}
OPTIONAL_ENV_VARS = [
    "GEMINI_API_KEY",
    "POLYGON_API_KEY",
    "FMP_API_KEY",
    "PINECONE_API_KEY",
    "PINECONE_INDEX_NAME",
    "MARKET_DATA_PROVIDER",
    "OPTIONS_DATA_PROVIDER",
    "IBKR_HOST",
    "IBKR_PORT",
    "IBKR_CLIENT_ID",
    "IBKR_READ_ONLY",
    "IBKR_USE_DELAYED_DATA",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _package_status(distribution_name: str, import_name: str) -> dict:
    try:
        available = importlib.util.find_spec(import_name) is not None
    except ModuleNotFoundError:
        available = False
    version = None
    if available:
        try:
            version = importlib.metadata.version(distribution_name)
        except importlib.metadata.PackageNotFoundError:
            try:
                module = importlib.import_module(import_name)
                version = getattr(module, "__version__", None)
            except Exception:
                version = None
    return {
        "available": available,
        "version": version,
    }


def _import_status(module_name: str) -> dict:
    try:
        module = importlib.import_module(module_name)
        return {
            "ok": True,
            "module": module_name,
            "error": None,
            "details": {
                "has_app": hasattr(module, "app") if module_name == "ui.app" else None,
                "has_main": hasattr(module, "main") if module_name == "cli" else None,
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "module": module_name,
            "error": str(exc),
            "details": {},
        }


def check_environment(db_path: str = DEFAULT_DB_PATH) -> dict:
    warnings: list[str] = []
    errors: list[str] = []

    packages = {
        package_name: _package_status(package_name, import_name)
        for package_name, import_name in REQUIRED_PACKAGES.items()
    }
    optional_packages = {
        package_name: _package_status(package_name, import_name)
        for package_name, import_name in OPTIONAL_PACKAGES.items()
    }
    packages.update(optional_packages)

    for package_name, status in packages.items():
        if package_name in REQUIRED_PACKAGES and not status["available"]:
            errors.append(f"Required package is not installed: {package_name}")
        elif package_name in OPTIONAL_PACKAGES and not status["available"]:
            warnings.append(f"Optional package is not installed: {package_name}")

    env_vars = {
        name: "present" if os.getenv(name) else "missing"
        for name in OPTIONAL_ENV_VARS
    }
    for name, status in env_vars.items():
        if status == "missing":
            warnings.append(f"Optional environment variable is missing: {name}")

    db_existed_before = os.path.exists(db_path)
    database: dict[str, Any]
    init_result = init_trade_tracking_db(db_path=db_path)
    if init_result.get("ok"):
        database = {
            "ok": True,
            "db_path": db_path,
            "exists": os.path.exists(db_path),
            "existed_before_check": db_existed_before,
            "can_initialize": True,
            "error": None,
        }
    else:
        database = {
            "ok": False,
            "db_path": db_path,
            "exists": os.path.exists(db_path),
            "existed_before_check": db_existed_before,
            "can_initialize": False,
            "error": init_result.get("error", "Failed to initialize SQLite database."),
        }
        errors.append(str(database["error"]))

    app_status = _import_status("ui.app")
    cli_status = _import_status("cli")
    if not app_status["ok"]:
        errors.append(f"FastAPI app import failed: {app_status['error']}")
    if not cli_status["ok"]:
        errors.append(f"CLI import failed: {cli_status['error']}")

    selected_providers = {
        "market_data_provider": os.getenv("MARKET_DATA_PROVIDER") or "polygon",
        "options_data_provider": os.getenv("OPTIONS_DATA_PROVIDER") or "polygon",
    }
    ibkr_config = {
        "host": os.getenv("IBKR_HOST") or "127.0.0.1",
        "port": os.getenv("IBKR_PORT") or "7496",
        "client_id": os.getenv("IBKR_CLIENT_ID") or "123",
        "read_only": os.getenv("IBKR_READ_ONLY") or "true",
        "use_delayed_data": os.getenv("IBKR_USE_DELAYED_DATA") or "true",
        "ib_insync_available": bool(packages.get("ib-insync", {}).get("available")),
    }

    return {
        "ok": not errors,
        "timestamp": _now_iso(),
        "python_version": platform.python_version(),
        "packages": packages,
        "env_vars": env_vars,
        "selected_providers": selected_providers,
        "ibkr": ibkr_config,
        "database": database,
        "app": app_status,
        "cli": cli_status,
        "warnings": warnings,
        "errors": errors,
    }
