"""仓位管理模块：计算买入数量和单只仓位。"""
import math
from config import LOT_SIZE, MAX_SINGLE_POSITION_PCT


def calculate_buy_quantity(
    available_cash: float,
    price: float,
    num_positions: int,
    total_nav: float,
) -> int:
    """计算买入股数（等权分配，取整手）。

    Args:
        available_cash: 可用现金
        price: 当前股价
        num_positions: 目标持仓数（剩余仓位空位）
        total_nav: 总净值

    Returns:
        股数（整手向下取整，最少100股）
    """
    if num_positions <= 0 or price <= 0:
        return 0

    # 等权分配
    equal_share = available_cash / num_positions

    # 单只仓位上限约束
    max_per_stock = total_nav * MAX_SINGLE_POSITION_PCT

    buy_amount = min(equal_share, max_per_stock)
    shares = int(buy_amount / price / LOT_SIZE) * LOT_SIZE

    return shares
