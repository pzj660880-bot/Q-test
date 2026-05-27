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

        # 硬止损：亏损达到-8%
        if pnl_pct <= HARD_STOP_LOSS:
            exits.append({"code": code, "reason": f"硬止损 ({pnl_pct:.1%})"})
            continue

        # 移动止盈：从最高点回撤6%
        high = max(pos.get("highest_price", entry_price), current_price)
        pos["highest_price"] = high
        drawdown_from_high = (current_price - high) / high
        if high > entry_price and drawdown_from_high <= TRAILING_STOP_DRAWDOWN:
            exits.append({"code": code, "reason": f"移动止盈 (回撤{drawdown_from_high:.1%})"})
            continue

        # 时间止损：持仓超40天未盈利
        days_held = (date - pos["entry_date"]).days
        if days_held > TIME_STOP_DAYS and pnl_pct <= 0:
            exits.append({"code": code, "reason": f"时间止损 (持仓{days_held}天)"})

    return exits
