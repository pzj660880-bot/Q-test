"""
全局配置参数 — 所有模块的统一参数来源。
修改策略参数只需改这个文件，不需要深入各个模块。
"""
from datetime import datetime

# ===== 回测时间区间 =====
BACKTEST_START = "2021-06-01"
BACKTEST_END   = "2026-05-28"

# ===== 数据源 =====
CACHE_DIR = "cache"
OUTPUT_DIR = "output"
BENCHMARK_INDEX = "000300"  # 沪深300作为基准
MARKET_INDEX = "000300"     # 大盘择时参考指数
SHANGHAI_INDEX = "000001"   # 上证指数备用

# ===== 选股池 =====
STOCK_POOL_INDICES = ["000300", "000905"]  # 沪深300 + 中证500
MIN_LISTING_DAYS = 60  # 上市不足60天剔除
EXCLUDE_ST_PREFIX = ("ST", "*ST")

# ===== 信号评分参数 =====
SIGNAL_THRESHOLD = 24  # 四维总分阈值（满分40，需≥24分触发买入）
EMA_SHORT, EMA_MID, EMA_LONG = 20, 60, 120
VOLUME_RATIO_THRESHOLD = 1.5       # 放量倍数
VOLUME_CONSECUTIVE_DAYS = 3        # 连续放量天数
MOMENTUM_GAIN_THRESHOLD = 0.02     # 量价配合涨幅阈值
TREND_DEVIATION_MAX = 0.30         # 均线偏离上限
PB_MAX = 3.0
ROE_MIN = 0.10
PE_SECTOR_DISCOUNT = 0.80         # PE需低于行业中位数的80%

# ===== 大盘择时 =====
PANIC_DROP_DAYS = 5
PANIC_DROP_THRESHOLD = -0.05  # 近5日跌幅超5%强制空仓
FULL_POSITION_COUNT = 8        # 满仓最多持仓数
HALF_POSITION_COUNT = 4        # 半仓最多持仓数
MAX_SINGLE_POSITION_PCT = 0.20 # 单只最大仓位20%

# ===== 风控 =====
HARD_STOP_LOSS = -0.08          # -8%硬止损
TRAILING_STOP_DRAWDOWN = -0.06  # 从最高点回撤6%移动止盈
TIME_STOP_DAYS = 40             # 持仓超40天无利润清仓

# ===== 费率 =====
COMMISSION_RATE = 0.00025   # 佣金万分之2.5
COMMISSION_MIN = 5.0        # 最低佣金5元
STAMP_TAX_RATE = 0.001     # 印花税千分之1（仅卖出）
LOT_SIZE = 100             # 1手=100股

# ===== 运行控制 =====
FETCH_BATCH_SIZE = 25        # 每批拉取股票数
FETCH_BATCH_SLEEP = 0.5      # 批次间隔秒数
API_TIMEOUT = 30             # API超时秒数
DAILY_BENCHMARK_CODE = "000300"  # 沪深300代码（akshare格式）
