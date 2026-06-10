import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


DEFAULT_DB_PATH = "strategy_library.db"
TERMINAL_STATUSES = {"win", "loss", "expired", "closed", "cancelled", "canceled"}
JSON_COLUMNS = {
    "trade_recommendations": {
        "data_snapshot_json",
        "constraint_results_json",
        "model_outputs_json",
    },
    "scanner_runs": {"config_json"},
    "candidate_evaluations": {
        "failed_constraints_json",
        "metrics_json",
        "constraint_results_json",
    },
    "trade_outcomes": {"grading_data_json"},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_initialized(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS trade_recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy TEXT NOT NULL,
                setup_type TEXT,
                entry_price REAL NOT NULL,
                target_price REAL NOT NULL,
                stop_loss REAL NOT NULL,
                risk_reward REAL,
                holding_period_days INTEGER,
                expiration TEXT,
                option_contract TEXT,
                confidence REAL,
                score REAL,
                recommendation_status TEXT DEFAULT 'open',
                thesis TEXT,
                invalidation TEXT,
                data_snapshot_json TEXT,
                constraint_results_json TEXT,
                model_outputs_json TEXT,
                source TEXT DEFAULT 'ai_agent',
                status TEXT DEFAULT 'open',
                outcome TEXT,
                exit_price REAL,
                closed_at TEXT,
                max_gain REAL,
                max_drawdown REAL,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS scanner_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                universe TEXT,
                total_scanned INTEGER,
                total_passed INTEGER,
                total_rejected INTEGER,
                market_data_freshness TEXT,
                config_json TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS candidate_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scanner_run_id INTEGER,
                created_at TEXT NOT NULL,
                ticker TEXT NOT NULL,
                asset_type TEXT,
                direction TEXT,
                setup_type TEXT,
                passed_constraints INTEGER,
                score REAL,
                rank INTEGER,
                rejection_reason TEXT,
                failed_constraints_json TEXT,
                metrics_json TEXT,
                constraint_results_json TEXT,
                FOREIGN KEY(scanner_run_id) REFERENCES scanner_runs(id)
            );

            CREATE TABLE IF NOT EXISTS trade_outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                outcome TEXT NOT NULL,
                exit_price REAL,
                exit_reason TEXT,
                realized_return REAL,
                max_gain REAL,
                max_drawdown REAL,
                grading_data_json TEXT,
                FOREIGN KEY(recommendation_id) REFERENCES trade_recommendations(id)
            );

            CREATE INDEX IF NOT EXISTS idx_trade_recommendations_status
            ON trade_recommendations(status);

            CREATE INDEX IF NOT EXISTS idx_trade_recommendations_ticker_created_at
            ON trade_recommendations(ticker, created_at);

            CREATE INDEX IF NOT EXISTS idx_candidate_evaluations_scanner_run_id
            ON candidate_evaluations(scanner_run_id);

            CREATE INDEX IF NOT EXISTS idx_trade_outcomes_recommendation_id
            ON trade_outcomes(recommendation_id);
            """
        )


def _is_terminal_status(status: str | None) -> bool:
    return str(status or "").lower() in TERMINAL_STATUSES


def _serialize_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _deserialize_json(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _row_to_dict(row: sqlite3.Row | None, table_name: str | None = None) -> dict | None:
    if row is None:
        return None

    result = dict(row)
    if table_name in JSON_COLUMNS:
        for column in JSON_COLUMNS[table_name]:
            if column in result:
                result[column] = _deserialize_json(result[column])
    return result


def _fetch_one(
    conn: sqlite3.Connection,
    query: str,
    params: tuple = (),
    table_name: str | None = None,
) -> dict | None:
    row = conn.execute(query, params).fetchone()
    return _row_to_dict(row, table_name=table_name)


def _fetch_all(
    conn: sqlite3.Connection,
    query: str,
    params: tuple = (),
    table_name: str | None = None,
) -> list[dict]:
    rows = conn.execute(query, params).fetchall()
    return [_row_to_dict(row, table_name=table_name) for row in rows]


def init_trade_tracking_db(db_path: str = DEFAULT_DB_PATH) -> dict:
    try:
        _ensure_initialized(db_path)

        return {
            "ok": True,
            "db_path": db_path,
            "tables_created": [
                "trade_recommendations",
                "scanner_runs",
                "candidate_evaluations",
                "trade_outcomes",
            ],
        }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "db_path": db_path}


def log_recommendation(
    ticker: str,
    asset_type: str,
    direction: str,
    strategy: str,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    setup_type: str | None = None,
    risk_reward: float | None = None,
    holding_period_days: int | None = None,
    expiration: str | None = None,
    option_contract: str | None = None,
    confidence: float | None = None,
    score: float | None = None,
    recommendation_status: str = "open",
    thesis: str | None = None,
    invalidation: str | None = None,
    data_snapshot_json: dict | list | str | None = None,
    constraint_results_json: dict | list | str | None = None,
    model_outputs_json: dict | list | str | None = None,
    source: str = "ai_agent",
    status: str = "open",
    outcome: str | None = None,
    exit_price: float | None = None,
    closed_at: str | None = None,
    max_gain: float | None = None,
    max_drawdown: float | None = None,
    notes: str | None = None,
    created_at: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    created_at = created_at or _utc_now_iso()

    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO trade_recommendations (
                    created_at, ticker, asset_type, direction, strategy, setup_type,
                    entry_price, target_price, stop_loss, risk_reward,
                    holding_period_days, expiration, option_contract, confidence,
                    score, recommendation_status, thesis, invalidation,
                    data_snapshot_json, constraint_results_json, model_outputs_json,
                    source, status, outcome, exit_price, closed_at, max_gain,
                    max_drawdown, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    ticker,
                    asset_type,
                    direction,
                    strategy,
                    setup_type,
                    entry_price,
                    target_price,
                    stop_loss,
                    risk_reward,
                    holding_period_days,
                    expiration,
                    option_contract,
                    confidence,
                    score,
                    recommendation_status,
                    thesis,
                    invalidation,
                    _serialize_json(data_snapshot_json),
                    _serialize_json(constraint_results_json),
                    _serialize_json(model_outputs_json),
                    source,
                    status,
                    outcome,
                    exit_price,
                    closed_at,
                    max_gain,
                    max_drawdown,
                    notes,
                ),
            )
            recommendation_id = cursor.lastrowid
            return _fetch_one(
                conn,
                "SELECT * FROM trade_recommendations WHERE id = ?",
                (recommendation_id,),
                table_name="trade_recommendations",
            ) or {
                "ok": False,
                "error": "Recommendation insert succeeded but could not be reloaded.",
                "id": recommendation_id,
            }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "ticker": ticker}


def get_recommendation(recommendation_id: int, db_path: str = DEFAULT_DB_PATH) -> dict | None:
    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            return _fetch_one(
                conn,
                "SELECT * FROM trade_recommendations WHERE id = ?",
                (recommendation_id,),
                table_name="trade_recommendations",
            )
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "id": recommendation_id}


def get_open_recommendations(db_path: str = DEFAULT_DB_PATH) -> list[dict] | dict:
    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            return _fetch_all(
                conn,
                """
                SELECT *
                FROM trade_recommendations
                WHERE closed_at IS NULL
                  AND lower(COALESCE(status, 'open')) NOT IN ('win', 'loss', 'expired', 'closed', 'cancelled', 'canceled')
                ORDER BY created_at DESC, id DESC
                """,
                table_name="trade_recommendations",
            )
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc)}


def update_recommendation_status(
    recommendation_id: int,
    status: str,
    outcome: str | None = None,
    exit_price: float | None = None,
    notes: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    normalized_status = str(status).lower()
    closed_at = _utc_now_iso() if _is_terminal_status(normalized_status) else None

    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            existing = _fetch_one(
                conn,
                "SELECT * FROM trade_recommendations WHERE id = ?",
                (recommendation_id,),
                table_name="trade_recommendations",
            )
            if existing is None:
                return {
                    "ok": False,
                    "error": f"Recommendation {recommendation_id} not found.",
                }

            merged_notes = notes if existing.get("notes") is None else existing["notes"]
            if notes and existing.get("notes"):
                merged_notes = f"{existing['notes']}\n{notes}"

            conn.execute(
                """
                UPDATE trade_recommendations
                SET status = ?,
                    recommendation_status = ?,
                    outcome = COALESCE(?, outcome),
                    exit_price = COALESCE(?, exit_price),
                    closed_at = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    status,
                    status,
                    outcome,
                    exit_price,
                    closed_at if _is_terminal_status(normalized_status) else existing.get("closed_at"),
                    merged_notes,
                    recommendation_id,
                ),
            )

            return _fetch_one(
                conn,
                "SELECT * FROM trade_recommendations WHERE id = ?",
                (recommendation_id,),
                table_name="trade_recommendations",
            ) or {
                "ok": False,
                "error": "Status update succeeded but could not be reloaded.",
                "id": recommendation_id,
            }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "id": recommendation_id}


