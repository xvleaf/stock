import os
import tushare as ts
import akshare as ak
import pandas as pd

# 从环境变量读取TUSHARE的TOKEN
TUSHARE_TOKEN = os.getenv('DJANGO_TUSHARE_TOKEN')
# 交易开始时间，对应时间戳
TRADE_AM_START = int(os.getenv('STOCK_TRADE_AM_START'))
# 交易休息时间
TRADE_AM_END = int(os.getenv('STOCK_TRADE_AM_END'))
# 交易回复时间
TRADE_PM_START = int(os.getenv('STOCK_TRADE_PM_START'))
# 交易休息时间
TRADE_PM_END = int(os.getenv('STOCK_TRADE_PM_END'))

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


# *****新建交易日历数据库*****
def get_trade_cal(start, end):
    """
    获取指定时间段的交易日历数据
    :param start: str 20250101
    :param end: str 20260725
    :return: DataFrame
    """
    # cal_date 日历日期
    # is_open 是否交易 '0'休市 '1'交易
    # pretrade_date 上一个交易日
    fields = 'cal_date,is_open,pretrade_date'
    # exchange为空查询沪深全市场交易日历
    cal = pro.trade_cal(exchange='', start_date=start, end_date=end, fields=fields)
    return cal


def get_all_industry():
    """
    获取全部行业指数下的一级行业分类信息
    :return: DataFrame 一级行业分类数据
    """
    # index_code 一级行业代码
    # industry_name 一级行业名称
    fields = 'index_code,industry_name'
    member = pro.index_classify(level='L1', fields=fields)
    return member


def get_industry_member(code):
    """
    获取指定行业指数下的一级行业分类信息
    :param code: str 行业指数代码（801xxxx.SI）
    :return: DataFrame 一级行业分类数据
    """
    # l1_code 一级行业代码
    # l1_name 一级行业名称
    fields = 'l1_code,l1_name'
    member = pro.index_member_all(ts_code=code, fields=fields)
    return member


def get_match_industry(industry_code):
    """
    根据一级行业代码，查询该行业下全部成分股票
    :param industry_code: str 801110.SI（一级行业l1_code代码）
    :return: DataFrame 行业成分股列表
    """
    fields = 'ts_code,name'
    member = pro.index_member_all(l1_code=industry_code, fields=fields)
    return member


# *****重新修改数据库*****
# *****可以通过更新数据，将退市股票剔除，非删除，仅标注，因为可能有交易*****
def get_stock_basic():
    """
    获取A股上市股票基础信息列表
    :return: DataFrame
    """
    # ts_code 000333.SZ
    # symbol 000333
    # exchange 交易所 SSE上交所 SZSE深交所 BSE北交所
    # market 市场类别 （主板/创业板/科创板/CDR/北交所）
    # industry 所属行业
    fields = 'symbol,name,exchange,market,industry'

    # list_status='L' 仅返回正常上市股票
    # exchange为空查询全市场
    data = pro.stock_basic(exchange='', list_status='L', fields=fields)
    return data


# ========================= 以下代码备用 =========================
# *****fund_basic接口获得的基金列表，与get_kline_data不对应，get_kline_data能得到ETF基金的K线*****
# *****etf_basic接口无权限调用（需要5000积分以上）*****
def get_fund_basic():
    """
    获取基金基础信息列表
    :return: DataFrame
    """
    # ts_code 159526.SZ
    # type 基金类型
    fields = 'ts_code,name,type'

    # market='E' 交易市场: E场内 O场外
    # status='L' 仅返回上市基金
    data = pro.etf_basic(market='E', status='L', fields=fields)
    return data


# *****cb_basic接口得到的转债列表，仅部分可采用get_kline_data能得到K线，因此只能用来辅助*****
# *****重新修改数据库*****
# *****可以通过更新数据，将退市基金剔除，非删除，仅标注，因为可能有交易*****
def get_bond_basic():
    """
    获取可转债基础信息列表
    :return: DataFrame
    """
    # ts_code 125959.SZ
    # bond_short_name 可转债简称
    # cb_type 转债类型: CB-可转债,EB-可交换债
    # stk_code	正股代码
    # stk_short_name 正股简称
    # exchange 交易所 SH上交所 SZ深交所
    fields = 'ts_code,bond_short_name,cb_type,stk_code,stk_short_name,exchange'
    data = pro.cb_basic(fields=fields)
    return data


