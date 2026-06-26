"""Research package public exports.

The package intentionally resolves exports lazily because deep research depends
on analytics modules that can import scanner modules during startup.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "analyze_earnings_8k": ("research.earnings_8k_analyzer", "analyze_earnings_8k"),
    "extract_earnings_release_sections": ("research.earnings_8k_analyzer", "extract_earnings_release_sections"),
    "analyze_filing_risks": ("research.sec_filings", "analyze_filing_risks"),
    "analyze_recent_filings": ("research.filing_analyzer", "analyze_recent_filings"),
    "analyze_guidance_context": ("research.earnings_transcripts", "analyze_guidance_context"),
    "analyze_transcript_sentiment": ("research.earnings_transcripts", "analyze_transcript_sentiment"),
    "build_evidence_table": ("research.deep_research", "build_evidence_table"),
    "build_current_research": ("research.research_orchestrator", "build_current_research"),
    "build_research_brief": ("research.deep_research", "build_research_brief"),
    "classify_filing_importance": ("research.filing_analyzer", "classify_filing_importance"),
    "detect_material_event_flags": ("research.filing_analyzer", "detect_material_event_flags"),
    "evaluate_filing_sentiment": ("research.filing_sentiment", "evaluate_filing_sentiment"),
    "clear_research_cache": ("research.research_orchestrator", "clear_research_cache"),
    "empty_research_response": ("research.research_orchestrator", "empty_research_response"),
    "fetch_company_submissions": ("research.sec_edgar_provider", "fetch_company_submissions"),
    "fetch_filing_text": ("research.sec_edgar_provider", "fetch_filing_text"),
    "fetch_recent_filings": ("research.sec_edgar_provider", "fetch_recent_filings"),
    "fetch_recent_news": ("research.news_provider", "fetch_recent_news"),
    "generate_trade_thesis": ("research.deep_research", "generate_trade_thesis"),
    "diagnose_news_provider": ("research.news_provider", "diagnose_news_provider"),
    "evaluate_borrow_pressure": ("research.short_interest", "evaluate_borrow_pressure"),
    "evaluate_news_sentiment": ("research.news_sentiment", "evaluate_news_sentiment"),
    "evaluate_short_interest": ("research.short_interest", "evaluate_short_interest"),
    "get_earnings_transcript_snapshot": ("research.earnings_transcripts", "get_earnings_transcript_snapshot"),
    "get_research_runtime_status": ("research.research_orchestrator", "get_research_runtime_status"),
    "get_sec_filing_snapshot": ("research.sec_filings", "get_sec_filing_snapshot"),
    "identify_key_risks": ("research.deep_research", "identify_key_risks"),
    "lookup_cik_for_ticker": ("research.sec_edgar_provider", "lookup_cik_for_ticker"),
    "normalize_filing_item": ("research.sec_filings", "normalize_filing_item"),
    "normalize_transcript_item": ("research.earnings_transcripts", "normalize_transcript_item"),
    "score_earnings_quality": ("research.earnings_transcripts", "score_earnings_quality"),
    "score_filing_risk": ("research.sec_filings", "score_filing_risk"),
    "score_research_conviction": ("research.deep_research", "score_research_conviction"),
    "summarize_earnings_context": ("research.earnings_transcripts", "summarize_earnings_context"),
    "summarize_bear_case": ("research.deep_research", "summarize_bear_case"),
    "summarize_bull_case": ("research.deep_research", "summarize_bull_case"),
    "summarize_filing_context": ("research.sec_filings", "summarize_filing_context"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'research' has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
