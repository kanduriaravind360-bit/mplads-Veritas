"""Learning from reviewer verdicts, and the threshold simulator."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from backend.app.deps import Context, reviewer
from backend.app.services import fusion, learning

router = APIRouter(tags=["learning"])


@router.get("/learning")
def learning_panel(ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    return learning.learn(ctx.db)


class SimulationRequest(BaseModel):
    weights: dict[str, float] = Field(default_factory=dict)
    band_percentiles: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> SimulationRequest:
        known = set(fusion.defaults()["weights"])
        unknown = set(self.weights) - known
        if unknown:
            raise ValueError(f"unknown channels: {sorted(unknown)}")
        if any(not 0.0 <= w <= 1.0 for w in self.weights.values()):
            raise ValueError("weights must be between 0 and 1")
        if self.weights and sum(self.weights.values()) <= 0:
            raise ValueError("at least one weight must be above 0")
        merged = {**fusion.defaults()["band_percentiles"], **self.band_percentiles}
        if not 0.5 <= merged["medium"] < merged["high"] < merged["critical"] < 1.0:
            raise ValueError("percentiles must satisfy 0.5 <= medium < high < critical < 1")
        return self


@router.get("/simulator/defaults")
def simulator_defaults(ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    return fusion.defaults()


@router.post("/simulator")
def simulate(body: SimulationRequest, ctx: Context = Depends(reviewer)) -> dict[str, Any]:
    defaults = fusion.defaults()
    weights = {**defaults["weights"], **body.weights}
    if sum(weights.values()) <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "all weights are zero")
    percentiles = {**defaults["band_percentiles"], **body.band_percentiles}
    return fusion.simulate(ctx.db, ctx.scope, weights, percentiles)
