# A股混合自适应量化交易策略 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从零搭建一套完整的A股量化交易策略系统，包含数据获取、四维信号共振、风控过滤、T+1回测执行、绩效分析五大模块。

**Architecture:** 模块化流水线架构。15个Python文件分属5层（data/signals/risk/execution/analysis），通过明确的数据接口串联。数据以pandas DataFrame在层间传递，每层独立可测试。回测引擎逐日循环，精确模拟A股T+1、涨跌停、费率等规则。

**Tech Stack:** Python 3.14, pandas 3.0, numpy 2.4, akshare 1.18, matplotlib 3.10

---

## 文件结构总览

| 文件 | 职责 | 行数估算 |
|------|------|---------|
| `config.py` | 全局参数常量定义 | ~60 |
| `data/__init__.py` | 数据层入口 | ~5 |
| `data/fetcher.py` | akshare数据拉取+本地缓存 | ~200 |
| `data/processor.py` | 数据清洗、复权、ST标记 | ~180 |
| `signals/__init__.py` | 信号层入口 | ~5 |
| `signals/trend.py` | 均线趋势打分 | ~80 |
| `signals/volume.py` | 量能异动打分 | ~80 |
| `signals/fundamental.py` | PE/PB/ROE估值打分 | ~120 |
| `signals/market_timing.py` | 大盘择时总开关 | ~90 |
| `risk/__init__.py` | 风控层入口 | ~5 |
| `risk/position_sizer.py` | 等权仓位分配 | ~70 |
| `risk/stop_loss.py` | 止损止盈检查 | ~100 |
| `execution/__init__.py` | 执行层入口 | ~5 |
| `execution/portfolio.py` | 持仓账簿+净值记录 | ~120 |
| `execution/broker.py` | T+1撮合+费用计算 | ~150 |
| `analysis/__init__.py` | 分析层入口 | ~5 |
| `analysis/metrics.py` | 绩效指标计算 | ~120 |
| `analysis/reporter.py` | 图表+文字报告 | ~150 |
| `main.py` | 主入口编排全流程 | ~180 |

---

### Task 1: 创建项目骨架 + config.py

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/config.py`
- Create: 所有 `__init__.py` 空文件

- [ ] **Step 1: 创建所有目录和 __init__.py**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy"
mkdir -p data signals risk execution analysis output cache
touch data/__init__.py signals/__init__.py risk/__init__.py execution/__init__.py analysis/__init__.py
```

- [ ] **Step 2: 编写 config.py**

```python
"""
全局配置参数 — 所有模块的统一参数来源。
修改策略参数只需改这个文件，不需要深入各个模块。
"""
from datetime import datetime

# ===== 回测时间区间 =====
BACKTEST_START = "2021-06-01"
BACKTEST_END   = "2026-05-28"

# ===== 数据源 =====
CACHE_DIR = "cache"
OUTPUT_DIR = "output"
BENCHMARK_INDEX = "000300"  # 沪深300作为基准
MARKET_INDEX = "000300"     # 大盘择时参考指数
SHANGHAI_INDEX = "000001"   # 上证指数备用

# ===== 选股池 =====
STOCK_POOL_INDICES = ["000300", "000905"]  # 沪深300 + 中证500
MIN_LISTING_DAYS = 60  # 上市不足60天剔除
EXCLUDE_ST_PREFIX = ("ST", "*ST")

# ===== 信号评分参数 =====
SIGNAL_THRESHOLD = 24  # 四维总分阈值（满分40，需≥24分触发买入）
EMA_SHORT, EMA_MID, EMA_LONG = 20, 60, 120
VOLUME_RATIO_THRESHOLD = 1.5       # 放量倍数
VOLUME_CONSECUTIVE_DAYS = 3        # 连续放量天数
MOMENTUM_GAIN_THRESHOLD = 0.02     # 量价配合涨幅阈值
TREND_DEVIATION_MAX = 0.30         # 均线偏离上限
PB_MAX = 3.0
ROE_MIN = 0.10
PE_SECTOR_DISCOUNT = 0.80         # PE需低于行业中位数的80%

# ===== 大盘择时 =====
PANIC_DROP_DAYS = 5
PANIC_DROP_THRESHOLD = -0.05  # 近5日跌幅超5%强制空仓
FULL_POSITION_COUNT = 8        # 满仓最多持仓数
HALF_POSITION_COUNT = 4        # 半仓最多持仓数
MAX_SINGLE_POSITION_PCT = 0.20 # 单只最大仓位20%

# ===== 风控 =====
HARD_STOP_LOSS = -0.08          # -8%硬止损
TRAILING_STOP_DRAWDOWN = -0.06  # 从最高点回撤6%移动止盈
TIME_STOP_DAYS = 40             # 持仓超40天无利润清仓

# ===== 费率 =====
COMMISSION_RATE = 0.00025   # 佣金万分之2.5
COMMISSION_MIN = 5.0        # 最低佣金5元
STAMP_TAX_RATE = 0.001     # 印花税千分之1（仅卖出）
LOT_SIZE = 100             # 1手=100股

# ===== 运行控制 =====
FETCH_BATCH_SIZE = 25        # 每批拉取股票数
FETCH_BATCH_SLEEP = 0.5      # 批次间隔秒数
API_TIMEOUT = 30             # API超时秒数
DAILY_BENCHMARK_CODE = "000300"  # 沪深300代码（akshare格式）
```

- [ ] **Step 3: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "import config; print(f'回测区间: {config.BACKTEST_START} ~ {config.BACKTEST_END}'); print('config OK')"
```

预期输出：`回测区间: 2021-06-01 ~ 2026-05-28` 和 `config OK`

---

### Task 2: data/fetcher.py — 数据拉取与缓存

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/data/fetcher.py`

- [ ] **Step 1: 编写 fetcher.py**