def log_scanner_run(
    universe: str | None = None,
    total_scanned: int | None = None,
    total_passed: int | None = None,
    total_rejected: int | None = None,
    market_data_freshness: str | None = None,
    config_json: dict | list | str | None = None,
    notes: str | None = None,
    created_at: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    created_at = created_at or _utc_now_iso()

    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO scanner_runs (
                    created_at, universe, total_scanned, total_passed,
                    total_rejected, market_data_freshness, config_json, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    universe,
                    total_scanned,
                    total_passed,
                    total_rejected,
                    market_data_freshness,
                    _serialize_json(config_json),
                    notes,
                ),
            )
            scanner_run_id = cursor.lastrowid
            return _fetch_one(
                conn,
                "SELECT * FROM scanner_runs WHERE id = ?",
                (scanner_run_id,),
                table_name="scanner_runs",
            ) or {
                "ok": False,
                "error": "Scanner run insert succeeded but could not be reloaded.",
                "id": scanner_run_id,
            }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc)}


def log_candidate_evaluation(
    ticker: str,
    scanner_run_id: int | None = None,
    asset_type: str | None = None,
    direction: str | None = None,
    setup_type: str | None = None,
    passed_constraints: int | bool | None = None,
    score: float | None = None,
    rank: int | None = None,
    rejection_reason: str | None = None,
    failed_constraints_json: dict | list | str | None = None,
    metrics_json: dict | list | str | None = None,
    constraint_results_json: dict | list | str | None = None,
    created_at: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    created_at = created_at or _utc_now_iso()
    normalized_passed = None if passed_constraints is None else int(bool(passed_constraints))

    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO candidate_evaluations (
                    scanner_run_id, created_at, ticker, asset_type, direction,
                    setup_type, passed_constraints, score, rank,
                    rejection_reason, failed_constraints_json, metrics_json,
                    constraint_results_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scanner_run_id,
                    created_at,
                    ticker,
                    asset_type,
                    direction,
                    setup_type,
                    normalized_passed,
                    score,
                    rank,
                    rejection_reason,
                    _serialize_json(failed_constraints_json),
                    _serialize_json(metrics_json),
                    _serialize_json(constraint_results_json),
                ),
            )
            evaluation_id = cursor.lastrowid
            return _fetch_one(
                conn,
                "SELECT * FROM candidate_evaluations WHERE id = ?",
                (evaluation_id,),
                table_name="candidate_evaluations",
            ) or {
                "ok": False,
                "error": "Candidate evaluation insert succeeded but could not be reloaded.",
                "id": evaluation_id,
            }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "ticker": ticker}


