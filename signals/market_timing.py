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