```python
"""数据拉取模块：从akshare获取A股日线数据，本地CSV缓存，批量拉取防限流。"""
import os
import time
import pandas as pd
import akshare as ak
from config import (
    CACHE_DIR, FETCH_BATCH_SIZE, FETCH_BATCH_SLEEP,
    API_TIMEOUT, STOCK_POOL_INDICES, BACKTEST_START, BACKTEST_END,
    BENCHMARK_INDEX, SHANGHAI_INDEX, MIN_LISTING_DAYS, EXCLUDE_ST_PREFIX,
)

os.makedirs(CACHE_DIR, exist_ok=True)


def _safe_ak_call(func, *args, **kwargs):
    """统一异常包装：超时、网络错误均捕获，返回空DataFrame。"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"  [WARN] akshare调用失败 {func.__name__}: {e}")
        return pd.DataFrame()


def get_index_constituents(index_code: str) -> list[str]:
    """获取指数成分股列表。

    Args:
        index_code: '000300'(沪深300) 或 '000905'(中证500)

    Returns:
        股票代码列表，如 ['000001', '000002', ...]
    """
    cache_file = os.path.join(CACHE_DIR, f"constituents_{index_code}.csv")
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, dtype={"code": str})
        return df["code"].tolist()

    try:
        if index_code == "000300":
            df = ak.index_stock_cons_csindex(symbol="000300")
        else:
            df = ak.index_stock_cons_csindex(symbol="000905")
        codes = df["成分券代码"].astype(str).str.zfill(6).tolist()
        pd.DataFrame({"code": codes}).to_csv(cache_file, index=False)
        print(f"  获取 {index_code} 成分股 {len(codes)} 只")
        return codes
    except Exception as e:
        print(f"  [ERROR] 获取成分股失败 {index_code}: {e}")
        return []


def build_stock_pool() -> list[str]:
    """构建选股池：合并指数成分股，去重，过滤ST和上市不足新股。"""
    all_codes = []
    for idx in STOCK_POOL_INDICES:
        codes = get_index_constituents(idx)
        all_codes.extend(codes)
    all_codes = list(dict.fromkeys(all_codes))  # 去重保序
    print(f"合并成分股 {len(all_codes)} 只（去重后）")

    # 剔除ST
    filtered = []
    for code in all_codes:
        try:
            info = _safe_ak_call(ak.stock_individual_info_em, symbol=code)
            if info is None or info.empty:
                continue
            name = str(info.loc[info["item"] == "股票简称", "value"].values[0]) if not info.empty else ""
            if name.startswith(EXCLUDE_ST_PREFIX):
                continue
            listed_date = info.loc[info["item"] == "上市时间", "value"].values[0]
            if pd.to_datetime(listed_date) > pd.Timestamp(BACKTEST_START) - pd.Timedelta(days=MIN_LISTING_DAYS):
                continue
            filtered.append(code)
        except Exception:
            continue
    print(f"过滤ST/新股后: {len(filtered)} 只")
    return filtered


def fetch_one_stock(code: str) -> pd.DataFrame | None:
    """拉取单只股票日线数据（后复权），缓存到CSV。

    Returns:
        DataFrame columns: date, open, high, low, close, volume, amount
        失败返回None
    """
    cache_file = os.path.join(CACHE_DIR, f"{code}.csv")

    # 检查缓存
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, parse_dates=["date"])
        last_date = df["date"].max()
        if pd.Timestamp(last_date) >= pd.Timestamp.now() - pd.Timedelta(days=7):
            return df
        # 增量更新：拉取最近数据
        start_date = (pd.Timestamp(last_date) - pd.Timedelta(days=10)).strftime("%Y%m%d")
    else:
        start_date = pd.Timestamp(BACKTEST_START).strftime("%Y%m%d")

    end_date = pd.Timestamp.now().strftime("%Y%m%d")

    try:
        raw = _safe_ak_call(
            ak.stock_zh_a_hist,
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date,
            adjust="hfq"  # 后复权
        )
        if raw is None or raw.empty:
            return _load_cache_or_none(cache_file)

        df = raw.rename(columns={
            "日期": "date", "开盘": "open", "最高": "high",
            "最低": "low", "收盘": "close", "成交量": "volume",
            "成交额": "amount",
        })
        df["date"] = pd.to_datetime(df["date"])
        keep_cols = ["date", "open", "high", "low", "close", "volume", "amount"]
        df = df[[c for c in keep_cols if c in df.columns]]

        # 合并已有缓存
        if os.path.exists(cache_file):
            old = pd.read_csv(cache_file, parse_dates=["date"])
            df = pd.concat([old, df]).drop_duplicates("date").sort_values("date")

        df.to_csv(cache_file, index=False)
        return df
    except Exception as e:
        print(f"  [ERROR] 拉取 {code} 失败: {e}")
        return _load_cache_or_none(cache_file)


def _load_cache_or_none(cache_file: str) -> pd.DataFrame | None:
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, parse_dates=["date"])
    return None


def fetch_all_stocks(codes: list[str]) -> dict[str, pd.DataFrame]:
    """分批拉取全量数据。

    Returns:
        {code: DataFrame} 字典，拉取失败的code不会出现在结果中
    """
    result = {}
    total = len(codes)
    for i in range(0, total, FETCH_BATCH_SIZE):
        batch = codes[i:i + FETCH_BATCH_SIZE]
        print(f"  拉取批次 [{i+1}-{min(i+FETCH_BATCH_SIZE, total)}] / {total}")
        for code in batch:
            df = fetch_one_stock(code)
            if df is not None and not df.empty:
                result[code] = df
        if i + FETCH_BATCH_SIZE < total:
            time.sleep(FETCH_BATCH_SLEEP)
    print(f"  成功拉取 {len(result)} / {total} 只股票数据")
    return result


def fetch_index_data(code: str) -> pd.DataFrame | None:
    """拉取指数日线数据（如沪深300=000300）。"""
    cache_file = os.path.join(CACHE_DIR, f"index_{code}.csv")
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, parse_dates=["date"])

    try:
        df = ak.stock_zh_index_daily(symbol=f"sh{code}" if code.startswith("000") else f"sz{code}")
        if df is None or df.empty:
            return None
        df = df.rename(columns={"date": "date", "open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        keep_cols = ["date", "open", "high", "low", "close", "volume"]
        df = df[[c for c in keep_cols if c in df.columns]]
        df.to_csv(cache_file, index=False)
        return df
    except Exception as e:
        print(f"  [ERROR] 拉取指数 {code} 失败: {e}")
        return None
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
from data.fetcher import build_stock_pool
codes = build_stock_pool()
print(f'选股池: {len(codes)} 只')
" 2>&1 | head -20
```

预期输出：选股池约 600-700 只（首次运行时需要网络）

---

### Task 3: data/processor.py — 数据清洗与预处理

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/data/processor.py`

- [ ] **Step 1: 编写 processor.py**

```python
"""数据清洗模块：复权对齐、停牌/涨跌停标记、异常值处理。"""
import pandas as pd
import numpy as np
from config import BACKTEST_START, BACKTEST_END


def clean_stock_data(df: pd.DataFrame, code: str) -> pd.DataFrame | None:
    """清洗单只股票数据。

    处理内容：
    1. 过滤回测区间外的数据
    2. 标记停牌日（volume=0）
    3. 标记涨跌停日（用于判断是否可交易）
    4. 填充缺失的EMA指标列
    5. 去重、排序

    Returns:
        清洗后DataFrame，数据不足返回None
    """
    if df is None or df.empty:
        return None

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date")

    # 裁剪回测区间
    start = pd.Timestamp(BACKTEST_START) - pd.Timedelta(days=150)  # 预留计算EMA的空间
    end = pd.Timestamp(BACKTEST_END)
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    if len(df) < 120:
        return None  # 数据太少，无法计算120日均线

    # 使用close填充缺失的OHLC
    for col in ["open", "high", "low"]:
        if col not in df.columns:
            df[col] = df["close"]

    # 计算涨跌幅和涨跌停标记
    df["pct_change"] = df["close"].pct_change()
    df["is_suspended"] = df["volume"] <= 0

    # 涨跌停判断（基于前一日收盘价的±10%，科创板/创业板±20%）
    # 简化处理：统一按±9.5%以上视为涨跌停（考虑四舍五入）
    df["limit_up"] = df["pct_change"] >= 0.095
    df["limit_down"] = df["pct_change"] <= -0.095

    # 计算EMA均线
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
    df["ema120"] = df["close"].ewm(span=120, adjust=False).mean()

    # 计算成交量均线
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # 计算量比（当日量/5日均量）
    df["vol_ratio"] = df["volume"] / df["volume"].rolling(5).mean().replace(0, np.nan)

    # 删除预计算区域的NaN行
    df = df.dropna(subset=["ema20", "ema60", "ema120"])

    return df


def clean_index_data(df: pd.DataFrame) -> pd.DataFrame | None:
    """清洗指数数据。"""
    if df is None or df.empty:
        return None

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date")

    start = pd.Timestamp(BACKTEST_START) - pd.Timedelta(days=150)
    end = pd.Timestamp(BACKTEST_END)
    df = df[(df["date"] >= start) & (df["date"] <= end)]

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema60"] = df["close"].ewm(span=60, adjust=False).mean()
    df["ema120"] = df["close"].ewm(span=120, adjust=False).mean()
    df["pct_change"] = df["close"].pct_change()

    return df.dropna(subset=["ema20", "ema60", "ema120"])


