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
