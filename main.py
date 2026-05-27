"""
A股混合自适应量化策略 — 主入口
串联：数据拉取 → 清洗 → 信号计算 → 回测 → 分析报告
"""
import sys
import os
import time
import pandas as pd
import numpy as np
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    BACKTEST_START, BACKTEST_END, OUTPUT_DIR, CACHE_DIR, MARKET_INDEX,
)
from data.fetcher import build_stock_pool, fetch_all_stocks, fetch_index_data
from data.processor import process_all_stocks, clean_index_data, get_trading_dates
from signals.fundamental import _get_fundamentals, compute_sector_pe_medians
from execution.portfolio import Portfolio
from execution.broker import run_backtest
from analysis.metrics import compute_metrics
from analysis.reporter import (
    plot_equity_curve, plot_monthly_heatmap,
    generate_report, save_report, save_signals_csv,
)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


def main():
    print("=" * 60)
    print("  A股混合自适应量化策略 — 回测系统")
    print(f"  回测区间: {BACKTEST_START} ~ {BACKTEST_END}")
    print("=" * 60)

    # ===== Phase 1: 数据获取 =====
    print("\n[Phase 1/6] 构建选股池...")
    try:
        codes = build_stock_pool()
        if not codes:
            print("[FATAL] 选股池为空，无法继续")
            return
        print(f"  选股池: {len(codes)} 只")
    except Exception as e:
        print(f"[FATAL] 构建选股池失败: {e}")
        traceback.print_exc()
        return

    print("\n[Phase 2/6] 拉取历史行情数据（分批拉取，请耐心等待）...")
    try:
        raw_data = fetch_all_stocks(codes)
        if not raw_data:
            print("[FATAL] 未能获取任何股票数据")
            return
        print(f"  获取到 {len(raw_data)} 只股票数据")
    except Exception as e:
        print(f"[FATAL] 数据拉取失败: {e}")
        traceback.print_exc()
        return

    print("\n[Phase 3/6] 数据清洗...")
    try:
        stock_data = process_all_stocks(raw_data)
        if not stock_data:
            print("[FATAL] 清洗后无可用数据")
            return

        print("  拉取指数数据...")
        raw_index = fetch_index_data(MARKET_INDEX)
        index_df = clean_index_data(raw_index)
        if index_df is None:
            print("[FATAL] 指数数据不可用")
            return

        trading_dates = get_trading_dates(stock_data)
        trading_dates = trading_dates[
            (trading_dates >= pd.Timestamp(BACKTEST_START)) &
            (trading_dates <= pd.Timestamp(BACKTEST_END))
        ]
        print(f"  交易日期: {len(trading_dates)} 天")
    except Exception as e:
        print(f"[FATAL] 数据清洗失败: {e}")
        traceback.print_exc()
        return

    print("\n[Phase 4/6] 获取基本面数据...")
    try:
        fund_df = _get_fundamentals(list(stock_data.keys()))
        sector_pe = compute_sector_pe_medians(fund_df)
        print(f"  基本面数据: {len(fund_df)} 只, 行业分类: {len(sector_pe)} 个")
    except Exception as e:
        print(f"[WARN] 基本面数据获取异常: {e}，使用空数据继续")
        fund_df = pd.DataFrame()
        sector_pe = {}

    # ===== Phase 5: 回测执行 =====
    print("\n[Phase 5/6] 执行回测...")
    portfolio = Portfolio(initial_nav=1.0)

    try:
        start_time = time.time()
        result = run_backtest(
            stock_data=stock_data,
            index_df=index_df,
            fund_df=fund_df,
            sector_pe=sector_pe,
            trading_dates=trading_dates,
            portfolio=portfolio,
        )
        elapsed = time.time() - start_time
        print(f"  回测完成，耗时: {elapsed:.1f} 秒")
        print(f"  交易记录: {len(result['trades_df'])} 笔")
    except Exception as e:
        print(f"[FATAL] 回测执行失败: {e}")
        traceback.print_exc()
        return

    # ===== Phase 6: 分析报告 =====
    print("\n[Phase 6/6] 生成分析报告...")
    try:
        nav_df = result["nav_df"]
        trades_df = result["trades_df"]
        signals_log = result["signals_log"]

        # 构建基准净值（沪深300，与策略净值起始对齐）
        benchmark_nav = None
        if index_df is not None and len(trading_dates) > 0:
            idx_start = index_df[index_df["date"] == trading_dates[0]]
            if not idx_start.empty:
                bench_start_close = idx_start.iloc[0]["close"]
                bench_aligned = []
                for d in trading_dates:
                    row = index_df[index_df["date"] == d]
                    if not row.empty:
                        bench_aligned.append(row.iloc[0]["close"] / bench_start_close)
                    else:
                        bench_aligned.append(bench_aligned[-1] if bench_aligned else 1.0)
                benchmark_nav = pd.Series(bench_aligned)

        metrics = compute_metrics(nav_df, trades_df, benchmark_nav)
        report = generate_report(metrics, trades_df, signals_log)

        print(report)
        save_report(report)

        plot_equity_curve(nav_df, benchmark_nav)
        plot_monthly_heatmap(nav_df)
        save_signals_csv(signals_log)

    except Exception as e:
        print(f"[FATAL] 报告生成失败: {e}")
        traceback.print_exc()
        return

    print("\n" + "=" * 60)
    print("  回测完成！所有结果已输出到 output/ 目录")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断")
    except Exception as e:
        print(f"\n[FATAL] 未捕获异常: {e}")
        traceback.print_exc()