def process_all_stocks(raw_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """批量清洗所有股票数据。

    Returns:
        {code: cleaned_DataFrame}，清洗失败的code会被剔除
    """
    cleaned = {}
    for code, df in raw_data.items():
        try:
            result = clean_stock_data(df, code)
            if result is not None:
                cleaned[code] = result
        except Exception as e:
            print(f"  [WARN] 清洗 {code} 失败: {e}")
    print(f"  清洗完成: {len(cleaned)} / {len(raw_data)} 只股票数据可用")
    return cleaned


def get_trading_dates(data_dict: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """从数据中提取所有交易日期（取所有股票日期并集的排序去重）。"""
    all_dates = pd.DatetimeIndex([])
    for df in data_dict.values():
        all_dates = all_dates.union(df["date"])
    return all_dates.sort_values()


def get_stock_on_date(data_dict: dict[str, pd.DataFrame], code: str, date: pd.Timestamp) -> pd.Series | None:
    """获取某只股票在某天的行情快照。"""
    df = data_dict.get(code)
    if df is None:
        return None
    row = df[df["date"] == date]
    return row.iloc[0] if not row.empty else None
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
from data.processor import clean_stock_data
print('processor module OK')
"
```

预期输出：`processor module OK`

---

### Task 4: signals/trend.py — 均线趋势信号

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/signals/trend.py`

- [ ] **Step 1: 编写 trend.py**

```python
"""均线趋势信号：EMA多头排列 + 金叉检测，输出0-10分。"""
import pandas as pd
import numpy as np


def score_trend(stock_df: pd.DataFrame, idx: int) -> float:
    """计算单只股票在指定日期的趋势得分。

    Args:
        stock_df: 已清洗的股票数据（需含 ema20/ema60/ema120/close 列）
        idx: 目标日期在DataFrame中的行索引

    Returns:
        0-10分，越高趋势越强
    """
    if idx < 2:
        return 0.0

    row = stock_df.iloc[idx]
    prev_row = stock_df.iloc[idx - 1]
    prev2_row = stock_df.iloc[idx - 2]

    ema20 = row["ema20"]
    ema60 = row["ema60"]
    ema120 = row["ema120"]
    close = row["close"]

    score = 0.0

    # 1. 三线多头排列：EMA20 > EMA60 > EMA120 (+3)
    if ema20 > ema60 > ema120:
        score += 3.0

    # 2. EMA20上穿EMA60（金叉，近3日内发生）(+3)
    current_cross = ema20 > ema60
    prev_cross = prev_row["ema20"] > prev_row["ema60"]
    prev2_cross = prev2_row["ema20"] > prev2_row["ema60"]
    # 当前是多头，且前2日内至少有一日仍是空头（即3日内发生过金叉）
    if current_cross and (not prev_cross or not prev2_cross):
        score += 3.0

    # 3. 收盘价在EMA20之上，且EMA20斜率向上 (+2)
    if close > ema20 and ema20 > prev_row["ema20"]:
        score += 2.0

    # 4. 偏离60日均线超过30% (-2)
    if ema60 > 0:
        deviation = (close - ema60) / ema60
        if deviation > 0.30:
            score -= 2.0

    # 归一化到0-10（原始分数范围-2到8）
    normalized = (score + 2) / 10 * 10  # 映射到 0-10
    return max(0.0, min(10.0, normalized))
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
import pandas as pd
import numpy as np
from signals.trend import score_trend

# 构造模拟数据验证
df = pd.DataFrame({
    'ema20':  [10, 10.5, 11.0],
    'ema60':  [9,   9.2,  9.5],
    'ema120': [8,   8.1,  8.3],
    'close':  [10.5, 11.0, 11.5],
})
# 三线多头排列 + 价在EMA20上 + EMA20斜率向上 = 5+2 = 7/8 = 归一化 8.75
score = score_trend(df, 2)
print(f'趋势得分: {score:.1f} (预期约8.8)')
print('trend OK')
"
```

---

### Task 5: signals/volume.py — 量能异动信号

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/signals/volume.py`

- [ ] **Step 1: 编写 volume.py**

```python
"""量能异动信号：放量突破 + 量堆 + 量价配合，输出0-10分。"""
import pandas as pd


def score_volume(stock_df: pd.DataFrame, idx: int) -> float:
    """计算单只股票在指定日期的量能得分。

    Args:
        stock_df: 需含 volume/vol_ma20/vol_ratio/pct_change 列
        idx: 目标日期行索引

    Returns:
        0-10分
    """
    if idx < 5:
        return 0.0

    row = stock_df.iloc[idx]
    volume = row["volume"]
    vol_ma20 = row["vol_ma20"]
    vol_ratio = row["vol_ratio"]
    pct_change = row["pct_change"]

    score = 0.0

    # 1. 放量：当日量 > 20日均量 * 1.5 (+4)
    if pd.notna(vol_ma20) and vol_ma20 > 0 and volume > vol_ma20 * 1.5:
        score += 4.0

    # 2. 量堆：连续3日量能递增 (+3)
    vols = [stock_df.iloc[idx - i]["volume"] for i in range(3)]
    if vols[0] > vols[1] > vols[2]:
        score += 3.0

    # 3. 量价配合：涨幅 > 2% 且量比 > 1.2 (+3)
    if pd.notna(pct_change) and pct_change > 0.02 and pd.notna(vol_ratio) and vol_ratio > 1.2:
        score += 3.0

    return min(10.0, score)
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
import pandas as pd
from signals.volume import score_volume
df = pd.DataFrame({
    'volume':    [100, 120, 150, 200, 300, 500],
    'vol_ma20':  [150, 150, 155, 160, 165, 170],
    'vol_ratio': [1.0, 1.1, 1.2, 1.3, 1.5, 2.0],
    'pct_change':[0.0, 0.01, 0.01, 0.02, 0.03, 0.04],
})
s = score_volume(df, 5)
print(f'量能得分: {s} (预期接近10)')
print('volume OK')
"
```

---

### Task 6: signals/fundamental.py — 估值过滤信号

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/signals/fundamental.py`

- [ ] **Step 1: 编写 fundamental.py**

```python
"""估值过滤信号：PE/PB/ROE三维评估，输出0-10分。"""
import pandas as pd
import akshare as ak
from config import PB_MAX, ROE_MIN, PE_SECTOR_DISCOUNT


def _get_fundamentals(codes: list[str]) -> pd.DataFrame:
    """批量获取股票基本面数据。

    PE/PB通过akshare的stock_zh_a_spot_em()一次获取全市场数据，
    ROE和行业通过stock_individual_info_em逐只获取（仅需获取一次，缓存后复用）。
    逐只请求控制在50只/批，避免限流。
    """
    codes_set = set(codes)
    records = []

    # 批量获取PE/PB（全市场一次调用，极快）
    try:
        spot = ak.stock_zh_a_spot_em()
        if spot is not None and not spot.empty:
            spot["代码"] = spot["代码"].astype(str)
            spot = spot[spot["代码"].isin(codes_set)]
            for _, r in spot.iterrows():
                records.append({
                    "code": r["代码"],
                    "pe": pd.to_numeric(r.get("市盈率-动态"), errors="coerce"),
                    "pb": pd.to_numeric(r.get("市净率"), errors="coerce"),
                })
    except Exception as e:
        print(f"  [WARN] 批量获取PE/PB失败: {e}")

    df = pd.DataFrame(records) if records else pd.DataFrame(columns=["code", "pe", "pb"])

    # 逐只获取ROE和行业（分批，每批50只）
    roe_sector_records = []
    all_codes = list(codes_set)
    for i in range(0, len(all_codes), 50):
        batch = all_codes[i:i+50]
        for code in batch:
            try:
                info = ak.stock_individual_info_em(symbol=code)
                if info is None or info.empty:
                    continue
                row = {"code": code}
                for _, r in info.iterrows():
                    if r["item"] == "净资产收益率":
                        row["roe"] = pd.to_numeric(r["value"], errors="coerce")
                    elif r["item"] == "行业":
                        row["sector"] = r["value"]
                roe_sector_records.append(row)
            except Exception:
                continue

    right_df = pd.DataFrame(roe_sector_records)
    if not right_df.empty and not df.empty:
        df = df.merge(right_df, on="code", how="left")
    elif not right_df.empty:
        df = right_df

    return df


def compute_sector_pe_medians(fund_df: pd.DataFrame) -> dict[str, float]:
    """计算各行业PE中位数。

    Returns:
        {sector_name: median_pe}
    """
    if "sector" not in fund_df.columns or "pe" not in fund_df.columns:
        return {}
    valid = fund_df.dropna(subset=["sector", "pe"])
    valid = valid[valid["pe"] > 0]
    return valid.groupby("sector")["pe"].median().to_dict()


def score_fundamental(code: str, fund_df: pd.DataFrame, sector_pe: dict[str, float]) -> float:
    """计算单只股票的估值得分。

    Args:
        code: 股票代码
        fund_df: 所有股票的基本面DataFrame
        sector_pe: 行业PE中位数映射

    Returns:
        0-10分
    """
    row = fund_df[fund_df["code"] == code]
    if row.empty:
        return 5.0  # 无数据给中性分

    row = row.iloc[0]
    score = 0.0

    pe = row.get("pe")
    pb = row.get("pb")
    roe = row.get("roe")
    sector = row.get("sector")

    # 1. PE低估 (+4)
    if pd.notna(pe) and pe > 0 and sector and sector in sector_pe:
        median = sector_pe[sector]
        if median > 0 and pe < median * PE_SECTOR_DISCOUNT:
            score += 4.0

    # 2. PB合理 (+3)
    if pd.notna(pb) and 0 < pb < PB_MAX:
        score += 3.0

    # 3. ROE过关 (+3) — 从akshare返回的值是百分比（如15表示15%）
    if pd.notna(roe) and roe > 0 and roe / 100 > ROE_MIN:
        score += 3.0

    return score
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
import pandas as pd
from signals.fundamental import score_fundamental
fund_df = pd.DataFrame([{
    'code': '000001', 'pe': 8.0, 'pb': 1.2, 'roe': 15.0, 'sector': '银行'
}])
sector_pe = {'银行': 10.0}
s = score_fundamental('000001', fund_df, sector_pe)
print(f'估值得分: {s} (PE低于银行中位数80%, PB合理, ROE>10% → 预期10)')
print('fundamental OK')
"
```

---

### Task 7: signals/market_timing.py — 大盘择时总开关

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/signals/market_timing.py`

- [ ] **Step 1: 编写 market_timing.py**

```python
"""大盘择时模块：根据沪深300指数状态决定仓位级别。"""
import pandas as pd
from config import PANIC_DROP_DAYS, PANIC_DROP_THRESHOLD, FULL_POSITION_COUNT, HALF_POSITION_COUNT

EMPTY, HALF, FULL = "empty", "half", "full"


def get_market_state(index_df: pd.DataFrame, date: pd.Timestamp) -> tuple[str, int]:
    """判断指定日期的大盘状态。

    Args:
        index_df: 已清洗的沪深300指数数据（需含 ema20/ema60/ema120/pct_change）
        date: 目标日期

    Returns:
        (state, max_positions)
        state: "empty" | "half" | "full"
        max_positions: 允许的最大持仓数
    """
    row = index_df[index_df["date"] == date]
    if row.empty:
        return EMPTY, 0

    row = row.iloc[0]
    ema20 = row["ema20"]
    ema60 = row["ema60"]
    ema120 = row["ema120"]

    # 检查近5日累计跌幅
    recent = index_df[index_df["date"] <= date].tail(PANIC_DROP_DAYS)
    if len(recent) >= PANIC_DROP_DAYS:
        cumulative = (recent["close"].iloc[-1] / recent["close"].iloc[0]) - 1
        if cumulative <= PANIC_DROP_THRESHOLD:
            return EMPTY, 0

    # EMA判断
    if pd.isna(ema20) or pd.isna(ema60):
        return EMPTY, 0

    if ema20 < ema60:
        return EMPTY, 0  # 短期空头

    if ema20 > ema60 > ema120:
        return FULL, FULL_POSITION_COUNT  # 三线多头

    # ema20 > ema60 但 ema60 <= ema120
    return HALF, HALF_POSITION_COUNT
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
import pandas as pd
from signals.market_timing import get_market_state, FULL, HALF, EMPTY
# 模拟多头排列
idx_df = pd.DataFrame([{
    'date': pd.Timestamp('2024-01-15'),
    'ema20': 3500, 'ema60': 3400, 'ema120': 3300, 'close': 3550
}])
state, max_pos = get_market_state(idx_df, pd.Timestamp('2024-01-15'))
print(f'三线多头 → {state}, 最大持仓{max_pos}只 (预期full, 8)')
print('market_timing OK')
"
```

---

### Task 8: risk/stop_loss.py + risk/position_sizer.py — 风控模块

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/risk/stop_loss.py`
- Create: `C:/Users/PCB/Desktop/quant-strategy/risk/position_sizer.py`

- [ ] **Step 1: 编写 stop_loss.py**

```python
"""止损止盈模块：检查持仓是否触发退出条件。"""
import pandas as pd
from config import HARD_STOP_LOSS, TRAILING_STOP_DRAWDOWN, TIME_STOP_DAYS


def check_exits(
    positions: list[dict],
    stock_data: dict[str, pd.DataFrame],
    date: pd.Timestamp,
) -> list[dict]:
    """检查所有持仓，返回需要卖出的列表。

    Args:
        positions: 当前持仓列表，每项 {code, entry_date, entry_price, highest_price, quantity}
        stock_data: {code: DataFrame} 全量数据
        date: 当前日期

    Returns:
        需卖出的持仓列表 [{code, reason}]
    """
    exits = []
    for pos in positions:
        code = pos["code"]
        df = stock_data.get(code)
        if df is None:
            continue

        row = df[df["date"] == date]
        if row.empty:
            continue
        current_price = row.iloc[0]["close"]
        if pd.isna(current_price) or current_price <= 0:
            continue

        entry_price = pos["entry_price"]
        pnl_pct = (current_price - entry_price) / entry_price

        # 硬止损
        if pnl_pct <= HARD_STOP_LOSS:
            exits.append({"code": code, "reason": f"硬止损 ({pnl_pct:.1%})"})
            continue

        # 移动止盈
        high = max(pos.get("highest_price", entry_price), current_price)
        pos["highest_price"] = high
        drawdown_from_high = (current_price - high) / high
        if high > entry_price and drawdown_from_high <= TRAILING_STOP_DRAWDOWN:
            exits.append({"code": code, "reason": f"移动止盈 (回撤{drawdown_from_high:.1%})"})
            continue

        # 时间止损
        days_held = (date - pos["entry_date"]).days
        if days_held > TIME_STOP_DAYS and pnl_pct <= 0:
            exits.append({"code": code, "reason": f"时间止损 (持仓{days_held}天)"})

    return exits
```

- [ ] **Step 2: 编写 position_sizer.py**

```python
"""仓位管理模块：计算买入数量和单只仓位。"""
import math
from config import LOT_SIZE, MAX_SINGLE_POSITION_PCT


def calculate_buy_quantity(
    available_cash: float,
    price: float,
    num_positions: int,
    total_nav: float,
) -> int:
    """计算买入股数（等权分配，取整手）。

    Args:
        available_cash: 可用现金
        price: 当前股价
        num_positions: 目标持仓数
        total_nav: 总净值

    Returns:
        股数（整手向下取整）
    """
    if num_positions <= 0 or price <= 0:
        return 0

    # 等权分配
    equal_share = available_cash / num_positions

    # 单只仓位上限约束
    max_per_stock = total_nav * MAX_SINGLE_POSITION_PCT

    buy_amount = min(equal_share, max_per_stock)
    shares = int(buy_amount / price / LOT_SIZE) * LOT_SIZE

    return shares
```

- [ ] **Step 3: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
from risk.position_sizer import calculate_buy_quantity
qty = calculate_buy_quantity(100000, 25.0, 8, 200000)
print(f'可用10万, 股价25, 8只等权, 净值20万 → {qty}股 (预期整手)')
print('risk OK')
"
```

---

### Task 9: execution/portfolio.py — 持仓账簿

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/execution/portfolio.py`

- [ ] **Step 1: 编写 portfolio.py**

```python
"""持仓账簿：跟踪现金、持仓、净值变化。"""
import pandas as pd


class Portfolio:
    """持仓与资金管理账本。"""

    def __init__(self, initial_nav: float = 1.0):
        self.initial_nav = initial_nav
        self.cash = initial_nav
        self.positions: list[dict] = []  # [{code, entry_date, entry_price, highest_price, quantity}]
        self.nav_history: list[dict] = []  # [{date, nav, cash, position_value}]
        self.trades: list[dict] = []       # [{date, code, action, price, quantity, amount, fee}]

    def total_nav(self, stock_data: dict[str, pd.DataFrame], date: pd.Timestamp) -> float:
        """计算当日总净值 = 现金 + 持仓市值。"""
        position_value = 0.0
        for pos in self.positions:
            code = pos["code"]
            df = stock_data.get(code)
            if df is None:
                continue
            row = df[df["date"] == date]
            if not row.empty:
                position_value += row.iloc[0]["close"] * pos["quantity"]
        return self.cash + position_value

    def record_nav(self, date: pd.Timestamp, stock_data: dict[str, pd.DataFrame]):
        """记录每日净值快照。"""
        pos_val = 0.0
        for pos in self.positions:
            df = stock_data.get(pos["code"])
            if df is not None:
                row = df[df["date"] == date]
                if not row.empty:
                    pos_val += row.iloc[0]["close"] * pos["quantity"]

        self.nav_history.append({
            "date": date,
            "nav": self.cash + pos_val,
            "cash": self.cash,
            "position_value": pos_val,
            "position_count": len(self.positions),
        })

    def add_position(self, code: str, date: pd.Timestamp, price: float, quantity: int):
        """记录买入持仓。"""
        self.positions.append({
            "code": code,
            "entry_date": date,
            "entry_price": price,
            "highest_price": price,
            "quantity": quantity,
        })

    def remove_position(self, code: str):
        """移除卖出持仓。"""
        self.positions = [p for p in self.positions if p["code"] != code]

    def record_trade(self, date, code, action, price, quantity, amount, fee):
        """记录交易。"""
        self.trades.append({
            "date": date, "code": code, "action": action,
            "price": price, "quantity": quantity, "amount": amount, "fee": fee,
        })

    def get_nav_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.nav_history)

    def get_trades_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades)
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
from execution.portfolio import Portfolio
p = Portfolio(1.0)
print(f'初始净值: {p.total_nav({}, pd.Timestamp.now())}')
print('portfolio OK')
"
```

---

### Task 10: execution/broker.py — 回测撮合引擎

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/execution/broker.py`

- [ ] **Step 1: 编写 broker.py**

```python
"""回测撮合引擎：T+1执行、涨跌停限制、费用计算。"""
import pandas as pd
import numpy as np
from config import (
    COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE, LOT_SIZE,
    BACKTEST_START, BACKTEST_END,
)


def compute_fee(amount: float, is_sell: bool) -> float:
    """计算交易费用。

    Args:
        amount: 成交金额
        is_sell: 是否卖出（卖出需印花税）

    Returns:
        总费用
    """
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    stamp = amount * STAMP_TAX_RATE if is_sell else 0.0
    return commission + stamp


def can_buy(stock_df: pd.DataFrame, date: pd.Timestamp) -> bool:
    """判断当日是否可以买入（非涨停、非停牌）。"""
    row = stock_df[stock_df["date"] == date]
    if row.empty:
        return False
    row = row.iloc[0]
    if row.get("is_suspended", False):
        return False
    if row.get("limit_up", False):
        return False
    return True


def can_sell(stock_df: pd.DataFrame, date: pd.Timestamp) -> bool:
    """判断当日是否可以卖出（非跌停、非停牌）。"""
    row = stock_df[stock_df["date"] == date]
    if row.empty:
        return False
    row = row.iloc[0]
    if row.get("is_suspended", False):
        return False
    if row.get("limit_down", False):
        return False
    return True


def execute_buy(
    portfolio, code: str, date: pd.Timestamp,
    stock_data: dict[str, pd.DataFrame], max_positions: int,
    signal_score: float,
) -> bool:
    """执行买入（T+1=次日开盘价成交）。

    Returns:
        True如果成功买入
    """
    df = stock_data.get(code)
    if df is None:
        return False

    # 找到下一个交易日
    next_dates = df[df["date"] > date]["date"]
    if next_dates.empty:
        return False
    next_date = next_dates.iloc[0]

    if not can_buy(df, next_date):
        return False

    row = df[df["date"] == next_date].iloc[0]
    price = row["open"]
    if pd.isna(price) or price <= 0:
        return False

    # 仓位已满
    if len(portfolio.positions) >= max_positions:
        return False

    # 计算买入数量
    remaining_slots = max_positions - len(portfolio.positions)
    if remaining_slots <= 0:
        return False

    from risk.position_sizer import calculate_buy_quantity
    nav = portfolio.total_nav(stock_data, date)
    qty = calculate_buy_quantity(portfolio.cash, price, remaining_slots, nav)

    if qty < LOT_SIZE:
        return False

    amount = price * qty
    fee = compute_fee(amount, is_sell=False)
    total_cost = amount + fee

    if total_cost > portfolio.cash:
        # 资金不足，减少1手重试
        qty -= LOT_SIZE
        if qty < LOT_SIZE:
            return False
        amount = price * qty
        fee = compute_fee(amount, is_sell=False)
        total_cost = amount + fee
        if total_cost > portfolio.cash:
            return False

    portfolio.cash -= total_cost
    portfolio.add_position(code, next_date, price, qty)
    portfolio.record_trade(next_date, code, "BUY", price, qty, amount, fee)
    return True


def execute_sell(
    portfolio, code: str, date: pd.Timestamp,
    stock_data: dict[str, pd.DataFrame], reason: str = "",
) -> bool:
    """执行卖出（T+1=次日开盘价成交）。"""
    pos = next((p for p in portfolio.positions if p["code"] == code), None)
    if pos is None:
        return False

    df = stock_data.get(code)
    if df is None:
        return False

    next_dates = df[df["date"] > date]["date"]
    if next_dates.empty:
        return False
    next_date = next_dates.iloc[0]

    if not can_sell(df, next_date):
        return False

    row = df[df["date"] == next_date].iloc[0]
    price = row["open"]
    if pd.isna(price) or price <= 0:
        return False

    qty = pos["quantity"]
    amount = price * qty
    fee = compute_fee(amount, is_sell=True)
    net_amount = amount - fee

    portfolio.cash += net_amount
    portfolio.remove_position(code)
    portfolio.record_trade(next_date, code, "SELL", price, qty, amount, fee)
    return True


def run_backtest(
    stock_data: dict[str, pd.DataFrame],
    index_df: pd.DataFrame,
    fund_df: pd.DataFrame,
    sector_pe: dict[str, float],
    trading_dates: pd.DatetimeIndex,
    portfolio,
) -> dict:
    """主回测循环。

    Returns:
        回测结果字典 {nav_df, trades_df, signals_log}
    """
    from signals.market_timing import get_market_state
    from signals.trend import score_trend
    from signals.volume import score_volume
    from signals.fundamental import score_fundamental
    from risk.stop_loss import check_exits

    signals_log = []
    total_dates = len(trading_dates)

    for i, date in enumerate(trading_dates):
        if date < pd.Timestamp(BACKTEST_START) or date > pd.Timestamp(BACKTEST_END):
            continue

        try:
            # Step 1: 检查止损止盈
            exits = check_exits(portfolio.positions, stock_data, date)
            for exit_order in exits:
                execute_sell(portfolio, exit_order["code"], date, stock_data, exit_order["reason"])

            # Step 2: 大盘择时
            state, max_pos = get_market_state(index_df, date)

            # Step 3: 选股（仅当仓位未满且非空仓状态）
            if state != "empty" and len(portfolio.positions) < max_pos and portfolio.cash > 0:
                scores = []
                for code, df in stock_data.items():
                    # 跳过已持仓
                    if any(p["code"] == code for p in portfolio.positions):
                        continue
                    # 跳过数据不足
                    idx = df[df["date"] == date].index
                    if len(idx) == 0:
                        continue
                    idx = idx[0]

                    try:
                        t_score = score_trend(df, idx)
                        v_score = score_volume(df, idx)
                        f_score = score_fundamental(code, fund_df, sector_pe)
                        total = t_score + v_score + f_score
                        if total >= 24:  # 信号阈值
                            scores.append((code, total, t_score, v_score, f_score))
                    except Exception:
                        continue

                # 按总分降序，买入前N只
                scores.sort(key=lambda x: x[1], reverse=True)
                for code, total, t_s, v_s, f_s in scores:
                    if len(portfolio.positions) >= max_pos:
                        break
                    if portfolio.cash <= 0:
                        break
                    success = execute_buy(portfolio, code, date, stock_data, max_pos, total)
                    if success:
                        signals_log.append({
                            "date": date, "code": code, "total_score": total,
                            "trend": t_s, "volume": v_s, "fundamental": f_s,
                            "market_state": state,
                        })

            # Step 4: 记录每日净值
            portfolio.record_nav(date, stock_data)

        except Exception as e:
            print(f"  [ERROR] 回测日期 {date.date()} 异常: {e}")
            portfolio.record_nav(date, stock_data)
            continue

    return {
        "nav_df": portfolio.get_nav_df(),
        "trades_df": portfolio.get_trades_df(),
        "signals_log": pd.DataFrame(signals_log),
    }
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
from execution.broker import compute_fee
buy_fee = compute_fee(10000, False)
sell_fee = compute_fee(10000, True)
print(f'买入1万元费用: {buy_fee:.2f} (预期约5元=最低佣金)')
print(f'卖出1万元费用: {sell_fee:.2f} (预期约15元=佣金+印花税)')
print('broker OK')
"
```

---

### Task 11: analysis/metrics.py — 绩效指标计算

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/analysis/metrics.py`

- [ ] **Step 1: 编写 metrics.py**

```python
"""绩效分析模块：计算各类回测指标。"""
import pandas as pd
import numpy as np

TRADING_DAYS_PER_YEAR = 252


def compute_metrics(nav_df: pd.DataFrame, trades_df: pd.DataFrame, benchmark_nav: pd.Series | None = None) -> dict:
    """计算完整绩效指标。

    Args:
        nav_df: 每日净值DataFrame（需含 date/nav 列）
        trades_df: 交易记录DataFrame
        benchmark_nav: 基准净值序列（与nav_df对齐）

    Returns:
        指标字典
    """
    if nav_df.empty:
        return {"error": "无净值数据"}

    nav = nav_df["nav"].values
    dates = pd.to_datetime(nav_df["date"].values)
    days = len(nav)

    # ---- 收益指标 ----
    total_return = (nav[-1] / nav[0]) - 1
    years = max((dates[-1] - dates[0]).days / 365.25, 0.1)
    annual_return = (1 + total_return) ** (1 / years) - 1

    # 日收益率
    daily_returns = np.diff(nav) / nav[:-1]
    annual_vol = np.std(daily_returns) * np.sqrt(TRADING_DAYS_PER_YEAR) if len(daily_returns) > 0 else 0
    rf_daily = 0.03 / TRADING_DAYS_PER_YEAR  # 假设无风险利率3%
    excess = daily_returns - rf_daily
    sharpe = (np.mean(excess) / np.std(excess)) * np.sqrt(TRADING_DAYS_PER_YEAR) if np.std(excess) > 0 else 0

    # ---- 风险指标 ----
    peak = nav[0]
    max_drawdown = 0.0
    dd_start = dd_end = dates[0]
    peak_date = dates[0]
    for i in range(len(nav)):
        if nav[i] > peak:
            peak = nav[i]
            peak_date = dates[i]
        dd = (nav[i] - peak) / peak
        if dd < max_drawdown:
            max_drawdown = dd
            dd_start = peak_date
            dd_end = dates[i]

    # 最大连续亏损（以交易日计）
    max_consecutive_losses = 0
    current_streak = 0
    for r in daily_returns:
        if r < 0:
            current_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_streak)
        else:
            current_streak = 0

    # ---- 交易统计 ----
    if not trades_df.empty:
        sells = trades_df[trades_df["action"] == "SELL"]
        buys = trades_df[trades_df["action"] == "BUY"]

        win_count = 0
        total_trades = 0
        total_profit = 0.0
        total_loss = 0.0

        for _, sell in sells.iterrows():
            code = sell["code"]
            sell_date = sell["date"]
            buy_row = buys[(buys["code"] == code) & (buys["date"] < sell_date)]
            if buy_row.empty:
                continue
            buy_price = buy_row.iloc[-1]["price"]
            sell_price = sell["price"]
            pnl = (sell_price - buy_price) / buy_price
            total_trades += 1
            if pnl > 0:
                win_count += 1
                total_profit += pnl
            else:
                total_loss += abs(pnl)

        win_rate = win_count / total_trades if total_trades > 0 else 0
        avg_win = total_profit / win_count if win_count > 0 else 0
        avg_loss = total_loss / (total_trades - win_count) if (total_trades - win_count) > 0 else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    else:
        total_trades = 0
        win_rate = 0.0
        profit_loss_ratio = 0.0

    # ---- 基准对比 ----
    excess_return = 0.0
    information_ratio = 0.0
    if benchmark_nav is not None and len(benchmark_nav) == len(nav):
        excess_return = total_return - (benchmark_nav[-1] / benchmark_nav[0] - 1)
        excess_daily = daily_returns - (np.diff(benchmark_nav) / benchmark_nav[:-1])
        if np.std(excess_daily) > 0:
            information_ratio = np.mean(excess_daily) / np.std(excess_daily) * np.sqrt(TRADING_DAYS_PER_YEAR)

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "max_drawdown_start": str(dd_start.date()),
        "max_drawdown_end": str(dd_end.date()),
        "max_consecutive_losses": max_consecutive_losses,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_loss_ratio": profit_loss_ratio,
        "excess_return_vs_benchmark": excess_return,
        "information_ratio": information_ratio,
        "years": years,
    }
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
import pandas as pd
from analysis.metrics import compute_metrics
nav = pd.DataFrame({'date': pd.date_range('2024-01-01', periods=100), 'nav': [1.0 + i*0.001 for i in range(100)]})
trades = pd.DataFrame()
m = compute_metrics(nav, trades)
print(f'总收益: {m[\"total_return\"]:.2%}, 年化: {m[\"annual_return\"]:.2%}, 夏普: {m[\"sharpe_ratio\"]:.2f}')
print('metrics OK')
"
```

---

### Task 12: analysis/reporter.py — 图表与文字报告

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/analysis/reporter.py`

- [ ] **Step 1: 编写 reporter.py**

```python
"""报告生成模块：图表绘制 + 文字报告 + 操作清单模板。"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from config import OUTPUT_DIR

os.makedirs(OUTPUT_DIR, exist_ok=True)
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def plot_equity_curve(nav_df: pd.DataFrame, benchmark_nav: pd.Series | None = None):
    """绘制净值曲线叠加图。"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})

    dates = pd.to_datetime(nav_df["date"])
    nav = nav_df["nav"].values

    ax1.plot(dates, nav / nav[0], label="策略净值", color="#1f77b4", linewidth=1.5)
    if benchmark_nav is not None:
        ax1.plot(dates, benchmark_nav / benchmark_nav[0], label="沪深300基准", color="#ff7f0e", linewidth=1.0, alpha=0.7)
    ax1.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
    ax1.set_title("策略净值 vs 基准", fontsize=14)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 回撤曲线
    peak = np.maximum.accumulate(nav)
    drawdown = (nav - peak) / peak
    ax2.fill_between(dates, drawdown, 0, color="red", alpha=0.3)
    ax2.set_title("回撤曲线", fontsize=12)
    ax2.set_ylabel("回撤比例")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "equity_curve.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表已保存: {path}")


def plot_monthly_heatmap(nav_df: pd.DataFrame):
    """绘制月度收益热力图。"""
    df = nav_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["monthly_return"] = df["nav"].pct_change()
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    monthly = df.groupby(["year", "month"])["monthly_return"].apply(lambda x: (1 + x).prod() - 1).unstack()

    if monthly.empty:
        return

    fig, ax = plt.subplots(figsize=(14, len(monthly) * 0.8))
    im = ax.imshow(monthly * 100, cmap="RdYlGn", aspect="auto", vmin=-15, vmax=15)

    for i in range(monthly.shape[0]):
        for j in range(monthly.shape[1]):
            val = monthly.iloc[i, j]
            if pd.notna(val):
                ax.text(j, i, f"{val*100:.1f}%", ha="center", va="center", fontsize=8)

    ax.set_xticks(range(12))
    ax.set_xticklabels([f"{m}月" for m in range(1, 13)])
    ax.set_yticks(range(len(monthly)))
    ax.set_yticklabels(monthly.index.astype(str))
    ax.set_title("月度收益热力图 (%)", fontsize=14)
    plt.colorbar(im, ax=ax)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "monthly_heatmap.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  热力图已保存: {path}")


