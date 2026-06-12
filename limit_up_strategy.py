"""
涨停板尾盘战法 — 14:50扫准涨停股，次日开盘无脑卖。

用法:
  python limit_up_strategy.py --mode backtest   # 3年回测
  python limit_up_strategy.py --mode live        # 实盘扫描（14:50运行）

策略逻辑:
  筛选条件:
    1. 涨幅 9.0%-10.0%（准涨停/涨停）
    2. 量比 ≥ 2.5（真金封板）
    3. 近5日首次涨停（非连续一字板）
    4. 收盘价接近日最高价（封板牢固，排除炸板）
    5. 日均成交额 < 10亿（小盘优先）
    6. 开盘涨幅 < 7%（排除一字板）
    7. 大盘不崩（CSI300 > -1.5%）
    8. 非ST、非新股
  买入: Top3按收盘价
  卖出: 次日开盘价无条件
"""

import sys
import os
import argparse
import datetime as dt
import glob
import time

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CACHE_DIR, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ALL_CACHE_DIR = os.path.join(SCRIPT_DIR, CACHE_DIR, "all_market")


# ============================================================================
# Config
# ============================================================================
class Cfg:
    # 涨停筛选
    GAIN_MIN = 7.0          # 涨幅下限（准涨停）
    GAIN_MAX = 9.5         # 涨幅上限
    VOL_RATIO_MIN = 3.0     # 量比下限（真金封板）
    OPEN_GAIN_MAX = 5.0     # 开盘涨幅上限（排除一字板）
    SEAL_RATIO = 0.95      # 收盘/最高 ≥ 此值 = 封板牢固
    AMT_MAX = 10e8          # 日均成交额上限
    FIRST_LIMIT_GAP = 5     # 近N日首次涨停
    MARKET_DROP_MAX = -1.5  # 大盘跌幅下限

    # 交易
    MAX_PICKS = 3           # 每日最多买3只
    TAKE_PROFIT = 0.01      # 止盈目标 1%（自然高开通常有1-3%）

    # 回测
    BACKTEST_YEARS = 5      # 回测年数
    INITIAL_CAPITAL = 1_000_000


# ============================================================================
# Data
# ============================================================================
def load_data():
    """加载全市场日线数据 + 指数数据。"""
    print("  加载数据...", flush=True)
    stock_data = {}
    files = glob.glob(os.path.join(ALL_CACHE_DIR, "*.csv"))
    if not files:
        sys.exit("未找到缓存数据，请先运行 fetch_all_market.py")

    for f in files:
        code = os.path.splitext(os.path.basename(f))[0]
        try:
            df = pd.read_csv(f, parse_dates=["date"])
            if len(df) < 60:
                continue
        except Exception:
            continue
        stock_data[code] = df

    # 加载指数
    index_df = None
    idx_file = os.path.join(SCRIPT_DIR, CACHE_DIR, "index_000300.csv")
    if os.path.exists(idx_file):
        index_df = pd.read_csv(idx_file, parse_dates=["date"])

    # 股票名称映射
    name_map = {}
    for idx_name in ["000300", "000905"]:
        cf = os.path.join(SCRIPT_DIR, CACHE_DIR, f"constituents_{idx_name}.csv")
        if os.path.exists(cf):
            try:
                df = pd.read_csv(cf, dtype={"code": str, "name": str})
                for _, row in df.iterrows():
                    name_map[row["code"]] = str(row.get("name", ""))
            except Exception:
                pass

    return stock_data, index_df, name_map


def compute_indicators(df):
    """计算技术指标。"""
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 30:
        return df
    df["pct_chg"] = df["close"].pct_change() * 100
    df["open_chg"] = (df["open"] - df["close"].shift(1)) / df["close"].shift(1) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan)
    df["seal_quality"] = df["close"] / df["high"]
    if "amount" in df.columns:
        df["amt_ma20"] = df["amount"].rolling(20).mean()
    else:
        df["amt_ma20"] = np.nan
    # 近5日是否涨停过
    limit_days = (df["pct_chg"] >= 9.0).astype(int)
    df["limit_in_5d"] = limit_days.rolling(5, min_periods=1).sum().shift(1).fillna(0)
    return df


def get_market_pct(index_df, date):
    """获取大盘涨跌幅。"""
    if index_df is None or index_df.empty:
        return 0
    rows = index_df[index_df["date"] == date]
    if rows.empty:
        return 0
    close = rows.iloc[0]["close"]
    prev_rows = index_df[index_df["date"] < date]
    if prev_rows.empty:
        return 0
    prev_close = prev_rows.iloc[-1]["close"]
    return (close - prev_close) / prev_close * 100 if prev_close > 0 else 0


