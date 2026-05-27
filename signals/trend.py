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
    normalized = (score + 2) / 10 * 10
    return max(0.0, min(10.0, normalized))