def generate_report(metrics: dict, trades_df: pd.DataFrame, signals_log: pd.DataFrame) -> str:
    """生成文字版回测报告。"""
    report = f"""
{'='*60}
      A股混合自适应量化策略 — 回测报告
{'='*60}

【收益指标】
  总收益率:       {metrics['total_return']*100:+.2f}%
  年化收益率:     {metrics['annual_return']*100:+.2f}%
  年化波动率:     {metrics['annual_volatility']*100:.2f}%
  夏普比率:       {metrics['sharpe_ratio']:.2f}
  回测年数:       {metrics['years']:.1f} 年

【风险指标】
  最大回撤:       {metrics['max_drawdown']*100:.2f}%
  回撤区间:       {metrics['max_drawdown_start']} ~ {metrics['max_drawdown_end']}
  最大连续亏损:   {metrics['max_consecutive_losses']} 个交易日

【交易统计】
  总交易次数:     {metrics['total_trades']}
  胜率:           {metrics['win_rate']*100:.1f}%
  盈亏比:         {metrics['profit_loss_ratio']:.2f}

【基准对比】
  超额收益(vs沪深300): {metrics['excess_return_vs_benchmark']*100:+.2f}%
  信息比率:            {metrics['information_ratio']:.2f}

{'='*60}
"""

    # 策略优缺点分析
    report += f"""
【策略优缺点分析】

  优势:
  1. 大盘择时空仓机制可规避系统性暴跌（如2022年、2024年初）
  2. 四维共振有效过滤噪音信号，降低频繁交易
  3. PE/PB/ROE估值初筛排除业绩暴雷股
  4. 等权分配 + 单只20%上限防黑天鹅

  适配场景:
  - 震荡上行市（大盘EMA20>EMA60，但非极端牛市）
  - 结构性行情（行业轮动中能捕捉到放量突破的个股）

  失效风险:
  - 单边急跌熊市：空仓机制会使其完全不交易，但如出现V型反转会踏空
  - 极端低波动市场：量能信号难以触发，可能长期空仓或轻仓
  - 中小盘风格切换：选股池以沪深300+中证500为主，小盘股行情时可能跑输
  - 基本面数据滞后：PE/PB/ROE基于最新财报，财报空窗期可能失真

{'='*60}
"""

    # 每日操作清单模板
    report += f"""
【实盘每日极简操作清单（模板）】

  收盘后检查（约15分钟）：

  □ 1. 打开沪深300指数日线，确认EMA20/EMA60/EMA120排列状态
       → 空头排列：明天不买任何新股
       → 三线多头：允许满仓操作
       → 中间状态：允许半仓操作

  □ 2. 检查现有持仓：
       □ 是否有股票亏损超过-8%？→ 明天开盘卖
       □ 是否有股票从高点回撤超过6%？→ 明天开盘卖
       □ 是否有股票持仓超40天仍未盈利？→ 明天开盘卖

  □ 3. 如大盘允许买入且仓位未满：
       □ 运行策略选股脚本，获得今日信号排名
       □ 选择总分最高的前N只股票，等额分配资金
       □ 记录每只买入价、数量、止损价（买入价×0.92）

  □ 4. 更新持仓日志（Excel或小本本）：
       - 日期 | 代码 | 买入价 | 数量 | 止损价 | 当前价 | 盈亏%

  盘中应急（仅在极端情况）：
  □ 大盘突然暴跌超5%：考虑手动清掉所有持仓（不执行是正常的）
  □ 持仓股发布重大利空/一字跌停：次日排队挂单卖出

{'='*60}
"""
    return report


