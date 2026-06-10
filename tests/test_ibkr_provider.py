from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from providers import ibkr_provider


class FakeStock:
    def __init__(self, symbol, exchange, currency):
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency
        self.secType = "STK"
        self.conId = 12345


class FakeIB:
    instances = []

    def __init__(self, *, fail_connect=False, bars=None, quote=None, option_params=None):
        self.fail_connect = fail_connect
        self.connected = False
        self.bars = bars or []
        self.quote = quote or SimpleNamespace(
            last=101.5,
            close=100.0,
            bid=101.4,
            ask=101.6,
            volume=123456,
            time=datetime(2026, 6, 8, tzinfo=timezone.utc),
            marketPrice=lambda: 101.5,
        )
        self.option_params = option_params or []
        self.delayed_mode = None
        self.market_data_types_requested = []
        FakeIB.instances.append(self)

    def connect(self, host, port, clientId, readonly=True, timeout=8):
        if self.fail_connect:
            raise ConnectionError("tws unavailable")
        self.connected = True

    def isConnected(self):
        return self.connected

    def disconnect(self):
        self.connected = False

    def reqMarketDataType(self, market_data_type):
        self.delayed_mode = market_data_type
        self.market_data_types_requested.append(market_data_type)

    def qualifyContracts(self, contract):
        return [contract]

    def reqHistoricalData(self, *args, **kwargs):
        return self.bars

    def reqMktData(self, *args, **kwargs):
        return self.quote

    def sleep(self, seconds):
        return None

    def cancelMktData(self, contract):
        return None

    def reqSecDefOptParams(self, *args, **kwargs):
        return self.option_params


def _fake_module(fake_ib_cls):
    return SimpleNamespace(IB=fake_ib_cls, Stock=FakeStock)


def test_missing_ib_insync_returns_clean_unavailable(monkeypatch):
    def fail_import(name):
        raise ModuleNotFoundError("missing")

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", fail_import)

    result = ibkr_provider.check_ibkr_connection()

    assert result["ok"] is False
    assert result["connected"] is False
    assert "ib_insync" in result["error"]


def test_tws_connection_failure_returns_clean_unavailable(monkeypatch):
    class FailingIB(FakeIB):
        def __init__(self):
            super().__init__(fail_connect=True)

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(FailingIB))

    result = ibkr_provider.check_ibkr_connection()

    assert result["ok"] is False
    assert result["connected"] is False
    assert "IBKR connection failed" in result["error"]


def test_delayed_mode_is_requested_and_reported(monkeypatch):
    class DelayedIB(FakeIB):
        def __init__(self):
            super().__init__()

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(DelayedIB))
    monkeypatch.setenv("IBKR_USE_DELAYED_DATA", "true")

    result = ibkr_provider.check_ibkr_connection()

    assert result["ok"] is True
    assert result["use_delayed_data"] is True
    assert FakeIB.instances[-1].delayed_mode == 3


def test_mocked_ibkr_historical_bars_normalize_to_existing_schema(monkeypatch):
    class BarsIB(FakeIB):
        def __init__(self):
            super().__init__(
                bars=[
                    SimpleNamespace(date="2026-06-05", open=100, high=103, low=99, close=102, volume=1000),
                    SimpleNamespace(date="2026-06-06", open=102, high=104, low=101, close=103, volume=1200),
                ]
            )

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(BarsIB))

    result = ibkr_provider.get_ibkr_historical_bars("AAPL", lookback_days=2)

    assert result["ok"] is True
    assert result["source"] == "ibkr"
    assert result["data"]["row_count"] == 2
    assert set(result["data"]["bars"][0]) == {"timestamp", "open", "high", "low", "close", "volume"}


def test_mocked_ibkr_quote_normalizes_to_existing_schema(monkeypatch):
    class QuoteIB(FakeIB):
        def __init__(self):
            super().__init__()

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(QuoteIB))

    result = ibkr_provider.get_ibkr_live_quote("AAPL")

    assert result["ok"] is True
    assert result["source"] == "ibkr"
    assert result["data"]["last_price"] == 101.5
    assert result["data"]["previous_close"] == 100.0


