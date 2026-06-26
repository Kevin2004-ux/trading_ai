from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
import threading
import time

from providers import ibkr_provider


class FakeStock:
    def __init__(self, symbol, exchange, currency):
        self.symbol = symbol
        self.exchange = exchange
        self.currency = currency
        self.secType = "STK"
        self.conId = 12345


class FakeOption:
    def __init__(self, symbol, lastTradeDateOrContractMonth, strike, right, exchange, currency="USD"):
        self.symbol = symbol
        self.lastTradeDateOrContractMonth = lastTradeDateOrContractMonth
        self.strike = strike
        self.right = right
        self.exchange = exchange
        self.currency = currency
        self.secType = "OPT"
        self.conId = 54321


class FakeIB:
    instances = []

    def __init__(self, *, fail_connect=False, bars=None, quote=None, option_params=None, option_quote=None):
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
        self.option_quote = option_quote or SimpleNamespace(
            bid=4.8,
            ask=5.0,
            last=4.9,
            close=4.85,
            volume=250,
            callOpenInterest=1400,
            putOpenInterest=1300,
            modelGreeks=SimpleNamespace(impliedVol=0.28, delta=0.52, gamma=0.05, theta=-0.04, vega=0.11),
            bidGreeks=None,
            askGreeks=None,
            marketDataType=3,
        )
        self.delayed_mode = None
        self.market_data_types_requested = []
        self.requested_contracts = []
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
        self.requested_contracts.append(contract)
        return [contract]

    def reqHistoricalData(self, *args, **kwargs):
        return self.bars

    def reqMktData(self, *args, **kwargs):
        contract = args[0] if args else None
        if getattr(contract, "secType", None) == "OPT":
            return self.option_quote
        return self.quote

    def sleep(self, seconds):
        return None

    def cancelMktData(self, contract):
        return None

    def reqSecDefOptParams(self, *args, **kwargs):
        return self.option_params


def _fake_module(fake_ib_cls):
    return SimpleNamespace(IB=fake_ib_cls, Stock=FakeStock, Option=FakeOption)


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


def test_ibkr_vix_is_not_requested_as_stock(monkeypatch):
    def fail_import(name):
        raise AssertionError(f"IBKR should not be imported for VIX stock-contract lookup: {name}")

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", fail_import)

    historical = ibkr_provider.get_ibkr_historical_bars("VIX", lookback_days=5)
    quote = ibkr_provider.get_ibkr_live_quote("VIX")

    assert historical["ok"] is False
    assert quote["ok"] is False
    assert historical["error_type"] == "symbol"
    assert quote["error_type"] == "symbol"
    assert "index" in historical["error"].lower()
    assert "stock" in historical["error"].lower()


def test_ibkr_unknown_contract_error_returns_symbol_warning(monkeypatch):
    class UnknownContractIB(FakeIB):
        def __init__(self):
            super().__init__()

        def qualifyContracts(self, contract):
            raise RuntimeError("No security definition has been found for the request: Unknown contract")

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(UnknownContractIB))

    result = ibkr_provider.get_ibkr_live_quote("BAD")

    assert result["ok"] is False
    assert result["error_type"] == "symbol"
    assert "contract qualification failed" in result["error"]
    assert "Unknown contract" in result["error"]


def test_ibkr_error_326_normalizes_to_client_id_message(monkeypatch):
    class ClientIdInUseIB(FakeIB):
        def __init__(self):
            super().__init__()

        def connect(self, host, port, clientId, readonly=True, timeout=8):
            raise TimeoutError("Error 326, reqId -1: Unable to connect as the client id is already in use. clientId already in use?")

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(ClientIdInUseIB))

    result = ibkr_provider.get_ibkr_live_quote("AAPL")

    assert result["ok"] is False
    assert result["error_type"] == "provider"
    assert result["error"] == "IBKR client ID is already in use. Close stale TWS sessions or use a unique IBKR_CLIENT_ID."


def test_concurrent_ibkr_quote_requests_are_serialized(monkeypatch):
    class SerializedIB(FakeIB):
        active_connects = 0
        max_active_connects = 0
        connect_client_ids = []
        class_lock = threading.Lock()

        def __init__(self):
            super().__init__()

        def connect(self, host, port, clientId, readonly=True, timeout=8):
            with self.class_lock:
                SerializedIB.active_connects += 1
                SerializedIB.max_active_connects = max(SerializedIB.max_active_connects, SerializedIB.active_connects)
                SerializedIB.connect_client_ids.append(clientId)
            time.sleep(0.03)
            self.connected = True

        def sleep(self, seconds):
            time.sleep(0.03)

        def disconnect(self):
            with self.class_lock:
                SerializedIB.active_connects -= 1
            self.connected = False

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(SerializedIB))
    monkeypatch.setenv("IBKR_CLIENT_ID", "701")

    results = []
    threads = [
        threading.Thread(target=lambda: results.append(ibkr_provider.get_ibkr_live_quote("AAPL"))),
        threading.Thread(target=lambda: results.append(ibkr_provider.get_ibkr_live_quote("MSFT"))),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert len(results) == 2
    assert all(result["ok"] for result in results)
    assert SerializedIB.connect_client_ids == [701, 701]
    assert SerializedIB.max_active_connects == 1


def test_market_snapshot_returns_quick_provider_failure_when_client_id_in_use(monkeypatch):
    class ClientIdInUseIB(FakeIB):
        def __init__(self):
            super().__init__()

        def connect(self, host, port, clientId, readonly=True, timeout=8):
            raise RuntimeError("Peer closed connection. clientId 701 already in use? Error 326")

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(ClientIdInUseIB))

    result = ibkr_provider.get_ibkr_market_snapshot("AAPL", lookback_days=2)

    assert result["ok"] is False
    assert result["error_type"] == "provider"
    assert "IBKR client ID is already in use" in result["error"]


