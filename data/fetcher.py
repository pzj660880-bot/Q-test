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