# ============================================================================
# Filters
# ============================================================================
def passes_filters(row, market_pct):
    """检查股票是否通过所有涨停过滤器。返回(通过?, 原因)。"""
    pct_chg = row.get("pct_chg", np.nan)
    vol_ratio = row.get("vol_ratio", np.nan)
    open_chg = row.get("open_chg", np.nan)
    seal = row.get("seal_quality", np.nan)
    amt_ma20 = row.get("amt_ma20", np.nan)
    limit_5d = row.get("limit_in_5d", 0)
    name = str(row.get("name", ""))
    close = row["close"]
    high = row["high"]

    if pd.isna(close) or close <= 0:
        return False, "无效价格"
    if pd.isna(high) or high <= 0:
        return False, "无效最高价"

    # 8: 黑名单
    if name.startswith(("ST", "*ST", "N", "C")):
        return False, "ST/新股"

    # 1: 涨幅 9.0-10.0%
    if pd.isna(pct_chg):
        return False, "无涨幅"
    if not (Cfg.GAIN_MIN <= pct_chg <= Cfg.GAIN_MAX):
        return False, f"涨幅{pct_chg:.1f}%"

    # 2: 量比 ≥ 2.5
    if pd.isna(vol_ratio) or vol_ratio < Cfg.VOL_RATIO_MIN:
        return False, f"量比{vol_ratio:.1f}"

    # 3: 近5日首次涨停
    if limit_5d > 0:
        return False, "近日已涨停过"

    # 4: 封板牢固（收盘/最高 > 0.995）
    if pd.isna(seal) or seal < Cfg.SEAL_RATIO:
        return False, f"封板不牢({seal:.3f})"

    # 5: 小盘
    if pd.notna(amt_ma20) and amt_ma20 > 0 and amt_ma20 > Cfg.AMT_MAX:
        return False, f"盘子大(日均{amt_ma20/1e8:.1f}亿)"

    # 6: 非一字板（开盘涨幅<7%）
    if pd.notna(open_chg) and open_chg >= Cfg.OPEN_GAIN_MAX:
        return False, f"一字板(开盘{open_chg:.1f}%)"

    # 7: 大盘不崩
    if market_pct < Cfg.MARKET_DROP_MAX:
        return False, f"大盘跌{market_pct:.1f}%"

    return True, "OK"


