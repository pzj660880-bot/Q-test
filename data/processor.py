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

    # 裁剪回测区间（预留150天计算EMA）
    start = pd.Timestamp(BACKTEST_START) - pd.Timedelta(days=150)
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
