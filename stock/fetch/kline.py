import os
import pandas as pd
import datetime
from django.http import JsonResponse
from . import tushare
from stock import func

# 交易休息时间
KLINE_START_DATE = os.getenv('KLINE_START_DATE')

KLINE_MA_CONFIG = {
    'D': {'ma': int(os.getenv('KLINE_MA_DAY')), 'mv': int(os.getenv('KLINE_MV_DAY'))},
    'W': {'ma': int(os.getenv('KLINE_MA_WEEK')), 'mv': int(os.getenv('KLINE_MV_WEEK'))},
    'M': {'ma': int(os.getenv('KLINE_MA_MONTH')),'mv': int(os.getenv('KLINE_MV_MONTH'))},
}

KLINE_EMA_CONFIG = {
    'D': {'k': int(os.getenv('KLINE_EMA_K_DAY')), 'd': int(os.getenv('KLINE_EMA_D_DAY'))},
    'W': {'k': int(os.getenv('KLINE_EMA_K_WEEK')), 'd': int(os.getenv('KLINE_EMA_D_WEEK'))},
    'M': {'k': int(os.getenv('KLINE_EMA_K_MONTH')), 'd': int(os.getenv('KLINE_EMA_D_MONTH'))},
}

KLINE_PARAMS_INIT = {
    'freq': 'D',
    'right': 'qfq',
    'k': KLINE_EMA_CONFIG['D']['k'],
    'd': KLINE_EMA_CONFIG['D']['d'],
    'deci': 2
}


def kline_data_for_chart(session, cat, market, code):
    """
    tushare 获取 k 线，包括轨道线
    :param asset: E股票 I沪深指数 FD基金 CB可转债
    :param tscode: str '000333.SZ'
    :param freq：'D'日线 'W'周线 'M'月线
    :param right: 'qfq' 或 None
    """
    tscode = f'{code}.{market}'
    
    deci_map = {'stock': 2}
    asset_map = {'stock': 'E'}

    kline_params = get_kline_params(session)
    freq = kline_params['freq']
    right = kline_params['right']
    k = kline_params['k']
    d = kline_params['d']
    deci = deci_map[cat]
    print(cat, market, code, freq, right, k, d ,deci)
    # 取近两年日线数据
    start = KLINE_START_DATE # or (datetime.datetime.now() - datetime.timedelta(days=730)).strftime('%Y%m%d')
    end = datetime.datetime.now().strftime('%Y%m%d')

    df = tushare.get_kline_data(
        asset=asset_map[cat],
        tscode=tscode,
        start=start,
        end=end,
        freq=freq,
        adj=right
    )

    if df is None or df.empty:
        return JsonResponse(df)

    df = df.dropna(subset=['open', 'high', 'low', 'close', 'vol'])
    df = df.sort_values('trade_date').reset_index(drop=True)

    if df.empty:
        return JsonResponse(df)

    # 一次性返回完整数据
    result = _handle_kline_full(df, freq, right, k, d, deci)

    return JsonResponse(result)


def get_kline_params(session):
    kline_params = func.get_session(session, 'kline_params', KLINE_PARAMS_INIT)
    return kline_params


def set_kline_params(session, key, value):
    kline_params = func.get_session(session, 'kline_params', KLINE_PARAMS_INIT)
    kline_params[key] = value
    func.set_session(session, 'kline_params', kline_params)


def _handle_kline_full(df, freq, right, k, d, deci):
    ohlc = []
    volume = []

    for _, row in df.iterrows():
        ts = func.date_to_timestamp(row['trade_date'])
        ohlc.append([
            ts,
            round(row['open'], deci),
            round(row['high'], deci),
            round(row['low'], deci),
            round(row['close'], deci),
            round(row['pct_chg'], 2) if pd.notna(row['pct_chg']) else 0
        ])

        volume.append([ts, int(row['vol'])])

    # EMA 轨道线
    tp, up, av, lw, fl = _calc_ema_track_line(df, k, d, deci)

    # 简单均线与均量线
    ma = _calc_simple_ma_line(df, 'close', window=KLINE_MA_CONFIG[freq]['ma'], deci=deci)
    mv = _calc_simple_ma_line(df, 'vol', window=KLINE_MA_CONFIG[freq]['mv'], deci=0)

    deadline = func.date_to_timestamp(df['trade_date'].iloc[-1]) if not df.empty else 0

    # 交易信号预留
    deal = {'long': [], 'short': [], 'dual': [], 'divd': []}

    return {
        'ohlc': ohlc,
        'volume': volume,
        'tp': tp,
        'up': up,
        'av': av,
        'lw': lw,
        'fl': fl,
        'ma': ma,
        'mv': mv,
        'deal': deal,
        'deadline': deadline,
        'deci': deci,
        'k': k,
        'd': d,
        'right': right,
        'freq': freq,
    }


