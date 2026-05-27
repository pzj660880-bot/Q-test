"""绩效分析模块：计算各类回测指标。"""
import pandas as pd
import numpy as np

TRADING_DAYS_PER_YEAR = 252


def compute_metrics(nav_df: pd.DataFrame, trades_df: pd.DataFrame, benchmark_nav: pd.Series | None = None) -> dict:
    """计算完整绩效指标。

    Args:
        nav_df: 每日净值DataFrame（需含 date/nav 列）
        trades_df: 交易记录DataFrame
        benchmark_nav: 基准净值序列（与nav_df对齐）

    Returns:
        指标字典
    """
    if nav_df.empty:
        return {"error": "无净值数据"}

    nav = nav_df["nav"].values
    dates = pd.to_datetime(nav_df["date"].values)
    days = len(nav)

    # ---- 收益指标 ----
    total_return = (nav[-1] / nav[0]) - 1
    years = max((dates[-1] - dates[0]).days / 365.25, 0.1)
    annual_return = (1 + total_return) ** (1 / years) - 1

    # 日收益率
    daily_returns = np.diff(nav) / nav[:-1]
    annual_vol = np.std(daily_returns) * np.sqrt(TRADING_DAYS_PER_YEAR) if len(daily_returns) > 0 else 0
    rf_daily = 0.03 / TRADING_DAYS_PER_YEAR  # 假设无风险利率3%
    excess = daily_returns - rf_daily
    sharpe = (np.mean(excess) / np.std(excess)) * np.sqrt(TRADING_DAYS_PER_YEAR) if np.std(excess) > 0 else 0

    # ---- 风险指标 ----
    peak = nav[0]
    max_drawdown = 0.0
    dd_start = dd_end = dates[0]
    peak_date = dates[0]
    for i in range(len(nav)):
        if nav[i] > peak:
            peak = nav[i]
            peak_date = dates[i]
        dd = (nav[i] - peak) / peak
        if dd < max_drawdown:
            max_drawdown = dd
            dd_start = peak_date
            dd_end = dates[i]

    # 最大连续亏损（以交易日计）
    max_consecutive_losses = 0
    current_streak = 0
    for r in daily_returns:
        if r < 0:
            current_streak += 1
            max_consecutive_losses = max(max_consecutive_losses, current_streak)
        else:
            current_streak = 0

    # ---- 交易统计 ----
    if not trades_df.empty:
        sells = trades_df[trades_df["action"] == "SELL"]
        buys = trades_df[trades_df["action"] == "BUY"]

        win_count = 0
        total_trades = 0
        total_profit = 0.0
        total_loss = 0.0

        for _, sell in sells.iterrows():
            code = sell["code"]
            sell_date = sell["date"]
            buy_row = buys[(buys["code"] == code) & (buys["date"] < sell_date)]
            if buy_row.empty:
                continue
            buy_price = buy_row.iloc[-1]["price"]
            sell_price = sell["price"]
            pnl = (sell_price - buy_price) / buy_price
            total_trades += 1
            if pnl > 0:
                win_count += 1
                total_profit += pnl
            else:
                total_loss += abs(pnl)

        win_rate = win_count / total_trades if total_trades > 0 else 0
        avg_win = total_profit / win_count if win_count > 0 else 0
        avg_loss = total_loss / (total_trades - win_count) if (total_trades - win_count) > 0 else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    else:
        total_trades = 0
        win_rate = 0.0
        profit_loss_ratio = 0.0

    # ---- 基准对比 ----
    excess_return = 0.0
    information_ratio = 0.0
    if benchmark_nav is not None and len(benchmark_nav) == len(nav):
        excess_return = total_return - (benchmark_nav.iloc[-1] / benchmark_nav.iloc[0] - 1)
        excess_daily = daily_returns - (np.diff(benchmark_nav.values) / benchmark_nav.values[:-1])
        if np.std(excess_daily) > 0:
            information_ratio = np.mean(excess_daily) / np.std(excess_daily) * np.sqrt(TRADING_DAYS_PER_YEAR)

    return {
        "total_return": total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_vol,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_drawdown,
        "max_drawdown_start": str(dd_start.date()),
        "max_drawdown_end": str(dd_end.date()),
        "max_consecutive_losses": max_consecutive_losses,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_loss_ratio": profit_loss_ratio,
        "excess_return_vs_benchmark": excess_return,
        "information_ratio": information_ratio,
        "years": years,
    }