def save_report(report: str):
    """保存文字报告到文件。"""
    path = os.path.join(OUTPUT_DIR, "report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  报告已保存: {path}")


def save_signals_csv(signals_log: pd.DataFrame):
    """保存每日信号日志。"""
    if signals_log.empty:
        return
    path = os.path.join(OUTPUT_DIR, "daily_signals.csv")
    signals_log.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  信号日志已保存: {path}")
```

- [ ] **Step 2: 验证**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
import pandas as pd
from analysis.reporter import generate_report, save_report
metrics = {'total_return': 0.35, 'annual_return': 0.07, 'annual_volatility': 0.18, 'sharpe_ratio': 0.6, 'years': 5, 'max_drawdown': -0.22, 'max_drawdown_start': '2022-03-15', 'max_drawdown_end': '2022-05-10', 'max_consecutive_losses': 8, 'total_trades': 120, 'win_rate': 0.45, 'profit_loss_ratio': 1.8, 'excess_return_vs_benchmark': 0.15, 'information_ratio': 0.8}
report = generate_report(metrics, pd.DataFrame(), pd.DataFrame())
save_report(report)
print('reporter OK')
"
```

---

### Task 13: main.py — 主编排入口

**Files:**
- Create: `C:/Users/PCB/Desktop/quant-strategy/main.py`

