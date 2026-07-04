"""Data source adapters for the daily downloader.

- :class:`TdxSource` — TCP-direct 通达信 (no rate limit, A-share only).
- :class:`TdxOfflineSource` — VIP ZIP download 通达信 (bulk, most reliable).
- :class:`ThsSource` — HTTP 同花顺/东财 via adata + AKShare fallback.
"""

from src.data.sources.base import BaseDataSource, DataSource
from src.data.sources.registry import VALID_SOURCES, create_source, fallback_chain
from src.data.sources.tdx_source import TdxSource
from src.data.sources.tdx_offline_source import TdxOfflineSource
from src.data.sources.ths_source import ThsSource
from src.data.sources.tencent_source import TencentSource

__all__ = [
    "BaseDataSource",
    "DataSource",
    "TdxSource",
    "TdxOfflineSource",
    "ThsSource",
    "TencentSource",
    "VALID_SOURCES",
    "create_source",
    "fallback_chain",
]
