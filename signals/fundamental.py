"""估值过滤信号：PE/PB评估，输出0-10分。使用baostock数据源。"""
import pandas as pd
import baostock as bs
from config import PB_MAX, PE_SECTOR_DISCOUNT


def _get_fundamentals(codes: list[str]) -> pd.DataFrame:
    """批量获取股票基本面数据（PE/PB/行业）。

    从baostock日线K线数据中提取最新PE/PB值，从query_stock_industry获取行业分类。
    """
    bs.login()
    records = []
    end_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    start_date = (pd.Timestamp.now() - pd.Timedelta(days=60)).strftime("%Y-%m-%d")

    for code in codes:
        try:
            bs_code = f"sh.{code}" if code.startswith("6") else f"sz.{code}"

            # PE/PB从日线数据提取（取最近有效值）
            rs = bs.query_history_k_data_plus(
                bs_code, "date,peTTM,pbMRQ",
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="1"
            )
            if rs.error_code != "0":
                continue

            rows = []
            while rs.next():
                rows.append(rs.get_row_data())

            pe = pb = None
            for r in reversed(rows):
                pe_val = float(r[1]) if r[1] and r[1] != "0.000000" else 0
                pb_val = float(r[2]) if r[2] and r[2] != "0.000000" else 0
                if pe_val > 0 and pe is None:
                    pe = pe_val
                if pb_val > 0 and pb is None:
                    pb = pb_val
                if pe is not None and pb is not None:
                    break

            # 行业分类
            sector = ""
            try:
                rs_ind = bs.query_stock_industry(code=bs_code)
                if rs_ind.error_code == "0":
                    ind_rows = []
                    while rs_ind.next():
                        ind_rows.append(rs_ind.get_row_data())
                    if ind_rows:
                        sector = ind_rows[-1][2]
            except Exception:
                pass

            records.append({"code": code, "pe": pe, "pb": pb, "sector": sector})
        except Exception:
            continue

    bs.logout()
    return pd.DataFrame(records) if records else pd.DataFrame(columns=["code", "pe", "pb", "sector"])


def compute_sector_pe_medians(fund_df: pd.DataFrame) -> dict[str, float]:
    """计算各行业PE中位数。"""
    if "sector" not in fund_df.columns or "pe" not in fund_df.columns:
        return {}
    valid = fund_df.dropna(subset=["sector", "pe"])
    valid = valid[valid["pe"] > 0]
    return valid.groupby("sector")["pe"].median().to_dict()


def score_fundamental(code: str, fund_df: pd.DataFrame, sector_pe: dict[str, float]) -> float:
    """计算单只股票的估值得分。

    PE低估得5分，PB合理得5分，满分10。无数据给中性5分。
    """
    row = fund_df[fund_df["code"] == code]
    if row.empty:
        return 5.0

    row = row.iloc[0]
    score = 0.0

    pe = row.get("pe")
    pb = row.get("pb")
    sector = row.get("sector")

    # PE低估：低于行业中位数80% (+5)
    if pd.notna(pe) and pe > 0 and sector and sector in sector_pe:
        median = sector_pe[sector]
        if median > 0 and pe < median * PE_SECTOR_DISCOUNT:
            score += 5.0
        elif pe < median:
            score += 2.5  # 不显著低估但也不算贵

    # PB合理 (+5)
    if pd.notna(pb) and 0 < pb < PB_MAX:
        score += 5.0
    elif pd.notna(pb) and pb > 0 and pb < PB_MAX * 1.5:
        score += 2.5  # 略高但可接受

    return score