def log_trade_outcome(
    recommendation_id: int,
    outcome: str,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    realized_return: float | None = None,
    max_gain: float | None = None,
    max_drawdown: float | None = None,
    grading_data_json: dict | list | str | None = None,
    created_at: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> dict:
    created_at = created_at or _utc_now_iso()

    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            recommendation = _fetch_one(
                conn,
                "SELECT * FROM trade_recommendations WHERE id = ?",
                (recommendation_id,),
                table_name="trade_recommendations",
            )
            if recommendation is None:
                return {
                    "ok": False,
                    "error": f"Recommendation {recommendation_id} not found.",
                }

            if realized_return is None and exit_price is not None and recommendation.get("entry_price"):
                entry_price = recommendation["entry_price"]
                realized_return = ((exit_price - entry_price) / entry_price) * 100.0
                if str(recommendation.get("direction", "")).lower() == "short":
                    realized_return = ((entry_price - exit_price) / entry_price) * 100.0

            cursor = conn.execute(
                """
                INSERT INTO trade_outcomes (
                    recommendation_id, created_at, outcome, exit_price, exit_reason,
                    realized_return, max_gain, max_drawdown, grading_data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    recommendation_id,
                    created_at,
                    outcome,
                    exit_price,
                    exit_reason,
                    realized_return,
                    max_gain,
                    max_drawdown,
                    _serialize_json(grading_data_json),
                ),
            )
            outcome_id = cursor.lastrowid

            closed_status = "open" if not _is_terminal_status(outcome) else outcome.lower()
            conn.execute(
                """
                UPDATE trade_recommendations
                SET outcome = ?,
                    status = ?,
                    recommendation_status = ?,
                    exit_price = COALESCE(?, exit_price),
                    closed_at = ?,
                    max_gain = COALESCE(?, max_gain),
                    max_drawdown = COALESCE(?, max_drawdown)
                WHERE id = ?
                """,
                (
                    outcome,
                    closed_status,
                    closed_status,
                    exit_price,
                    None if closed_status == "open" else created_at,
                    max_gain,
                    max_drawdown,
                    recommendation_id,
                ),
            )

            return _fetch_one(
                conn,
                "SELECT * FROM trade_outcomes WHERE id = ?",
                (outcome_id,),
                table_name="trade_outcomes",
            ) or {
                "ok": False,
                "error": "Trade outcome insert succeeded but could not be reloaded.",
                "id": outcome_id,
            }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc), "recommendation_id": recommendation_id}


def get_win_loss_record(db_path: str = DEFAULT_DB_PATH) -> dict:
    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_recommendations,
                    SUM(CASE WHEN lower(COALESCE(outcome, '')) = 'win' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN lower(COALESCE(outcome, '')) = 'loss' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN lower(COALESCE(outcome, '')) = 'expired' THEN 1 ELSE 0 END) AS expired,
                    SUM(CASE WHEN lower(COALESCE(status, 'open')) = 'open' THEN 1 ELSE 0 END) AS open
                FROM trade_recommendations
                """
            ).fetchone()

            result = dict(row)
            closed = (result["wins"] or 0) + (result["losses"] or 0)
            result["closed_trades"] = closed
            result["win_rate"] = round(((result["wins"] or 0) / closed) * 100.0, 2) if closed else 0.0
            return result
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc)}


