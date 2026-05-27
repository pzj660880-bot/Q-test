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