def test_ibkr_options_returns_metadata_or_clean_unavailable(monkeypatch):
    class OptionsIB(FakeIB):
        def __init__(self):
            super().__init__(
                option_params=[
                    SimpleNamespace(
                        expirations={"20260717", "20260821"},
                        strikes={100.0, 105.0},
                        exchange="SMART",
                    )
                ]
            )

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(OptionsIB))

    result = ibkr_provider.get_ibkr_options_chain("AAPL", min_days_to_expiration=1, max_days_to_expiration=120)

    assert result["ok"] is False
    assert result["source"] == "ibkr"
    assert result["data"]["row_count"] == 0
    assert "metadata" in result["data"]
    assert "not enabled yet" in result["error"]


def test_ibkr_provider_does_not_expose_execution_calls():
    source = Path("providers/ibkr_provider.py").read_text()

    forbidden_terms = [
        "place" + "Order",
        "trans" + "mit",
        "reqAccount" + "Updates",
        "account" + "Values",
        "posit" + "ions",
    ]
    for term in forbidden_terms:
        assert term not in source


def test_market_snapshot_uses_historical_bar_fallback_when_quote_unavailable(monkeypatch):
    class FallbackIB(FakeIB):
        def __init__(self):
            super().__init__(
                bars=[
                    SimpleNamespace(date="2026-06-05", open=100, high=103, low=99, close=102, volume=1000),
                    SimpleNamespace(date="2026-06-06", open=102, high=104, low=101, close=103, volume=1200),
                ],
                quote=SimpleNamespace(
                    last=float("nan"),
                    close=float("nan"),
                    bid=float("nan"),
                    ask=float("nan"),
                    volume=None,
                    time=None,
                    marketPrice=lambda: float("nan"),
                    marketDataType=3,
                ),
            )

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(FallbackIB))

    result = ibkr_provider.get_ibkr_market_snapshot("AAPL", lookback_days=2)

    assert result["ok"] is True
    assert result["data"]["quote_fallback_used"] is True
    assert result["data"]["quote"]["quote_source"] == "historical_bar_fallback"
    assert result["data"]["quote"]["last_price"] == 103.0
    assert "IBKR quote unavailable" in result["data"]["data_quality_warnings"][0]


def test_ibkr_diagnostic_schema_and_subscription_warning(monkeypatch):
    class DiagnosticIB(FakeIB):
        def __init__(self):
            super().__init__(
                bars=[
                    SimpleNamespace(date="2026-06-05", open=100, high=103, low=99, close=102, volume=1000),
                ],
                quote=SimpleNamespace(
                    last=float("nan"),
                    close=float("nan"),
                    bid=float("nan"),
                    ask=float("nan"),
                    volume=None,
                    time=None,
                    marketPrice=lambda: float("nan"),
                    marketDataType=3,
                ),
                option_params=[
                    SimpleNamespace(expirations={"20260717"}, strikes={100.0, 105.0}, exchange="SMART")
                ],
            )

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(DiagnosticIB))

    result = ibkr_provider.diagnose_ibkr_market_data_permissions("AAPL")

    assert result["ok"] is True
    assert result["ticker"] == "AAPL"
    assert result["connection"]["ok"] is True
    assert result["historical_bars"]["ok"] is True
    assert result["quote_snapshot"]["ok"] is False
    assert result["delayed_quote_snapshot"]["ok"] is False
    assert result["permissions_summary"]["historical_bars_available"] is True
    assert result["permissions_summary"]["live_or_delayed_quotes_available"] is False
    assert result["permissions_summary"]["options_metadata_available"] is True
    assert result["permissions_summary"]["options_quotes_available"] is False
    assert any("market data" in warning.lower() for warning in result["warnings"])
    assert FakeIB.instances[-1].market_data_types_requested