# *****当天的日/周/月K线只有当天收盘后才更新，因此需要自行添加当天的*****
# *****FD/CB数据周线和月线需要根据日线自行处理*****
# *****考虑应用中取消FD/CB相关的功能*****
# *****K线只能是收盘数据，当天不是实时数据*****
def get_kline_data(asset, tscode, start, end, freq='D', adj=None):
    """
    获取股票/基金/债券的K线（基于TuShare）
    :param asset: 资产类别：E股票 I沪深指数 FT期货 FD基金 O期权 CB可转债
    :param ts_code: ts标准代码 000333.SZ
    :param start: 起始日期 str YYYYMMDD (注意起始日数据是不全的，因此数据从下一个交易日开始)
    :param end: 结束日期 str YYYYMMDD
    :param freq: 周期 D日 W周 M月
    :param adj: None不复权 qfq前复权 hfq后复权
    :return: DataFrame
    """
    
    base_fields = [
        'ts_code', 'trade_date', 'open', 'close', 'high', 'low', 'pre_close',
        'change', 'pct_chg', 'vol', 'amount'
    ]

    kline = pd.DataFrame(columns=base_fields)

    # 资产类型映射（修正 'FT' → 'F'）
    asset_map = {'E': 'E', 'I': 'I', 'FD': 'FD', 'CB': 'CB'}
    if asset not in asset_map:
        # 返回空 DataFrame 数据
        return kline

    # 如果为日线股票可以获取换手率与量比
    if asset == 'E' and freq == 'D':
        base_fields.extend(['turnover_rate','volume_ratio'])

    fields = ','.join(base_fields)

    # 未复权日线也可调用daily接口
    # 周线/月线也可调用stk_week_month及stk_week_month_adj接口
    # 也可以采用自定义函数 kline_freq_from_daily(kline, freq)，注意该函数不会出现数据缺失的情况，因此下面中的 iloc[1:] 不需要
    if asset == 'E':
        kline = ts.pro_bar(asset=asset, ts_code=tscode, freq=freq, adj=adj, start_date=start, end_date=end, factors=['tor', 'vr'], fields=fields)        
    
    elif asset == 'FD':
        # 仅能得到日线数据，周线数据需要自行得到
        kline = ts.pro_bar(asset=asset, ts_code=tscode, freq=freq, start_date=start, end_date=end, fields=fields)

    elif asset == 'CB':
        # 仅能得到日线数据，周线数据需要自行得到
        kline = pro.cb_daily(ts_code=tscode, start_date=start, end_date=end, fields=fields)
    
    # elif asset == 'I':
    else:
        kline = ts.pro_bar(asset=asset, ts_code=tscode, freq=freq, adj=adj, start_date=start, end_date=end, fields=fields)

    # 按交易日期升序排列（否则默认是最新在前）
    # 由于第一个数据缺少 pre_close，change，pct_chg这三项，因此从第二个数据开始
    if kline is not None and not kline.empty:
        kline = kline.sort_values('trade_date', ignore_index=True).iloc[1:]

    return kline


