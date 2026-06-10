import importlib


def test_translator_main_imports_without_missing_model_artifacts():
    module = importlib.import_module("translator.main")

    assert hasattr(module, "ask_translator")
    assert callable(module.ask_translator)


def test_translator_registers_agent_tools():
    module = importlib.import_module("translator.main")

    expected_tools = {
        "build_trade_review_tool",
        "generate_report_tool",
        "run_paper_trading_tool",
        "run_trading_brain_tool",
        "scan_market_for_weekly_trades_tool",
        "scan_candidates_tool",
        "scan_options_for_candidate_tool",
        "evaluate_option_mispricing_tool",
        "calculate_position_size_tool",
        "search_trade_memory_tool",
        "store_trade_memory_tool",
        "find_similar_setups_tool",
        "get_market_regime_tool",
        "get_portfolio_risk_tool",
        "get_relative_strength_tool",
        "get_deep_research_brief_tool",
        "get_sec_filing_brain_tool",
        "get_earnings_transcript_brain_tool",
        "get_candidate_details_tool",
        "log_recommendation_tool",
        "get_open_recommendations_tool",
        "update_outcomes_tool",
        "get_win_loss_record_tool",
        "get_strategy_performance_tool",
        "get_statistical_brain_tool",
        "get_catalyst_brain_tool",
        "review_closed_trades_tool",
        "get_trade_reviews_tool",
    }

    assert expected_tools.issubset(set(module.REGISTERED_TOOL_NAMES))


def test_prompt_contains_mandatory_tool_rules():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "scan_market_for_weekly_trades_tool" in prompt
    assert "run_trading_brain_tool" in prompt
    assert "run_paper_trading_tool" in prompt
    assert "log_recommendation_tool" in prompt
    assert "get_open_recommendations_tool" in prompt
    assert "get_portfolio_risk_tool" in prompt
    assert "calculate_position_size_tool" in prompt
    assert "find_similar_setups_tool" in prompt
    assert "store_trade_memory_tool" in prompt
    assert "build_trade_review_tool" in prompt
    assert "review_closed_trades_tool" in prompt
    assert "get_trade_reviews_tool" in prompt
    assert "generate_report_tool" in prompt
    assert "get_win_loss_record_tool" in prompt
    assert "scan_options_for_candidate_tool" in prompt
    assert "get_deep_research_brief_tool" in prompt
    assert "get_sec_filing_brain_tool" in prompt
    assert "get_earnings_transcript_brain_tool" in prompt


def test_prompt_blocks_failed_and_watchlist_final_recommendations():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Never recommend a trade that failed constraints." in prompt
    assert "Never recommend a watchlist candidate as a final trade." in prompt


def test_prompt_requires_logging_for_final_recommendations():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Whenever you give a final actionable recommendation, you must call `log_recommendation_tool`." in prompt


def test_prompt_marks_trading_brain_as_primary_orchestrator():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "primary orchestrator" in prompt
    assert "Do not bypass the trading brain for weekly recommendations." in prompt


def test_prompt_marks_paper_trading_as_simulated_only():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Paper trading is simulated only." in prompt
    assert "only paper tracking is supported" in prompt
    assert "Never imply paper performance is real realized brokerage P/L." in prompt


def test_prompt_includes_option_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Options are research alternatives unless they are explicitly logged through `log_recommendation_tool`." in prompt
    assert "Options are higher-risk research alternatives unless explicitly selected by the trading brain." in prompt
    assert "Never recommend an option without checking bid/ask spread, volume, open interest, expiration, breakeven, and risk/reward." in prompt
    assert "Do not present an option as preferred unless the trading brain marks it preferred or `log_recommendation_tool` accepts it." in prompt
    assert "Never pretend option premium P/L is known without true option price history." in prompt
    assert "Never imply option paper P/L is exact unless option price history is available." in prompt
    assert "If options-chain data is unavailable, say so clearly." in prompt
    assert "Options mispricing labels are research estimates, not certainty." in prompt
    assert "Never call an option guaranteed undervalued." in prompt
    assert "A cheap option can still be a bad trade if probability, liquidity, spread, or breakeven is poor." in prompt
    assert "Do not prefer an option solely because theoretical value is higher than market mid." in prompt


