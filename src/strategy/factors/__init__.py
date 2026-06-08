"""Factor implementations for A-share quantitative research."""

from src.strategy.factors.momentum import MomentumFactor
from src.strategy.factors.trend import TrendFactor
from src.strategy.factors.mean_reversion import MeanReversionFactor
from src.strategy.factors.value import ValueFactor
from src.strategy.factors.composite import CompositeFactor

__all__ = [
    "MomentumFactor",
    "TrendFactor",
    "MeanReversionFactor",
    "ValueFactor",
    "CompositeFactor",
]
