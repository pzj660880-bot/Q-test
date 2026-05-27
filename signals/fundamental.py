"""估值过滤信号：PE/PB/ROE三维评估，输出0-10分。"""
import pandas as pd
import akshare as ak
from config import PB_MAX, ROE_MIN, PE_SECTOR_DISCOUNT


def _get_fundamentals(codes: list[str]) -> pd.DataFrame:
    """批量获取股票基本面数据。

    PE/PB通过akshare的stock_zh_a_spot_em()一次获取全市场数据，
    ROE和行业通过stock_individual_info_em逐只获取（仅需获取一次，缓存后复用）。
    逐只请求控制在50只/批，避免限流。
    """
    codes_set = set(codes)
    records = []

    # 批量获取PE/PB（全市场一次调用）
    try:
        spot = ak.stock_zh_a_spot_em()
        if spot is not None and not spot.empty:
            spot["代码"] = spot["代码"].astype(str)
            spot = spot[spot["代码"].isin(codes_set)]
            for _, r in spot.iterrows():
                records.append({
                    "code": r["代码"],
                    "pe": pd.to_numeric(r.get("市盈率-动态"), errors="coerce"),
                    "pb": pd.to_numeric(r.get("市净率"), errors="coerce"),
                })
    except Exception as e:
        print(f"  [WARN] 批量获取PE/PB失败: {e}")

    df = pd.DataFrame(records) if records else pd.DataFrame(columns=["code", "pe", "pb"])

    # 逐只获取ROE和行业（分批，每批50只）
    roe_sector_records = []
    all_codes = list(codes_set)
    for i in range(0, len(all_codes), 50):
        batch = all_codes[i:i+50]
        for code in batch:
            try:
                info = ak.stock_individual_info_em(symbol=code)
                if info is None or info.empty:
                    continue
                row = {"code": code}
                for _, r in info.iterrows():
                    if r["item"] == "净资产收益率":
                        row["roe"] = pd.to_numeric(r["value"], errors="coerce")
                    elif r["item"] == "行业":
                        row["sector"] = r["value"]
                roe_sector_records.append(row)
            except Exception:
                continue

    right_df = pd.DataFrame(roe_sector_records)
    if not right_df.empty and not df.empty:
        df = df.merge(right_df, on="code", how="left")
    elif not right_df.empty:
        df = right_df

    return df


def compute_sector_pe_medians(fund_df: pd.DataFrame) -> dict[str, float]:
    """计算各行业PE中位数。

    Returns:
        {sector_name: median_pe}
    """
    if "sector" not in fund_df.columns or "pe" not in fund_df.columns:
        return {}
    valid = fund_df.dropna(subset=["sector", "pe"])
    valid = valid[valid["pe"] > 0]
    return valid.groupby("sector")["pe"].median().to_dict()


def score_fundamental(code: str, fund_df: pd.DataFrame, sector_pe: dict[str, float]) -> float:
    """计算单只股票的估值得分。

    Args:
        code: 股票代码
        fund_df: 所有股票的基本面DataFrame
        sector_pe: 行业PE中位数映射

    Returns:
        0-10分
    """
    row = fund_df[fund_df["code"] == code]
    if row.empty:
        return 5.0  # 无数据给中性分

    row = row.iloc[0]
    score = 0.0

    pe = row.get("pe")
    pb = row.get("pb")
    roe = row.get("roe")
    sector = row.get("sector")

    # 1. PE低估 (+4)
    if pd.notna(pe) and pe > 0 and sector and sector in sector_pe:
        median = sector_pe[sector]
        if median > 0 and pe < median * PE_SECTOR_DISCOUNT:
            score += 4.0

    # 2. PB合理 (+3)
    if pd.notna(pb) and 0 < pb < PB_MAX:
        score += 3.0

    # 3. ROE过关 (+3) — akshare返回的ROE是百分比（如15表示15%）
    if pd.notna(roe) and roe > 0 and roe / 100 > ROE_MIN:
        score += 3.0

    return score
