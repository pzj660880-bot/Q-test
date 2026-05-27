"""止损止盈模块：检查持仓是否触发退出条件。"""
import pandas as pd
from config import HARD_STOP_LOSS, TRAILING_STOP_DRAWDOWN, TIME_STOP_DAYS


def check_exits(
    positions: list[dict],
    stock_data: dict[str, pd.DataFrame],
    date: pd.Timestamp,
    idx_map: dict | None = None,
) -> list[dict]:
    """检查所有持仓，返回需要卖出的列表。

    Args:
        positions: [{code, entry_date, entry_price, highest_price, quantity}]
        stock_data: {code: DataFrame}
        date: 当前日期
        idx_map: {code: {date: row_index}} 预建索引，启用O(1)查找
    """
    exits = []
    for pos in positions:
        code = pos["code"]
        df = stock_data.get(code)
        if df is None:
            continue

        # O(1)索引查找，回退到O(n)扫描
        if idx_map and code in idx_map:
            i = idx_map[code].get(date)
            row = df.iloc[i] if i is not None else None
        else:
            rows = df[df["date"] == date]
            row = rows.iloc[0] if not rows.empty else None

        if row is None:
            continue
        current_price = row["close"]
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