def test_prompt_includes_market_regime_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Broad trade recommendations should consider market regime." in prompt
    assert "The model must not force 2 to 5 trades when the regime is unfavorable." in prompt
    assert "If regime is risk-off or high-volatility, explain that fewer or no trades may qualify." in prompt
    assert "Option aggressiveness should be reduced in high-volatility or risk-off regimes." in prompt
    assert "Mention when market regime reduces aggressiveness." in prompt


def test_prompt_includes_portfolio_risk_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Broad trade recommendations should consider portfolio risk." in prompt
    assert "Before final weekly recommendations when portfolio construction matters, call `get_portfolio_risk_tool` or use `run_trading_brain_tool`." in prompt
    assert "Do not recommend too many correlated trades." in prompt
    assert "Do not ignore sector concentration or theme concentration." in prompt
    assert "Do not ignore option premium exposure." in prompt
    assert "Portfolio risk limits do not replace hard trade constraints." in prompt
    assert "portfolio-level risk" in prompt


def test_prompt_includes_position_sizing_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Broad trade recommendations should consider position sizing for paper/research use." in prompt
    assert "calculate_position_size_tool" in prompt
    assert "Position sizing is for paper/research only and is not financial advice." in prompt
    assert "Position sizing should be based on account size, risk mode, entry, stop, and option premium." in prompt
    assert "If suggested position size is zero, explain that the trade is too large for the configured account or risk settings." in prompt


def test_prompt_includes_semantic_memory_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Semantic memory is qualitative context only." in prompt
    assert "SQLite remains the source of truth for trade outcomes and performance." in prompt
    assert "Do not treat similar-memory matches as statistical proof." in prompt
    assert "If semantic memory is unavailable, say so clearly." in prompt
    assert "Do not store memories unless the user explicitly asks or `store_memory=True`." in prompt
    assert "find_similar_setups_tool" in prompt
    assert "store_trade_memory_tool" in prompt


def test_prompt_includes_trade_journal_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "review my trades" in prompt
    assert "build_trade_review_tool" in prompt
    assert "review_closed_trades_tool" in prompt
    assert "get_trade_reviews_tool" in prompt
    assert "Winning trades are not automatically good process." in prompt
    assert "Losing trades are not automatically bad process." in prompt
    assert "Do not invent reasons for trade outcomes when journal, outcome, thesis, or market-context data is missing." in prompt
    assert "Trade reviews are for improving the system and paper-trading process, not guarantees of future performance." in prompt
    assert "SQLite remains the source of truth for outcomes; semantic memory is qualitative only." in prompt


def test_prompt_includes_report_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "generate_report_tool" in prompt
    assert "make a report" in prompt
    assert "Reports summarize evidence and system outputs; they do not create new trades by themselves." in prompt
    assert "Reports must preserve warnings, missing data, and risk notes." in prompt
    assert "Do not treat paper-trading performance reports as live brokerage P/L." in prompt


def test_prompt_includes_relative_strength_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "Broad trade recommendations should consider relative strength." in prompt
    assert "The model should prefer stocks outperforming SPY, QQQ, or sector peers when other constraints are equal." in prompt
    assert "The model should mention when a technically good setup has weak relative strength." in prompt
    assert "The model must not force trades solely because relative strength is strong." in prompt
    assert "Relative strength is context, not a replacement for hard constraints." in prompt


def test_prompt_includes_deep_research_guardrails():
    prompts = importlib.import_module("translator.prompts")
    prompt = prompts.SYSTEM_PROMPT

    assert "deep dive, research brief, bull case, bear case" in prompt
    assert "Research briefs are evidence summaries, not guarantees." in prompt
    assert "Do not invent source-backed claims when the evidence table says data is unavailable." in prompt
    assert "Distinguish a research thesis from a final trade recommendation." in prompt
    assert "A strong research brief does not bypass hard constraints or logging guardrails." in prompt
    assert "filing risk, 10-K, 10-Q, 8-K, dilution, or offering risk" in prompt
    assert "earnings call, transcript, management tone, or guidance" in prompt
    assert "Filing and transcript summaries are evidence summaries, not guarantees." in prompt
    assert "Do not invent filing details or management commentary when the data is unavailable." in prompt
    assert "A strong earnings transcript does not bypass hard trade constraints." in prompt
    assert "High filing risk should be surfaced clearly as a risk." in prompt
