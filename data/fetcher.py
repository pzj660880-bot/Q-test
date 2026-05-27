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
    """带重试的akshare调用：最多3次，指数退避。"""
    max_retries = 3
    last_error = None
    for attempt in range(max_retries):
        try:
            result = func(*args, **kwargs)
            if result is not None and not (hasattr(result, "empty") and result.empty):
                return result
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 2  # 2s, 4s, 6s
                time.sleep(wait)
    if last_error:
        print(f"  [WARN] akshare调用失败 {func.__name__}: {last_error}")
    return pd.DataFrame()


def get_index_constituents(index_code: str) -> pd.DataFrame:
    """获取指数成分股列表（含代码+名称，用于ST过滤）。

    Args:
        index_code: '000300'(沪深300) 或 '000905'(中证500)

    Returns:
        DataFrame with columns: code, name
    """
    cache_file = os.path.join(CACHE_DIR, f"constituents_{index_code}.csv")
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, dtype={"code": str, "name": str})
        if "name" in df.columns:
            return df

    try:
        if index_code == "000300":
            raw = ak.index_stock_cons_csindex(symbol="000300")
        else:
            raw = ak.index_stock_cons_csindex(symbol="000905")
        df = pd.DataFrame({
            "code": raw["成分券代码"].astype(str).str.zfill(6),
            "name": raw["成分券名称"].astype(str),
        })
        df.to_csv(cache_file, index=False)
        print(f"  获取 {index_code} 成分股 {len(df)} 只")
        return df
    except Exception as e:
        print(f"  [ERROR] 获取成分股失败 {index_code}: {e}")
        return pd.DataFrame(columns=["code", "name"])


def build_stock_pool() -> list[str]:
    """构建选股池：合并指数成分股，去重，从成分股名称过滤ST。

    指数成分股数据自带股票名称，直接通过名称前缀过滤ST，
    无需逐只调用API，Phase 1从20分钟缩短到秒级。
    指数纳入规则已隐含上市时间要求，不再单独过滤。
    """
    all_rows = []
    seen = set()
    for idx in STOCK_POOL_INDICES:
        df = get_index_constituents(idx)
        for _, row in df.iterrows():
            code = row["code"]
            if code not in seen:
                seen.add(code)
                all_rows.append(row)
    print(f"合并成分股 {len(all_rows)} 只（去重后）")

    filtered = []
    for row in all_rows:
        name = str(row.get("name", ""))
        if name.startswith(EXCLUDE_ST_PREFIX):
            continue
        filtered.append(row["code"])

    st_count = len(all_rows) - len(filtered)
    print(f"剔除ST: {st_count} 只, 最终选股池: {len(filtered)} 只")
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
    """分批拉取全量数据，每只股票间隔0.3秒防限流。

    Returns:
        {code: DataFrame} 字典，拉取失败的code不会出现在结果中
    """
    result = {}
    total = len(codes)
    sleep_per_stock = 0.3  # 每只股票间隔300ms
    for i, code in enumerate(codes):
        if (i + 1) % 20 == 0 or i == 0:
            print(f"  进度 [{i+1}/{total}] ({(i+1)/total*100:.0f}%)")
        df = fetch_one_stock(code)
        if df is not None and not df.empty:
            result[code] = df
        time.sleep(sleep_per_stock)
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