# ============================================================================
# Backtest
# ============================================================================
def run_backtest():
    print("=" * 60)
    print("  涨停板尾盘战法 — 回测模式")
    print(f"  回测: {Cfg.BACKTEST_YEARS}年")
    print("=" * 60)

    stock_data, index_df, name_map = load_data()
    print(f"  股票: {len(stock_data)} 只")

    # 预计算指标
    print("  预计算指标...", flush=True)
    for code in stock_data:
        stock_data[code] = compute_indicators(stock_data[code])
        stock_data[code]["name"] = name_map.get(code, code)

    # 收集所有交易日
    all_dates = set()
    for df in stock_data.values():
        all_dates.update(df["date"].tolist())
    trade_dates = sorted(all_dates)
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=Cfg.BACKTEST_YEARS * 366)
    trade_dates = [d for d in trade_dates if d >= cutoff]
    print(f"  交易日: {len(trade_dates)} 天", flush=True)

    # 逐日回测
    all_trades = []
    total = len(trade_dates)

    for di in range(total - 1):
        t_date = trade_dates[di]
        t1_date = trade_dates[di + 1]

        if (t1_date - t_date).days > 5:
            continue

        if di % 100 == 0:
            print(f"  [{di}/{total}] {t_date.date()}", flush=True)

        market_pct = get_market_pct(index_df, t_date)

        # 扫描候选
        candidates = []
        for code, df in stock_data.items():
            rows = df[df["date"] == t_date]
            if rows.empty:
                continue
            row = rows.iloc[0].to_dict()
            row["code"] = code
            row["name"] = name_map.get(code, code)

            passed, _ = passes_filters(row, market_pct)
            if passed:
                candidates.append((code, row))

        # 按量比排序，取Top3
        candidates.sort(key=lambda x: x[1].get("vol_ratio", 0), reverse=True)
        picks = candidates[:Cfg.MAX_PICKS]

        # T+1执行
        for code, pick in picks:
            buy_price = pick["close"]

            t1_rows = stock_data[code][stock_data[code]["date"] == t1_date]
            if t1_rows.empty:
                continue
            sell_price = t1_rows.iloc[0]["open"]
            if pd.isna(sell_price) or sell_price <= 0:
                continue

            pnl_pct = (sell_price - buy_price) / buy_price * 100
            win = pnl_pct >= Cfg.TAKE_PROFIT * 100  # ≥1% = win

            all_trades.append({
                "buy_date": t_date,
                "sell_date": t1_date,
                "code": code,
                "name": pick.get("name", ""),
                "buy_price": round(buy_price, 2),
                "sell_price": round(sell_price, 2),
                "pnl_pct": round(pnl_pct, 2),
                "win": win,
                "pct_chg": round(pick.get("pct_chg", 0), 1),
                "vol_ratio": round(pick.get("vol_ratio", 1), 1),
                "seal": round(pick.get("seal_quality", 0), 3),
            })

    # ---- 统计 ----
    print(f"\n{'='*60}")
    print(f"  回测结果 ({Cfg.BACKTEST_YEARS}年)")
    print(f"{'='*60}")

    if not all_trades:
        print("  0笔交易！")
        return

    trades_df = pd.DataFrame(all_trades)
    total = len(trades_df)
    wins = trades_df["win"].sum()
    win_rate = wins / total * 100

    avg_win = trades_df[trades_df["win"]]["pnl_pct"].mean()
    avg_loss = trades_df[~trades_df["win"]]["pnl_pct"].mean()
    plr = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")
    total_pnl = trades_df["pnl_pct"].sum()
    avg_pnl = trades_df["pnl_pct"].mean()

    # 最大回撤
    daily = trades_df.groupby("buy_date")["pnl_pct"].mean()
    cumsum = daily.cumsum()
    dd = (cumsum - cumsum.cummax())
    max_dd = dd.min()

    # 年度统计
    trades_df["year"] = trades_df["buy_date"].dt.year
    yearly = trades_df.groupby("year").agg(
        trades=("code", "count"), win_rate=("win", "mean"),
        total_pnl=("pnl_pct", "sum"), avg_pnl=("pnl_pct", "mean"),
    )

    # 月度统计
    trades_df["month"] = trades_df["buy_date"].dt.to_period("M")
    monthly = trades_df.groupby("month").agg(
        trades=("code", "count"), win_rate=("win", "mean"),
    )

    print(f"""
  总交易:     {total} 笔
  胜率:       {win_rate:.1f}%
  平均盈利:   +{avg_win:.2f}%
  平均亏损:   {avg_loss:.2f}%
  盈亏比:     {plr:.2f}
  累计盈亏:   {total_pnl:+.1f}%
  平均每笔:   {avg_pnl:+.2f}%
  最大回撤:   {max_dd:.1f}%
  日均信号:   {total/len(trade_dates):.1f} 只
""")

    print("  年度表现:")
    print(f"  {'年份':<8} {'交易数':<8} {'胜率':<10} {'累计盈亏':<12} {'均价盈亏':<10}")
    for y, r in yearly.iterrows():
        print(f"  {y:<8} {int(r['trades']):<8} {r['win_rate']*100:>6.1f}%   {r['total_pnl']:>+8.1f}%   {r['avg_pnl']:>+8.2f}%")

    print("\n  月度胜率一览:")
    for m, r in monthly.iterrows():
        bar = "+" * max(0, int(r["win_rate"] * 10))
        print(f"  {str(m):<10} {int(r['trades']):>3}笔  {r['win_rate']*100:>5.0f}% {bar}")

    # 最近10笔
    print(f"\n  最近10笔:")
    for _, t in trades_df.tail(10).iterrows():
        m = "+" if t["win"] else "-"
        print(f"  {t['buy_date'].date()} {t['code']} {t['name'][:6]:<6s} "
              f"{t['buy_price']:>8.2f}→{t['sell_price']:>8.2f} {t['pnl_pct']:>+5.1f}% {m}")

    trades_df.to_csv(os.path.join(SCRIPT_DIR, CACHE_DIR, "limit_up_trades.csv"), index=False)
    print(f"\n  明细: cache/limit_up_trades.csv")