def _calc_ema_track_line(df, k, d, deci):
    """
    EWMA 轨道线
    :param k: 轨道宽度百分比（整数）
    :param d: EMA 周期
    :return: tp, up, av, lw, fl 五个等长数组
    """
    close_series = df['close']
    # 指数加权移动平均（中轨 av）
    av_series = close_series.ewm(span=d, adjust=False).mean().round(deci)

    # 轨道系数
    k_tp = 1 + 2 * k / 100
    k_up = 1 + k / 100
    k_lw = 1 - k / 100
    k_fl = 1 - 2 * k / 100

    tp_series = (av_series * k_tp).round(deci)
    up_series = (av_series * k_up).round(deci)
    lw_series = (av_series * k_lw).round(deci)
    fl_series = (av_series * k_fl).round(deci)

    tp_list, up_list, av_list, lw_list, fl_list = [], [], [], [], []
    for trade_date, tp, up, av, lw, fl in zip(
        df['trade_date'], tp_series, up_series, av_series, lw_series, fl_series
    ):
        ts = func.date_to_timestamp(trade_date)
        tp_list.append([ts, tp if pd.notna(tp) else None])
        up_list.append([ts, up if pd.notna(up) else None])
        av_list.append([ts, av if pd.notna(av) else None])
        lw_list.append([ts, lw if pd.notna(lw) else None])
        fl_list.append([ts, fl if pd.notna(fl) else None])

    return tp_list, up_list, av_list, lw_list, fl_list


def _calc_simple_ma_line(df, col, window, deci):
    """
    简单移动平均线
    返回与df等长数组，索引一一对应，前window-1个值为None
    """
    ma_series = df[col].rolling(window=window).mean().round(deci)
    result = []
    for trade_date, value in zip(df['trade_date'], ma_series):
        ts = func.date_to_timestamp(trade_date)
        result.append([ts, value if pd.notna(value) else None])
    return result


# 备用
def _kline_freq_from_daily(df, freq):
    """
    根据日线聚合为周线或月线
    :Param df : DataFrame 日线数据，索引必须为 DatetimeIndex（由 'trade_date' 设置）
    :freq : str 'W' 周线（按周五收盘），'M' 月线
    :Returns: pd.DataFrame
    """
    # 转换 trade_date 为 datetime
    df['trade_date'] = pd.to_datetime(df['trade_date'])
    df = df.set_index('trade_date')

    # 确保索引已排序（对于 resample 很重要）
    df = df.sort_index()

    # 添加一列保存真实的日期（索引值）
    df['real_date'] = df.index

    # 定义聚合规则
    agg_dict = {
        # 取该周期最后一个交易日期
        'real_date': 'last',
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'vol': 'sum',
        'amount': 'sum'
    }

    # 执行重采样
    if freq == 'W':
        # 按周五结束
        resampled = df.resample('W-FRI').agg(agg_dict)
    # elif freq == 'M':
    else:
        # 按自然月末
        resampled = df.resample('ME').agg(agg_dict)  

    # 删除空行（完全没有交易数据的周期）
    resampled = resampled.dropna(how='all')

    # 将 real_date 设为新索引（覆盖原来的边界日期）
    resampled.set_index('real_date', inplace=True)
    # 删除原来的索引名称（原索引列已被替换）
    resampled.index.name = None

    # 计算 pre_close, change, pct_chg
    resampled['pre_close'] = resampled['close'].shift(1)
    resampled['change'] = resampled['close'] - resampled['pre_close']
    # 避免除零，若 pre_close 为 0 或 NaN，则 pct_chg 为 NaN
    resampled['pct_chg'] = (resampled['change'] / resampled['pre_close']) * 100
    resampled['pct_chg'] = resampled['pct_chg'].round(2)   # 保留两位小数

    # 重置索引，将日期变为列 trade_date
    resampled = resampled.reset_index()
    resampled.rename(columns={'index': 'trade_date'}, inplace=True)

    # 添加 ts_code（如果原始数据有该列）
    resampled['ts_code'] = df['ts_code'].iloc[0]

    # 重置索引，将日期变为普通列
    resampled = resampled.reset_index()

    # 调整列顺序，确保与标准字段一致
    final_cols = ['ts_code', 'trade_date', 'open', 'close', 'high', 'low',
                  'pre_close', 'change', 'pct_chg', 'vol', 'amount']                  
    resampled = resampled[final_cols]
    
    return resampled
