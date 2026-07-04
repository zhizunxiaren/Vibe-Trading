---
name: data-download
category: data-source
description: 盘后数据拉取——批量下载A股+港股日线到本地DuckDB。通达信(TDX,TCP直连)+同花顺(THS,HTTP多源)。按单票增量同步，自动刷新重复bar。
---

# 盘后数据批量下载

每日收盘后全市场日线数据拉取，落盘到 `market_data.duckdb`。

## 数据源

| 源 | 日线 | 15m线 | 资金流向 | 协议 | A股 | 港股 |
|----|------|-------|---------|------|------|------|
| **tdx** (通达信) | ✅ | ✅ | ❌ | TCP (mootdx) | ✅ | ❌ |
| **tdx_offline** (通达信离线包) | ✅ | ❌ | ❌ | HTTP ZIP cache | ✅ | ❌ |
| **tencent** (腾讯财经) | ✅ | ✅ | ❌ | HTTP (stdlib) | ✅ | ❌ |
| **ths** (同花顺) | ✅ | ✅ | ✅ | HTTP (adata+东财+AKShare) | ✅ | ✅ |

- TDX 走 TCP 二进制协议，不会被封 IP。日线+分钟线都走 mootdx。
- `tdx_offline` 下载并缓存通达信 VIP 日线 ZIP，适合全市场日线批量补齐。
- THS 自带 token-bucket + 自适应退避，防止 IP 封禁。资金流向走 AKShare。
- CLI 单项下载默认 `--source auto` 会先用 Tencent；全量 `--mode full`
  会按 stock info → `tdx_offline` 日线 → Tencent 分钟线 → THS 资金流的链路执行。

## 快速开始

```bash
# 进入 agent 目录（必须，因为模块路径）
cd agent

# A股日线 — 通达信 (快, ~8min)
python -m src.data download --market a_share --source tdx

# A股分钟线 — 腾讯财经 (60m/30m/15m)
python -m src.data download --market a_share --source tencent --interval all --from-date 2026-06-24 --to-date 2026-06-24

# A股单个分钟周期
python -m src.data download --market a_share --source tencent --interval 15m --from-date 2026-06-24 --to-date 2026-06-24

# A股日线 — 同花顺 (慢, 安全)
python -m src.data download --market a_share --source ths

# 港股日线
python -m src.data download --market hk_equity --source ths

# 资金流向 (主力净流入/流出)
python -m src.data capital-flow --market a_share --source ths

# 全市场 (A股日线→TDX，A股分钟线→Tencent 60m/30m/15m，港股→THS)
python -m src.data download --market all --source auto

# 试运行 (不写库，只检查)
python -m src.data download --market a_share --source tdx --dry-run

# 指定日期范围
python -m src.data download --market a_share --from-date 2026-06-01 --to-date 2026-06-10

# 查看最近下载记录
python -m src.data status

# 查看各市场最新数据日期
python -m src.data latest
```

## 增量同步

默认增量模式：按每只股票自己的最新日期 + 1 天开始拉取，避免一次部分成功后跳过落后股票。首次运行拉近一年。

日线、分钟线、资金流都使用 upsert/replace 语义。重复运行不会产生冗余数据，供应商修正历史行情、复权数据或资金流时会刷新旧值。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VIBE_TRADING_DATA_DIR` | `<project_root>/data` | 数据目录 |
| `VIBE_TRADING_DATA_DB` | `<data_dir>/market_data.duckdb` | DuckDB 路径 |
| `VIBE_TRADING_DATA_PROXY` | (空) | HTTP 代理 (THS 源) |
| `VIBE_TRADING_DATA_RPS` | `2.0` | HTTP 最大请求/秒 |
| `VIBE_TRADING_DATA_DELAY` | `0.5` | 请求间基础延迟(秒) |
| `VIBE_TRADING_DATA_MAX_DELAY` | `30.0` | 退避上限(秒) |
| `VIBE_TRADING_DATA_BATCH` | `100` | 每批次符号数 |
| `VIBE_TRADING_DATA_BATCH_PAUSE` | `5.0` | 批次间暂停(秒) |
| `VIBE_TRADING_TDX_TIMEOUT` | `30` | TDX TCP 超时(秒) |

## 速率控制

**THS (HTTP) 源自带多层防护，不需要额外配置:**

1. **Token bucket** — 每秒最多 N 个请求 (默认 2)
2. **自适应退避** — 连续出错时延迟指数增长 (0.5s → 1s → 2s → ... 上限 30s)
3. **批次暂停** — 每 100 个符号暂停 5 秒
4. **UA 轮换** — 3 个 User-Agent 循环
5. **代理支持** — 设置 `VIBE_TRADING_DATA_PROXY=http://127.0.0.1:7890`

**TDX (TCP) 源不需要速率控制** — 二进制协议，不会被 ban。

## 存储结构

`market_data.duckdb` (DuckDB):

```
daily_ohlcv     — 日线 OHLCV (code, trade_date) 复合主键
intraday_ohlcv  — 分钟线 OHLCV (code, interval, trade_date, bar_time) 复合主键
capital_flow    — 资金流向 (code, trade_date) 复合主键
stock_info      — 股票主数据
download_log    — 下载审计日志
```

## 依赖

- TDX 源: `pip install mootdx`
- THS 源: `pip install adata`（A股）或已装 `akshare`（A股+港股后备）
- 两者都不装时: `check_available()` 返回 False，工具会跳过
