"""报告生成模块：图表绘制 + 文字报告 + 操作清单模板。"""
import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from config import OUTPUT_DIR

os.makedirs(OUTPUT_DIR, exist_ok=True)
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def plot_equity_curve(nav_df: pd.DataFrame, benchmark_nav: pd.Series | None = None):
    """绘制净值曲线叠加图（含回撤子图）。"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={"height_ratios": [3, 1]})

    dates = pd.to_datetime(nav_df["date"])
    nav = nav_df["nav"].values

    ax1.plot(dates, nav / nav[0], label="策略净值", color="#1f77b4", linewidth=1.5)
    if benchmark_nav is not None:
        ax1.plot(dates, benchmark_nav / benchmark_nav.iloc[0], label="沪深300基准", color="#ff7f0e", linewidth=1.0, alpha=0.7)
    ax1.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5)
    ax1.set_title("策略净值 vs 基准", fontsize=14)
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 回撤曲线
    peak = np.maximum.accumulate(nav)
    drawdown = (nav - peak) / peak
    ax2.fill_between(dates, drawdown, 0, color="red", alpha=0.3)
    ax2.set_title("回撤曲线", fontsize=12)
    ax2.set_ylabel("回撤比例")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "equity_curve.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  图表已保存: {path}")


def plot_monthly_heatmap(nav_df: pd.DataFrame):
    """绘制月度收益热力图。"""
    df = nav_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["monthly_return"] = df["nav"].pct_change()
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    monthly = df.groupby(["year", "month"])["monthly_return"].apply(lambda x: (1 + x).prod() - 1).unstack()

    if monthly.empty:
        return

    fig, ax = plt.subplots(figsize=(14, len(monthly) * 0.8))
    im = ax.imshow(monthly * 100, cmap="RdYlGn", aspect="auto", vmin=-15, vmax=15)

    for i in range(monthly.shape[0]):
        for j in range(monthly.shape[1]):
            val = monthly.iloc[i, j]
            if pd.notna(val):
                ax.text(j, i, f"{val*100:.1f}%", ha="center", va="center", fontsize=8)

    ax.set_xticks(range(12))
    ax.set_xticklabels([f"{m}月" for m in range(1, 13)])
    ax.set_yticks(range(len(monthly)))
    ax.set_yticklabels(monthly.index.astype(str))
    ax.set_title("月度收益热力图 (%)", fontsize=14)
    plt.colorbar(im, ax=ax)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "monthly_heatmap.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  热力图已保存: {path}")


def generate_report(metrics: dict, trades_df: pd.DataFrame, signals_log: pd.DataFrame) -> str:
    """生成文字版回测报告。"""
    report = f"""
{'='*60}
      A股混合自适应量化策略 — 回测报告
{'='*60}

【收益指标】
  总收益率:       {metrics['total_return']*100:+.2f}%
  年化收益率:     {metrics['annual_return']*100:+.2f}%
  年化波动率:     {metrics['annual_volatility']*100:.2f}%
  夏普比率:       {metrics['sharpe_ratio']:.2f}
  回测年数:       {metrics['years']:.1f} 年

【风险指标】
  最大回撤:       {metrics['max_drawdown']*100:.2f}%
  回撤区间:       {metrics['max_drawdown_start']} ~ {metrics['max_drawdown_end']}
  最大连续亏损:   {metrics['max_consecutive_losses']} 个交易日

【交易统计】
  总交易次数:     {metrics['total_trades']}
  胜率:           {metrics['win_rate']*100:.1f}%
  盈亏比:         {metrics['profit_loss_ratio']:.2f}

【基准对比】
  超额收益(vs沪深300): {metrics['excess_return_vs_benchmark']*100:+.2f}%
  信息比率:            {metrics['information_ratio']:.2f}

{'='*60}
"""

    report += f"""
【策略优缺点分析】

  优势:
  1. 大盘择时空仓机制可规避系统性暴跌（如2022年、2024年初）
  2. 四维共振有效过滤噪音信号，降低频繁交易
  3. PE/PB/ROE估值初筛排除业绩暴雷股
  4. 等权分配 + 单只20%上限防黑天鹅

  适配场景:
  - 震荡上行市（大盘EMA20>EMA60，但非极端牛市）
  - 结构性行情（行业轮动中能捕捉到放量突破的个股）

  失效风险:
  - 单边急跌熊市：空仓机制会使其完全不交易，但如出现V型反转会踏空
  - 极端低波动市场：量能信号难以触发，可能长期空仓或轻仓
  - 中小盘风格切换：选股池以沪深300+中证500为主，小盘股行情时可能跑输
  - 基本面数据滞后：PE/PB/ROE基于最新财报，财报空窗期可能失真

{'='*60}
"""

    report += f"""
【实盘每日极简操作清单（模板）】

  收盘后检查（约15分钟）：

  □ 1. 打开沪深300指数日线，确认EMA20/EMA60/EMA120排列状态
       → 空头排列：明天不买任何新股
       → 三线多头：允许满仓操作
       → 中间状态：允许半仓操作

  □ 2. 检查现有持仓：
       □ 是否有股票亏损超过-8%？→ 明天开盘卖
       □ 是否有股票从高点回撤超过6%？→ 明天开盘卖
       □ 是否有股票持仓超40天仍未盈利？→ 明天开盘卖

  □ 3. 如大盘允许买入且仓位未满：
       □ 运行策略选股脚本，获得今日信号排名
       □ 选择总分最高的前N只股票，等额分配资金
       □ 记录每只买入价、数量、止损价（买入价×0.92）

  □ 4. 更新持仓日志（Excel或小本本）：
       - 日期 | 代码 | 买入价 | 数量 | 止损价 | 当前价 | 盈亏%

  盘中应急（仅在极端情况）：
  □ 大盘突然暴跌超5%：考虑手动清掉所有持仓
  □ 持仓股发布重大利空/一字跌停：次日排队挂单卖出

{'='*60}
"""
    return report


def save_report(report: str):
    """保存文字报告到文件。"""
    path = os.path.join(OUTPUT_DIR, "report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  报告已保存: {path}")


def save_signals_csv(signals_log: pd.DataFrame):
    """保存每日信号日志。"""
    if signals_log.empty:
        return
    path = os.path.join(OUTPUT_DIR, "daily_signals.csv")
    signals_log.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"  信号日志已保存: {path}")