def test_ibkr_options_returns_small_quoted_chain_when_snapshots_work(monkeypatch):
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

    assert result["ok"] is True
    assert result["source"] == "ibkr"
    assert result["data"]["row_count"] > 0
    assert result["data"]["contracts"][0]["mid"] == 4.9
    assert "metadata" in result["data"]
    assert result["error"] is None


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
    assert "IBKR live quote unavailable" in result["data"]["data_quality_warnings"][0]


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


def test_ibkr_normalizes_class_share_symbol_before_contract_lookup(monkeypatch):
    class NormalizingIB(FakeIB):
        def __init__(self):
            super().__init__(
                bars=[
                    SimpleNamespace(date="2026-06-05", open=100, high=103, low=99, close=102, volume=1000),
                ]
            )

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(NormalizingIB))

    result = ibkr_provider.get_ibkr_historical_bars("BRK.B", lookback_days=1)

    assert result["ok"] is True
    assert result["ticker"] == "BRK.B"
    assert result["data"]["provider_ticker"] == "BRK B"
    assert FakeIB.instances[-1].requested_contracts[0].symbol == "BRK B"


def test_ibkr_timeout_returns_clean_error(monkeypatch):
    @contextmanager
    def timeout_connection():
        raise ibkr_provider._IbkrTimeoutError("IBKR historical bars timed out for WMT after 10 seconds.")
        yield

    monkeypatch.setattr(ibkr_provider, "_ibkr_connection", timeout_connection)

    result = ibkr_provider.get_ibkr_historical_bars("WMT", lookback_days=1)

    assert result["ok"] is False
    assert result["error_type"] == "timeout"
    assert result["provider"] == "ibkr"
    assert result["ticker"] == "WMT"


def test_near_money_option_contract_selection_prefers_closest_strikes():
    specs = ibkr_provider._select_near_money_option_specs(
        "AAPL",
        {
            "matching_expirations": ["2026-07-17"],
            "strikes": [90.0, 100.0, 105.0, 110.0],
        },
        underlying_price=103.0,
        max_contracts=4,
    )

    assert [spec["strike"] for spec in specs] == [105.0, 105.0, 100.0, 100.0]
    assert {spec["option_type"] for spec in specs} == {"call", "put"}


def test_option_quote_diagnostic_normalizes_successful_quotes(monkeypatch):
    class OptionQuoteIB(FakeIB):
        def __init__(self):
            super().__init__(
                option_params=[
                    SimpleNamespace(
                        expirations={"20260717"},
                        strikes={95.0, 100.0, 105.0},
                        exchange="SMART",
                    )
                ]
            )

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(OptionQuoteIB))

    result = ibkr_provider.diagnose_ibkr_option_quotes("AAPL", max_contracts=2)

    assert result["ok"] is True
    assert result["metadata"]["ok"] is True
    assert len(result["contracts_tested"]) == 2
    assert result["permissions_summary"]["option_quotes_available"] is True
    first_quote = result["quotes"][0]
    assert first_quote["ok"] is True
    assert first_quote["bid"] == 4.8
    assert first_quote["ask"] == 5.0
    assert first_quote["mid"] == 4.9
    assert first_quote["model_greeks"]["delta"] == 0.52


def test_option_quote_diagnostic_reports_opra_permission_gap(monkeypatch):
    class MissingOpraIB(FakeIB):
        def __init__(self):
            super().__init__(
                option_params=[
                    SimpleNamespace(
                        expirations={"20260717"},
                        strikes={100.0, 105.0},
                        exchange="SMART",
                    )
                ],
                option_quote=SimpleNamespace(
                    bid=float("nan"),
                    ask=float("nan"),
                    last=float("nan"),
                    close=float("nan"),
                    volume=None,
                    callOpenInterest=None,
                    putOpenInterest=None,
                    modelGreeks=None,
                    marketDataType=3,
                ),
            )

    monkeypatch.setattr(ibkr_provider.importlib, "import_module", lambda name: _fake_module(MissingOpraIB))

    result = ibkr_provider.diagnose_ibkr_option_quotes("AAPL", max_contracts=2)

    assert result["ok"] is True
    assert result["permissions_summary"]["option_metadata_available"] is True
    assert result["permissions_summary"]["option_quotes_available"] is False
    assert result["permissions_summary"]["likely_missing_opra"] is True
    assert any("blocked" in warning.lower() for warning in result["warnings"])
