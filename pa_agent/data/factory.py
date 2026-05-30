"""Construct :class:`DataSource` implementations by kind id."""
from __future__ import annotations

from pa_agent.data.base import DataSource
from pa_agent.data.market_defaults import GOLD_TV_SYMBOL

DataSourceKind = str  # kept for settings compat; only "tradingview" is active


def default_tradingview_exchange() -> str:
    """Empty string = probe all TV preset venues."""
    return ""


def default_symbol_for_kind(kind: str | None = None) -> str:
    return GOLD_TV_SYMBOL


def create_data_source(kind: str | None = None) -> DataSource:
    """Instantiate a TradingView data source (not connected)."""
    from pa_agent.data.tradingview import TradingViewSource

    return TradingViewSource()
