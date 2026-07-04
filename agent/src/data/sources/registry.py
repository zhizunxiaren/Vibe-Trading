"""Data source registry and fallback chains."""

from __future__ import annotations

from src.data.sources.base import BaseDataSource

VALID_SOURCES = ("tencent", "tdx_offline", "tdx", "ths")

SOURCE_FALLBACK: dict[str, list[str]] = {
    "tencent": ["tdx_offline", "ths"],
    "tdx_offline": ["tencent", "ths"],
    "tdx": ["tdx_offline", "tencent", "ths"],
    "ths": ["tencent", "tdx_offline"],
    "auto": ["tencent", "tdx_offline", "ths"],
}

CAPITAL_FLOW_SOURCE_FALLBACK: dict[str, list[str]] = {
    "tencent": ["ths"],
    "tdx_offline": ["ths"],
    "tdx": ["ths"],
    "ths": [],
    "auto": ["ths"],
}


def create_source(source: str, **kwargs) -> BaseDataSource:
    """Create a data source adapter by name."""
    if source == "tdx":
        from src.data.sources.tdx_source import TdxSource

        return TdxSource(**kwargs)
    if source == "tdx_offline":
        from src.data.sources.tdx_offline_source import TdxOfflineSource

        return TdxOfflineSource(**kwargs)
    if source == "tencent":
        from src.data.sources.tencent_source import TencentSource

        return TencentSource(**kwargs)
    if source == "ths":
        from src.data.sources.ths_source import ThsSource

        return ThsSource(**kwargs)
    raise ValueError(
        f"Unknown data source: {source!r}. Valid sources: {', '.join(VALID_SOURCES)}"
    )


def fallback_chain(source: str, *, data_type: str = "daily") -> list[str]:
    """Return the source fallback chain, including *source* first."""
    fallback_map = (
        CAPITAL_FLOW_SOURCE_FALLBACK
        if data_type == "capital_flow"
        else SOURCE_FALLBACK
    )
    chain = [source]
    for candidate in fallback_map.get(source, []):
        if candidate not in chain:
            chain.append(candidate)
    return chain
