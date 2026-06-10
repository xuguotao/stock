"""Factor implementations for A-share quantitative research."""

from src.strategy.factors.momentum import MomentumFactor
from src.strategy.factors.trend import TrendFactor
from src.strategy.factors.mean_reversion import MeanReversionFactor
from src.strategy.factors.value import ValueFactor
from src.strategy.factors.composite import CompositeFactor
from src.strategy.factors.tail_session import TailSessionFactor
from src.strategy.factors.overnight_momentum import OvernightMomentumFactor

__all__ = [
    "MomentumFactor",
    "TrendFactor",
    "MeanReversionFactor",
    "ValueFactor",
    "CompositeFactor",
    "TailSessionFactor",
    "OvernightMomentumFactor",
]
