"""持仓账簿：跟踪现金、持仓、净值变化。"""
import pandas as pd


class Portfolio:
    """持仓与资金管理账本。"""

    def __init__(self, initial_nav: float = 1.0):
        self.initial_nav = initial_nav
        self.cash = initial_nav
        self.positions: list[dict] = []  # [{code, entry_date, entry_price, highest_price, quantity}]
        self.nav_history: list[dict] = []  # [{date, nav, cash, position_value}]
        self.trades: list[dict] = []       # [{date, code, action, price, quantity, amount, fee}]

    def total_nav(self, stock_data: dict[str, pd.DataFrame], date: pd.Timestamp) -> float:
        """计算当日总净值 = 现金 + 持仓市值。"""
        position_value = 0.0
        for pos in self.positions:
            code = pos["code"]
            df = stock_data.get(code)
            if df is None:
                continue
            row = df[df["date"] == date]
            if not row.empty:
                position_value += row.iloc[0]["close"] * pos["quantity"]
        return self.cash + position_value

    def record_nav(self, date: pd.Timestamp, stock_data: dict[str, pd.DataFrame]):
        """记录每日净值快照。"""
        pos_val = 0.0
        for pos in self.positions:
            df = stock_data.get(pos["code"])
            if df is not None:
                row = df[df["date"] == date]
                if not row.empty:
                    pos_val += row.iloc[0]["close"] * pos["quantity"]

        self.nav_history.append({
            "date": date,
            "nav": self.cash + pos_val,
            "cash": self.cash,
            "position_value": pos_val,
            "position_count": len(self.positions),
        })

    def add_position(self, code: str, date: pd.Timestamp, price: float, quantity: int):
        """记录买入持仓。"""
        self.positions.append({
            "code": code,
            "entry_date": date,
            "entry_price": price,
            "highest_price": price,
            "quantity": quantity,
        })

    def remove_position(self, code: str):
        """移除卖出持仓。"""
        self.positions = [p for p in self.positions if p["code"] != code]

    def record_trade(self, date, code, action, price, quantity, amount, fee):
        """记录交易。"""
        self.trades.append({
            "date": date, "code": code, "action": action,
            "price": price, "quantity": quantity, "amount": amount, "fee": fee,
        })

    def get_nav_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.nav_history)

    def get_trades_df(self) -> pd.DataFrame:
        return pd.DataFrame(self.trades)