# 备用，trend.py 采用了 ashare 的实时数据
# 本函数采用了 akshare，仅能采集收盘后的数据
def get_trend_data(tscode, deci):
    """
    获取分时数据(采用1分钟K线等效，基于AKshare）
    :param tscode: str 000333.SZ
    :param deci: int 2或3，保留小数位数
    :return: 结构化结果字典
    """

    get_data = _for_trend_data(tscode, deci)

    if not get_data:
        return {}
    
    last_time = get_data['last_time']
    clock_zero = get_data['clock_zero']
    pre_close = get_data['pre_close']
    trend = get_data['trend']
    
    # 交易时段时间点
    am_start = clock_zero + pd.Timedelta(seconds=TRADE_AM_START)
    am_end = clock_zero + pd.Timedelta(seconds=TRADE_AM_END)
    pm_start = clock_zero + pd.Timedelta(seconds=TRADE_PM_START)
    pm_end = clock_zero + pd.Timedelta(seconds=TRADE_PM_END)

    # 上午交易时段
    am_range = pd.date_range(start=am_start, end=am_end, freq='1min')
    # 下午交易时段
    pm_range = pd.date_range(start=pm_start, end=pm_end, freq='1min')
    # 合并两段索引
    full_trade_index = am_range.union(pm_range)

    # 将 day 列设置为索引
    trend = trend.set_index('day')
    # 将上午与下午时段每分钟填满数据
    trend = trend.reindex(full_trade_index, copy=False)
    # 将所有空白close整体向前填充ffill
    trend['close'] = trend['close'].ffill()
    # index_last_time 用于确定最后一组有效数据位置，由于填充了数据，有效数据对应的位置变化了，因此根据last_time来锁定位置
    # 由于已将 day 列设置为索引，此时行索引本身就是 datetime，last_time 就是索引里的元素
    index_last_time = trend.index.get_loc(last_time)

    # 筛选 9:30 之后第一个有效 open
    after_am_trend = trend.loc[trend.index > am_start, 'open']
    index_am = after_am_trend.first_valid_index()
    valid_am_open = after_am_trend.loc[index_am] if index_am is not None else None
    if valid_am_open is not None:
        trend.at[am_start, 'close'] = valid_am_open

    # 筛选 13:00 之后第一个有效 open
    after_pm_trend = trend.loc[trend.index > pm_start, 'open']
    index_pm = after_pm_trend.first_valid_index()
    valid_pm_open = after_pm_trend.loc[index_pm] if index_pm is not None else None
    if valid_pm_open is not None:
        trend.at[pm_start, 'close'] = valid_pm_open

    # 全部空缺成交量、成交额均置0
    trend[['volume', 'amount']] = trend[['volume', 'amount']].fillna(0)    
    # 将 volume 列转化为 int 类型
    trend['volume'] = trend['volume'].astype(int)

    # 恢复时间字段，否则无法使用trend['day']
    trend.reset_index(names='day', inplace=True)
    # astype(int)： 得到纳秒时间戳 / 1000 得到毫秒时间戳（13位）；//：代表整除，结果为整数
    trend['day'] = trend['day'].astype('int64') // 1000000

    # 新增两列 percent 和 delta
    trend['percent'] = round((trend['close'] - pre_close) / pre_close * 100, 2)
    trend['delta'] = round(trend['close'] - pre_close, deci)

    ohlc = []
    volume = []
    for row in trend.itertuples(index=False):
        ohlc.append([row.day, row.close, row.percent, row.delta])
        volume.append([row.day, row.volume])

    # 当日全部close最大值、最小值
    high = trend['close'].max()
    low = trend['close'].min()

    tick_gap = max(abs(pre_close - high), abs(pre_close - low))
    tick_gap = 1.2 * tick_gap if tick_gap > 0 else pre_close * 0.1
    unit = 10 ** (-deci)
    tick_itv = max(round(tick_gap / 2, deci), unit)
    tick_max = round(pre_close + 2 * tick_itv, deci)
    tick_min = round(pre_close - 2 * tick_itv, deci)

    return {
        'pc': pre_close,
        'high': high,
        'low': low,
        'deci': deci,
        'index': index_last_time,
        'tick_itv': tick_itv,
        'tick_max': tick_max,
        'tick_min': tick_min,
        'ohlc': ohlc,
        'volume': volume
    }


def _for_trend_data(tscode, deci):
    """
    为 get_trend_data 提供分时数据(采用1分钟K线等效）
    :param tscode: str 000333.SZ
    :param deci: int 2或3，保留小数位数
    :return: 字典
    """
     # 将 ts 代码转换为 ak 代码
    num, suffix = tscode.split('.')
    akcode = f'{suffix.lower()}{num}'
    # freq 可以取1/5/15/30/60分钟，本函数用于获取分时数据，取1
    try:
        trend = ak.stock_zh_a_minute(symbol=akcode, freq='1', adjust='qfq')
    except Exception:
        return {}

    if trend.empty:
        return {}

    trend['day'] = pd.to_datetime(trend['day'])
    # 取最后一条数据的时间戳
    last_time = trend['day'].iloc[-1]
    # 开始时间为数据最后一天零点
    clock_zero = last_time.normalize()

    pre_trend = trend.loc[trend['day'] < clock_zero]
    pre_close = pre_trend['close'].iloc[-1] if not pre_trend.empty else None
    
    if pre_close is None:
        return {}

    # 筛选数据最后一天全部数据
    trend = trend.loc[trend['day'] >= clock_zero]
    return {
        'last_time': last_time,
        'clock_zero': clock_zero,
        'pre_close': pre_close,
        'trend': trend
    }