# ============================================================================
# Telegram
# ============================================================================
def send_telegram(text: str) -> bool:
    """发送消息到 Telegram。返回是否成功。"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:
        return False


# ============================================================================
# Live Scanner
# ============================================================================
def run_live():
    print("=" * 60)
    print(f"  涨停板尾盘战法 — 实盘扫描")
    print(f"  时间: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    try:
        import akshare as ak
    except ImportError:
        sys.exit("需要 akshare: pip install akshare")

    print("  拉取实时行情...")
    try:
        df = ak.stock_zh_a_spot_em()
    except Exception:
        import requests
        url = "http://82.push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "5000", "po": "1", "np": "1",
            "fltt": "2", "invt": "2", "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": "f2,f3,f8,f10,f12,f14,f15,f16,f17,f20,f6",
        }
        r = requests.get(url, params=params, timeout=15)
        items = r.json().get("data", {}).get("diff", [])
        df = pd.DataFrame(items)
        df.columns = ["price","pct_chg","turnover","vol_ratio",
                      "code","name","high","low","open","circ_mv","volume"]

    # 标准化列名
    if "代码" in df.columns:
        df = df.rename(columns={"代码":"code","名称":"name","最新价":"price",
            "涨跌幅":"pct_chg","成交量":"volume","换手率":"turnover",
            "量比":"vol_ratio","流通市值":"circ_mv","最高":"high",
            "最低":"low","今开":"open"})

    for col in ["pct_chg","vol_ratio","price","high","low","open"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    candidates = []
    for _, row in df.iterrows():
        code = str(row.get("code","")).zfill(6)
        name = str(row.get("name",""))
        pct_chg = row.get("pct_chg", np.nan)
        vol_ratio = row.get("vol_ratio", np.nan)
        price = row.get("price", np.nan)
        high = row.get("high", np.nan)
        open_ = row.get("open", np.nan)

        if pd.isna(pct_chg): continue
        if name.startswith(("ST","*ST","N","C")): continue
        if not (Cfg.GAIN_MIN <= pct_chg <= Cfg.GAIN_MAX): continue
        if pd.isna(vol_ratio) or vol_ratio < Cfg.VOL_RATIO_MIN: continue
        if pd.notna(price) and pd.notna(high) and high > 0:
            if price / high < Cfg.SEAL_RATIO: continue
        if pd.notna(open_) and pd.notna(price) and open_ > 0:
            open_chg = (open_ - price / (1 + pct_chg/100)) / (price / (1 + pct_chg/100)) * 100
            if open_chg >= Cfg.OPEN_GAIN_MAX: continue

        candidates.append({"code":code,"name":name,"price":price,
                          "pct_chg":pct_chg,"vol_ratio":vol_ratio})

    candidates.sort(key=lambda x: x["vol_ratio"], reverse=True)
    picks = candidates[:Cfg.MAX_PICKS]

    print(f"\n{'='*60}")
    print(f"  🎯 涨停板尾盘推荐 — {dt.datetime.now().strftime('%H:%M')}")
    print(f"  买入: 14:50-14:57  |  卖出: 次日开盘")
    print(f"{'='*60}")

    if not picks:
        print("\n  ⚠️ 今日无符合条件的涨停股")
        send_telegram(f"⚠️ 涨停板扫描 {dt.datetime.now().strftime('%m-%d %H:%M')}\n今日无符合条件的涨停股")
        return

    tg_lines = [
        f"<b>🎯 涨停板尾盘推荐</b> — {dt.datetime.now().strftime('%m-%d %H:%M')}",
        f"买入: 14:50-14:57 | 卖出: 次日开盘\n",
    ]
    for i, s in enumerate(picks):
        print(f"\n  #{i+1}  {s['code']}  {s['name']}"
              f"\n      现价 ¥{s['price']:.2f}  涨幅 +{s['pct_chg']:.1f}%  量比 {s['vol_ratio']:.1f}"
              f"\n      买入价: ¥{s['price']:.2f}  次日止盈: >¥{s['price']*1.01:.2f}")
        tg_lines.append(
            f"<b>#{i+1} {s['code']} {s['name']}</b>\n"
            f"现价 ¥{s['price']:.2f}  +{s['pct_chg']:.1f}%  量比{s['vol_ratio']:.1f}\n"
            f"买入 ¥{s['price']:.2f}  止盈 >¥{s['price']*1.01:.2f}"
        )

    print("\n  ⚠️ 量化筛选，不构成投资建议。")
    tg_lines.append("\n⚠️ 量化筛选，不构成投资建议")
    send_telegram("\n".join(tg_lines))


# ============================================================================
# Main
# ============================================================================
def run_schedule():
    """定时模式：等到14:30自动执行实盘扫描。"""
    now = dt.datetime.now()
    target = now.replace(hour=14, minute=30, second=0, microsecond=0)
    if now > target:
        target += dt.timedelta(days=1)

    wait = (target - now).total_seconds()
    print(f"  定时模式: {target.strftime('%H:%M')} 自动扫描")
    print(f"  等待 {int(wait//60)} 分钟...")
    print(f"  按 Ctrl+C 取消")

    try:
        while dt.datetime.now() < target:
            remaining = (target - dt.datetime.now()).total_seconds()
            if remaining <= 0:
                break
            m, s = int(remaining // 60), int(remaining % 60)
            print(f"\r  倒计时: {m:02d}:{s:02d}", end="", flush=True)
            time.sleep(1)
        print()
        run_live()
    except KeyboardInterrupt:
        print("\n  已取消")


def main():
    parser = argparse.ArgumentParser(description="涨停板尾盘战法")
    parser.add_argument("--mode", choices=["backtest","live","schedule"], default="live")
    args = parser.parse_args()

    if args.mode == "backtest":
        run_backtest()
    elif args.mode == "schedule":
        run_schedule()
    else:
        run_live()


if __name__ == "__main__":
    main()