def get_strategy_performance(db_path: str = DEFAULT_DB_PATH) -> dict:
    try:
        _ensure_initialized(db_path)
        with _connect(db_path) as conn:
            overall = dict(
                conn.execute(
                    """
                    SELECT
                        COUNT(*) AS total_recommendations,
                        AVG(score) AS average_score,
                        AVG(confidence) AS average_confidence,
                        AVG(risk_reward) AS average_risk_reward
                    FROM trade_recommendations
                    """
                ).fetchone()
            )

            by_strategy = _fetch_all(
                conn,
                """
                WITH latest_outcomes AS (
                    SELECT t1.*
                    FROM trade_outcomes t1
                    INNER JOIN (
                        SELECT recommendation_id, MAX(id) AS max_id
                        FROM trade_outcomes
                        GROUP BY recommendation_id
                    ) t2
                    ON t1.recommendation_id = t2.recommendation_id
                    AND t1.id = t2.max_id
                )
                SELECT
                    tr.strategy,
                    COUNT(*) AS total_recommendations,
                    SUM(CASE WHEN lower(COALESCE(tr.outcome, '')) = 'win' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN lower(COALESCE(tr.outcome, '')) = 'loss' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN lower(COALESCE(tr.outcome, '')) = 'expired' THEN 1 ELSE 0 END) AS expired,
                    AVG(tr.score) AS average_score,
                    AVG(tr.confidence) AS average_confidence,
                    AVG(tr.risk_reward) AS average_risk_reward,
                    AVG(lo.realized_return) AS average_realized_return
                FROM trade_recommendations tr
                LEFT JOIN latest_outcomes lo
                    ON lo.recommendation_id = tr.id
                GROUP BY tr.strategy
                ORDER BY total_recommendations DESC, tr.strategy ASC
                """,
            )

            by_setup_type = _fetch_all(
                conn,
                """
                WITH latest_outcomes AS (
                    SELECT t1.*
                    FROM trade_outcomes t1
                    INNER JOIN (
                        SELECT recommendation_id, MAX(id) AS max_id
                        FROM trade_outcomes
                        GROUP BY recommendation_id
                    ) t2
                    ON t1.recommendation_id = t2.recommendation_id
                    AND t1.id = t2.max_id
                )
                SELECT
                    COALESCE(tr.setup_type, 'unspecified') AS setup_type,
                    COUNT(*) AS total_recommendations,
                    SUM(CASE WHEN lower(COALESCE(tr.outcome, '')) = 'win' THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN lower(COALESCE(tr.outcome, '')) = 'loss' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN lower(COALESCE(tr.outcome, '')) = 'expired' THEN 1 ELSE 0 END) AS expired,
                    AVG(tr.score) AS average_score,
                    AVG(tr.confidence) AS average_confidence,
                    AVG(tr.risk_reward) AS average_risk_reward,
                    AVG(lo.realized_return) AS average_realized_return
                FROM trade_recommendations tr
                LEFT JOIN latest_outcomes lo
                    ON lo.recommendation_id = tr.id
                GROUP BY COALESCE(tr.setup_type, 'unspecified')
                ORDER BY total_recommendations DESC, setup_type ASC
                """,
            )

            return {
                "overall": overall,
                "by_strategy": by_strategy,
                "by_setup_type": by_setup_type,
            }
    except sqlite3.Error as exc:
        return {"ok": False, "error": str(exc)}