- [ ] **Step 1: 编写 main.py**

```python
"""
A股混合自适应量化策略 — 主入口
串联：数据拉取 → 清洗 → 信号计算 → 回测 → 分析报告
"""
import sys
import os
import time
import pandas as pd
import numpy as np
import traceback

# 将项目根目录加入路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    BACKTEST_START, BACKTEST_END, OUTPUT_DIR, CACHE_DIR, MARKET_INDEX,
)
from data.fetcher import build_stock_pool, fetch_all_stocks, fetch_index_data
from data.processor import process_all_stocks, clean_index_data, get_trading_dates
from signals.fundamental import _get_fundamentals, compute_sector_pe_medians
from execution.portfolio import Portfolio
from execution.broker import run_backtest
from analysis.metrics import compute_metrics
from analysis.reporter import (
    plot_equity_curve, plot_monthly_heatmap,
    generate_report, save_report, save_signals_csv,
)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


def main():
    print("=" * 60)
    print("  A股混合自适应量化策略 — 回测系统")
    print(f"  回测区间: {BACKTEST_START} ~ {BACKTEST_END}")
    print("=" * 60)

    # ===== Phase 1: 数据获取 =====
    print("\n[Phase 1/6] 构建选股池...")
    try:
        codes = build_stock_pool()
        if not codes:
            print("[FATAL] 选股池为空，无法继续")
            return
        print(f"  选股池: {len(codes)} 只")
    except Exception as e:
        print(f"[FATAL] 构建选股池失败: {e}")
        traceback.print_exc()
        return

    print("\n[Phase 2/6] 拉取历史行情数据（分批拉取，请耐心等待）...")
    try:
        raw_data = fetch_all_stocks(codes)
        if not raw_data:
            print("[FATAL] 未能获取任何股票数据")
            return
        print(f"  获取到 {len(raw_data)} 只股票数据")
    except Exception as e:
        print(f"[FATAL] 数据拉取失败: {e}")
        traceback.print_exc()
        return

    print("\n[Phase 3/6] 数据清洗...")
    try:
        stock_data = process_all_stocks(raw_data)
        if not stock_data:
            print("[FATAL] 清洗后无可用数据")
            return

        # 拉取并清洗指数数据
        print("  拉取指数数据...")
        raw_index = fetch_index_data(MARKET_INDEX)
        index_df = clean_index_data(raw_index)
        if index_df is None:
            print("[FATAL] 指数数据不可用")
            return

        trading_dates = get_trading_dates(stock_data)
        # 只保留回测区间内的日期
        trading_dates = trading_dates[
            (trading_dates >= pd.Timestamp(BACKTEST_START)) &
            (trading_dates <= pd.Timestamp(BACKTEST_END))
        ]
        print(f"  交易日期: {len(trading_dates)} 天")
    except Exception as e:
        print(f"[FATAL] 数据清洗失败: {e}")
        traceback.print_exc()
        return

    print("\n[Phase 4/6] 获取基本面数据...")
    try:
        fund_df = _get_fundamentals(list(stock_data.keys()))
        sector_pe = compute_sector_pe_medians(fund_df)
        print(f"  基本面数据: {len(fund_df)} 只, 行业分类: {len(sector_pe)} 个")
    except Exception as e:
        print(f"[WARN] 基本面数据获取异常: {e}，使用空数据继续")
        fund_df = pd.DataFrame()
        sector_pe = {}

    # ===== Phase 5: 回测执行 =====
    print("\n[Phase 5/6] 执行回测...")
    portfolio = Portfolio(initial_nav=1.0)

    try:
        start_time = time.time()
        result = run_backtest(
            stock_data=stock_data,
            index_df=index_df,
            fund_df=fund_df,
            sector_pe=sector_pe,
            trading_dates=trading_dates,
            portfolio=portfolio,
        )
        elapsed = time.time() - start_time
        print(f"  回测完成，耗时: {elapsed:.1f} 秒")
        print(f"  交易记录: {len(result['trades_df'])} 笔")
    except Exception as e:
        print(f"[FATAL] 回测执行失败: {e}")
        traceback.print_exc()
        return

    # ===== Phase 6: 分析报告 =====
    print("\n[Phase 6/6] 生成分析报告...")
    try:
        nav_df = result["nav_df"]
        trades_df = result["trades_df"]
        signals_log = result["signals_log"]

        # 构建基准净值（沪深300）
        benchmark_nav = None
        if index_df is not None:
            idx_start = index_df[index_df["date"] == trading_dates[0]]
            if not idx_start.empty:
                bench_start_close = idx_start.iloc[0]["close"]
                bench_aligned = []
                for d in trading_dates:
                    row = index_df[index_df["date"] == d]
                    if not row.empty:
                        bench_aligned.append(row.iloc[0]["close"] / bench_start_close)
                    else:
                        bench_aligned.append(bench_aligned[-1] if bench_aligned else 1.0)
                benchmark_nav = pd.Series(bench_aligned, index=range(len(trading_dates)))

        metrics = compute_metrics(nav_df, trades_df, benchmark_nav)
        report = generate_report(metrics, trades_df, signals_log)

        print(report)
        save_report(report)

        # 图表
        plot_equity_curve(nav_df, benchmark_nav)
        plot_monthly_heatmap(nav_df)
        save_signals_csv(signals_log)

    except Exception as e:
        print(f"[FATAL] 报告生成失败: {e}")
        traceback.print_exc()
        return

    print("\n" + "=" * 60)
    print("  回测完成！所有结果已输出到 output/ 目录")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
    except Exception as e:
        print(f"\n[FATAL] 未捕获异常: {e}")
        traceback.print_exc()
```

