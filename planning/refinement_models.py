from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


REFINEMENT_PROPOSAL_VERSION = "scan_refinement_proposal_v1"


class RefinementAdjustmentsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    universes: list[str] | None = None
    profiles: list[str] | None = None
    max_tickers: int | None = None
    max_candidates: int | None = None
    profile_weights: dict[str, Any] | None = None
    opportunity_weights: dict[str, Any] | None = None
    option_min_dte: int | None = None
    option_max_dte: int | None = None
    max_option_contracts_per_ticker: int | None = None
    max_option_underlyings: int | None = None


class RefinementProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["stop", "refine"] = "stop"
    reasoning_summary: str = Field(default="", max_length=500)
    adjustments: RefinementAdjustmentsModel = Field(default_factory=RefinementAdjustmentsModel)


def empty_refinement_proposal(action: Literal["stop", "refine"] = "stop", reason: str = "") -> dict:
    return {
        "proposal_version": REFINEMENT_PROPOSAL_VERSION,
        "action": action,
        "reasoning_summary": reason,
        "adjustments": RefinementAdjustmentsModel().model_dump(mode="json"),
    }
