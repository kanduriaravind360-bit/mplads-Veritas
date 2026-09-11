"""GPU detection with automatic CPU fallback (CLAUDE.md rule 5)."""

from __future__ import annotations

import random
from functools import lru_cache
from typing import Any

import numpy as np


@lru_cache(maxsize=1)
def torch_device() -> str:
    """Return ``"cuda"`` when a working CUDA device is present, else ``"cpu"``."""
    try:
        import torch
    except ImportError:
        return "cpu"
    try:
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


@lru_cache(maxsize=1)
def device_name() -> str:
    """Human-readable name of the compute device, for logs and metrics."""
    if torch_device() != "cuda":
        return "cpu"
    try:
        import torch

        return torch.cuda.get_device_name(0)
    except Exception:
        return "cuda"


def xgb_params(base: dict[str, Any]) -> dict[str, Any]:
    """Add ``device="cuda"`` to XGBoost params when a GPU is available.

    XGBoost raises at ``fit`` time rather than construction time if CUDA is
    unusable, so callers should still wrap training in :func:`fit_with_fallback`.
    """
    params = dict(base)
    params["device"] = torch_device()
    return params


def fit_with_fallback(model_factory, params: dict[str, Any], *fit_args, **fit_kwargs):
    """Fit a model on the GPU, retrying on CPU if CUDA training fails.

    ``model_factory`` is called with the parameter dict and must return an
    unfitted estimator. Returns ``(fitted_model, device_used)``.
    """
    device = params.get("device", "cpu")
    if device == "cuda":
        try:
            model = model_factory(params)
            model.fit(*fit_args, **fit_kwargs)
            return model, "cuda"
        except Exception:
            pass
    cpu_params = dict(params)
    cpu_params["device"] = "cpu"
    model = model_factory(cpu_params)
    model.fit(*fit_args, **fit_kwargs)
    return model, "cpu"


def set_seed(seed: int) -> None:
    """Seed every RNG the pipeline touches (CLAUDE.md rule 5: seed 42)."""
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass
