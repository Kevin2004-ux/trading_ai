from alerts.alert_manager import create_alert, list_alerts, process_alerts


def test_create_and_list_alert_round_trip(tmp_path):
    db_path = str(tmp_path / "alerts.db")

    created = create_alert(
        db_path=db_path,
        severity="warning",
        alert_type="data_quality_degraded",
        title="Data warning",
        message="Historical fallback was used.",
        payload={"ticker": "AAPL"},
        source="test",
    )
    listed = list_alerts(db_path=db_path)

    assert created["ok"] is True
    assert created["alert"]["payload_json"] == {"ticker": "AAPL"}
    assert listed["ok"] is True
    assert listed["count"] == 1
    assert listed["severity_counts"]["warning"] == 1


def test_process_alerts_stores_warning_and_delivers_locally(tmp_path):
    result = process_alerts(
        db_path=str(tmp_path / "alerts.db"),
        alerts=[
            {
                "severity": "warning",
                "alert_type": "job_failed",
                "title": "Job failed",
                "message": "A scheduled job failed.",
                "payload": {"job": "healthcheck"},
            }
        ],
        config={"ALERT_CHANNELS": "local"},
    )

    assert result["ok"] is True
    assert len(result["stored_alerts"]) == 1
    assert result["deliveries"][0]["channel"] == "local"


def test_process_alerts_respects_min_severity(tmp_path):
    result = process_alerts(
        db_path=str(tmp_path / "alerts.db"),
        alerts=[{"severity": "info", "alert_type": "no_trade_selected", "title": "No trades", "message": "No trades."}],
        config={"ALERT_MIN_SEVERITY": "warning"},
    )

    assert result["ok"] is True
    assert result["stored_alerts"] == []


def test_process_alerts_can_be_disabled(tmp_path):
    result = process_alerts(
        db_path=str(tmp_path / "alerts.db"),
        alerts=[{"severity": "critical", "alert_type": "startup_not_ready", "title": "Startup", "message": "Failed."}],
        config={"ALERTS_ENABLED": "false"},
    )

    assert result["ok"] is True
    assert result["stored_alerts"] == []
    assert result["warning"] == "Alerts are disabled."