- [ ] **Step 2: 验证（仅导入检查，不执行完整回测）**

```bash
cd "C:/Users/PCB/Desktop/quant-strategy" && python -c "
import sys; sys.path.insert(0, '.')
# 验证所有模块可导入
from config import BACKTEST_START, BACKTEST_END
from data.fetcher import build_stock_pool
from data.processor import clean_stock_data
from signals.trend import score_trend
from signals.volume import score_volume
from signals.fundamental import score_fundamental
from signals.market_timing import get_market_state
from risk.stop_loss import check_exits
from risk.position_sizer import calculate_buy_quantity
from execution.portfolio import Portfolio
from execution.broker import run_backtest
from analysis.metrics import compute_metrics
from analysis.reporter import generate_report
print('所有模块导入成功')
print(f'回测区间: {BACKTEST_START} ~ {BACKTEST_END}')
"
```

预期输出：`所有模块导入成功` + 回测区间

---

## 执行顺序总结

```
Task 1  (骨架+配置) → 所有模块的基础
Task 2  (数据拉取)  → 独立，可先跑
Task 3  (数据清洗)  → 依赖 Task 2
Task 4  (均线信号)  → 独立
Task 5  (量能信号)  → 独立
Task 6  (估值信号)  → 依赖 Task 2（需要股票代码列表）
Task 7  (大盘择时)  → 依赖 Task 3（需要指标数据格式）
Task 8  (风控模块)  → 依赖 Task 1
Task 9  (持仓账簿)  → 独立
Task 10 (回测引擎)  → 依赖 Task 4-9
Task 11 (绩效指标)  → 依赖 Task 9 的输出格式
Task 12 (报告生成)  → 依赖 Task 11
Task 13 (主编排)    → 依赖全部模块
```
