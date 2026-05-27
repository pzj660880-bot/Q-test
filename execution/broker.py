"""回测撮合引擎：T+1执行、涨跌停限制、费用计算。"""
import pandas as pd
import numpy as np
from config import (
    COMMISSION_RATE, COMMISSION_MIN, STAMP_TAX_RATE, LOT_SIZE,
    BACKTEST_START, BACKTEST_END,
)


def compute_fee(amount: float, is_sell: bool) -> float:
    """计算交易费用（佣金+印花税）。"""
    commission = max(amount * COMMISSION_RATE, COMMISSION_MIN)
    stamp = amount * STAMP_TAX_RATE if is_sell else 0.0
    return commission + stamp


def _get_row(df: pd.DataFrame, date, idx_map: dict | None = None):
    """O(1)获取指定日期的行情行。"""
    date = pd.Timestamp(date)
    if idx_map is not None:
        i = idx_map.get(date)
        if i is not None:
            return df.iloc[i]
        return None
    rows = df[df["date"] == date]
    return rows.iloc[0] if not rows.empty else None


def _get_next_date(df: pd.DataFrame, date, idx_map: dict | None = None):
    """获取下一个交易日。"""
    date = pd.Timestamp(date)
    if idx_map is not None:
        # idx_map keys are already pd.Timestamp, sort and find next
        all_dates = sorted(idx_map.keys())
        for d in all_dates:
            if d > date:
                return d
        return None
    dates = pd.to_datetime(df["date"])
    later = dates[dates > date]
    return later.iloc[0] if not later.empty else None


def can_buy(df: pd.DataFrame, date: pd.Timestamp, idx_map: dict | None = None) -> bool:
    row = _get_row(df, date, idx_map)
    if row is None:
        return False
    if row.get("is_suspended", False) or row.get("limit_up", False):
        return False
    return True


def can_sell(df: pd.DataFrame, date: pd.Timestamp, idx_map: dict | None = None) -> bool:
    row = _get_row(df, date, idx_map)
    if row is None:
        return False
    if row.get("is_suspended", False) or row.get("limit_down", False):
        return False
    return True


def execute_buy(portfolio, code: str, date: pd.Timestamp,
                stock_data: dict, max_positions: int,
                signal_score: float, idx_map: dict | None = None) -> bool:
    """T+1买入：次日开盘价成交。"""
    df = stock_data.get(code)
    if df is None:
        return False

    next_date = _get_next_date(df, date, idx_map)
    if next_date is None:
        return False

    if not can_buy(df, next_date, idx_map):
        return False

    row = _get_row(df, next_date, idx_map)
    if row is None:
        return False
    price = row["open"]
    if pd.isna(price) or price <= 0:
        return False

    if len(portfolio.positions) >= max_positions:
        return False

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
    if amount + fee > portfolio.cash:
        qty -= LOT_SIZE
        if qty < LOT_SIZE:
            return False
        amount = price * qty
        fee = compute_fee(amount, is_sell=False)
        if amount + fee > portfolio.cash:
            return False

    portfolio.cash -= amount + fee
    portfolio.add_position(code, next_date, price, qty)
    portfolio.record_trade(next_date, code, "BUY", price, qty, amount, fee)
    return True


def execute_sell(portfolio, code: str, date: pd.Timestamp,
                 stock_data: dict, reason: str = "",
                 idx_map: dict | None = None) -> bool:
    """T+1卖出：次日开盘价成交。"""
    pos = next((p for p in portfolio.positions if p["code"] == code), None)
    if pos is None:
        return False

    df = stock_data.get(code)
    if df is None:
        return False

    next_date = _get_next_date(df, date, idx_map)
    if next_date is None:
        return False

    if not can_sell(df, next_date, idx_map):
        return False

    row = _get_row(df, next_date, idx_map)
    if row is None:
        return False
    price = row["open"]
    if pd.isna(price) or price <= 0:
        return False

    qty = pos["quantity"]
    amount = price * qty
    fee = compute_fee(amount, is_sell=True)
    portfolio.cash += amount - fee
    portfolio.remove_position(code)
    portfolio.record_trade(next_date, code, "SELL", price, qty, amount, fee)
    return True


def run_backtest(stock_data: dict, index_df: pd.DataFrame,
                 fund_df: pd.DataFrame, sector_pe: dict,
                 trading_dates: pd.DatetimeIndex, portfolio) -> dict:
    """主回测循环：预建日期索引，O(1)日期查找替代O(n)全表扫描。"""
    from signals.market_timing import get_market_state
    from signals.trend import score_trend
    from signals.volume import score_volume
    from signals.fundamental import score_fundamental
    from risk.stop_loss import check_exits

    # 预建 {code: {pd.Timestamp: row_index}} — O(1)日期查询
    print("  构建日期索引...")
    idx_map = {}
    for code, df in stock_data.items():
        m = {}
        dates = pd.to_datetime(df["date"])
        for i in range(len(dates)):
            m[dates.iloc[i]] = i
        idx_map[code] = m

    signals_log = []
    total = len(trading_dates)

    for di, date in enumerate(trading_dates):
        if date < pd.Timestamp(BACKTEST_START) or date > pd.Timestamp(BACKTEST_END):
            continue

        if (di + 1) % 200 == 0:
            print(f"  回测 [{di+1}/{total}] ({(di+1)/total*100:.0f}%)")

        try:
            # Step 1: 止损止盈
            exits = check_exits(portfolio.positions, stock_data, date, idx_map)
            for exit_order in exits:
                execute_sell(portfolio, exit_order["code"], date, stock_data,
                             exit_order["reason"], idx_map)

            # Step 2: 大盘择时
            state, max_pos = get_market_state(index_df, date)

            # Step 3: 选股
            if state != "empty" and len(portfolio.positions) < max_pos and portfolio.cash > 0:
                held = {p["code"] for p in portfolio.positions}
                scores = []
                for code, df in stock_data.items():
                    if code in held:
                        continue
                    i = idx_map.get(code, {}).get(date)
                    if i is None:
                        continue
                    try:
                        ts = score_trend(df, i)
                        vs = score_volume(df, i)
                        fs = score_fundamental(code, fund_df, sector_pe)
                        total = ts + vs + fs
                        if total >= 24:
                            scores.append((code, total, ts, vs, fs))
                    except Exception:
                        continue

                scores.sort(key=lambda x: x[1], reverse=True)
                for code, total, ts, vs, fs in scores:
                    if len(portfolio.positions) >= max_pos or portfolio.cash <= 0:
                        break
                    ok = execute_buy(portfolio, code, date, stock_data, max_pos, total, idx_map)
                    if ok:
                        signals_log.append(dict(date=date, code=code, total_score=total,
                            trend=ts, volume=vs, fundamental=fs, market_state=state))

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
