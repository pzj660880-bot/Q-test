"""数据拉取模块：baostock获取个股日线 + akshare获取指数/成分股，本地CSV缓存。"""
import os
import time
import pandas as pd
import baostock as bs
import akshare as ak
from config import (
    CACHE_DIR, STOCK_POOL_INDICES, BACKTEST_START, BACKTEST_END,
    BENCHMARK_INDEX, SHANGHAI_INDEX, MIN_LISTING_DAYS, EXCLUDE_ST_PREFIX,
)

os.makedirs(CACHE_DIR, exist_ok=True)

# baostock 全局登录
_BS_LOGGED_IN = False


def _bs_login():
    global _BS_LOGGED_IN
    if not _BS_LOGGED_IN:
        bs.login()
        _BS_LOGGED_IN = True


def _bs_logout():
    global _BS_LOGGED_IN
    if _BS_LOGGED_IN:
        bs.logout()
        _BS_LOGGED_IN = False


def _code_to_bs(code: str) -> str:
    """将6位代码转为baostock格式。6开头=上海(sh)，其余=深圳(sz)。"""
    return f"sh.{code}" if code.startswith("6") else f"sz.{code}"


def get_index_constituents(index_code: str) -> pd.DataFrame:
    """获取指数成分股列表（含代码+名称，用于ST过滤）。

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
    """构建选股池：合并指数成分股，去重，从成分股名称过滤ST。"""
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
    """拉取单只股票日线数据（后复权），缓存到CSV。使用baostock数据源。

    Returns:
        DataFrame columns: date, open, high, low, close, volume, amount
        失败返回None
    """
    cache_file = os.path.join(CACHE_DIR, f"{code}.csv")

    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, parse_dates=["date"])
        last_date = df["date"].max()
        if pd.Timestamp(last_date) >= pd.Timestamp.now() - pd.Timedelta(days=7):
            return df
        start_date = (pd.Timestamp(last_date) - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    else:
        start_date = pd.Timestamp(BACKTEST_START).strftime("%Y-%m-%d")

    end_date = pd.Timestamp.now().strftime("%Y-%m-%d")

    try:
        _bs_login()
        rs = bs.query_history_k_data_plus(
            _code_to_bs(code),
            "date,open,high,low,close,volume,amount",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="1"  # 1=后复权
        )
        if rs.error_code != "0":
            return _load_cache_or_none(cache_file)

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            return _load_cache_or_none(cache_file)

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "amount"])
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 删除全为NaN的行（停牌日baostock可能返回空行）
        df = df.dropna(subset=["open", "close"])

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
    """分批次拉取全量数据。baostock不需要长间隔，0.1s即可。

    Returns:
        {code: DataFrame} 字典
    """
    _bs_login()
    result = {}
    total = len(codes)
    for i, code in enumerate(codes):
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  进度 [{i+1}/{total}] ({(i+1)/total*100:.0f}%)")
        df = fetch_one_stock(code)
        if df is not None and not df.empty:
            result[code] = df
        time.sleep(0.1)  # baostock限速较宽松
    _bs_logout()
    print(f"  成功拉取 {len(result)} / {total} 只股票数据")
    return result


def fetch_index_data(code: str) -> pd.DataFrame | None:
    """拉取指数日线数据（如沪深300=000300）。使用baostock。

    Args:
        code: 指数代码如 '000300'，自动加 sh 前缀
    """
    _bs_login()
    cache_file = os.path.join(CACHE_DIR, f"index_{code}.csv")
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, parse_dates=["date"])

    try:
        rs = bs.query_history_k_data_plus(
            f"sh.{code}",
            "date,open,high,low,close,volume",
            start_date=pd.Timestamp(BACKTEST_START).strftime("%Y-%m-%d"),
            end_date=pd.Timestamp.now().strftime("%Y-%m-%d"),
            frequency="d", adjustflag="1"
        )
        if rs.error_code != "0":
            return None

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "close"])
        df.to_csv(cache_file, index=False)
        return df
    except Exception as e:
        print(f"  [ERROR] 拉取指数 {code} 失败: {e}")
        return None
