import os
import datetime
import pytz
import pandas as pd
from . import ashare
from stock import func

AM_START = int(os.environ.get('STOCK_TRADE_AM_START', 34200))   # 09:30
AM_END   = int(os.environ.get('STOCK_TRADE_AM_END', 41400))     # 11:30
PM_START = int(os.environ.get('STOCK_TRADE_PM_START', 46800))   # 13:00
PM_END   = int(os.environ.get('STOCK_TRADE_PM_END', 54000))     # 15:00

TREND_PARAMS_INIT = {
}


def trend_data_for_chart(session, tscode, step, deci=2):
    """
    获取分时图数据
    :param tscode: 股票代码（如 '000333.SZ'）
    :param step: 字符串 '0' 表示初始化，'1' 表示增量更新
    :param session: django session 对象（用于记录最后数据的时间戳和当前交易日）
    :return: 字典，格式与 trend.js 的预期一致
    """
    tscode = tscode.upper()
    if tscode.endswith('.SZ'):
        code = 'sz' + tscode.replace('.SZ', '')
    else:
        code = 'sh' + tscode.replace('.SH', '')

    # 获取最新交易日分钟线 + 对应前收盘价（全部从分钟线推导，无外部依赖）
    df, pre_close = _get_today_minute_data(code)
    if df is None or pre_close is None:
        # 无数据时返回空结构
        return {
            'ohlc': [],
            'volume': [],
            'index': 0,
            'pc': 0.0,
            'deci': deci,
            'tick_itv': 0,
            'tick_max': 0,
            'tick_min': 0,
            'reset': False
        }

    # 当前分时数据对应的交易日
    current_trade_date = df.index.date[-1].strftime('%Y-%m-%d')
    # 从 Session 读取上一次记录的交易日
    session_trade_date = session.get('current_trade_date', None)

    # 核心判断：是否需要全量重置
    # 触发条件：初始化请求 / 交易日发生切换（盘前→开盘、跨周末/节假日、停牌后复牌等）
    need_reset = (step == '0') or (session_trade_date != current_trade_date)

    # 构建 ohlc / volume 数据列表
    ohlc = []
    volume = []
    for idx, row in df.iterrows():
        ts = int(idx.timestamp() * 1000)          # 毫秒时间戳
        close = row['close']
        delta = close - pre_close
        percent = (delta / pre_close * 100) if pre_close != 0 else 0.0
        ohlc.append([ts, close, percent, delta])
        volume.append([ts, row['volume']])
        
    # 计算 Y 轴参数
    tick_min, tick_max, tick_itv = _calc_tick_params(df, pre_close, deci)

    # 全量重置场景
    if need_reset:
        session['current_trade_date'] = current_trade_date
        if ohlc:
            session['last_timestamp'] = ohlc[-1][0]
        return {
            'ohlc': ohlc,
            'volume': volume,
            'index': len(ohlc),
            'pc': pre_close,
            'deci': deci,
            'tick_itv': tick_itv,
            'tick_max': tick_max,
            'tick_min': tick_min,
            'reset': True
        }

    # 正常增量更新场景（交易日未变化）
    last_ts = session.get('last_timestamp', None)
    new_ohlc = []
    new_volume = []
    if last_ts is not None:
        for o_item, v_item in zip(ohlc, volume):
            if o_item[0] > last_ts:
                new_ohlc.append(o_item)
                new_volume.append(v_item)
    else:
        new_ohlc = ohlc
        new_volume = volume

    if new_ohlc:
        session['last_timestamp'] = new_ohlc[-1][0]

    return {
        'ohlc': new_ohlc,
        'volume': new_volume,
        'index': len(new_ohlc),
        'pc': pre_close,
        'deci': deci,
        'tick_itv': tick_itv,
        'tick_max': tick_max,
        'tick_min': tick_min,
        'reset': False
    }


def get_trend_params(session):
    trend_params = func.get_session(session, 'trend_params', TREND_PARAMS_INIT)
    return trend_params


def set_trend_params(session, key, value):
    trend_params = func.get_session(session, 'trend_params', TREND_PARAMS_INIT)
    trend_params[key] = value
    func.set_session(session, 'trend_params', trend_params)


def _get_today_minute_data(code):
    """
    获取【最新一个有交易交易日】的全部 1 分钟 K 线，并过滤交易时段
    同时从分钟线数据中推导该交易日对应的前一交易日收盘价
    自动兼容：盘中、盘前、当日停牌、周末/节假日、新股首日
    :param code: 带市场前缀的代码，如 'sz000333'
    :return: (df, pre_close)
        df: 按时间升序的 DataFrame，包含 open/close/high/low/volume；失败返回 None
        pre_close: 对应前一交易日收盘价；失败返回 None
    """
    try:
        # count=300 保证覆盖最新交易日全天 + 前一交易日尾盘（足够提取昨收）
        df = ashare.get_price(code, frequency='1m', count=300)        
        if df is None or df.empty:
            return None, None

        # 时区统一处理
        tz = pytz.timezone('Asia/Shanghai')
        if df.index.tz is None:
            df.index = df.index.tz_localize(tz, ambiguous='infer')

        # 过滤非交易时段脏数据
        df = df[df.index.map(_is_trading_time)]        
        if df.empty:
            return None, None

        df = df.sort_index()

        # 提取所有有真实交易的日期，升序排列
        trade_dates = sorted(df.index.normalize().unique().date)
        if not trade_dates:
            return None, None

        # 取最新的交易日作为分时展示目标
        target_date = trade_dates[-1]
        target_df = df[df.index.date == target_date].copy()
        if target_df.empty:
            return None, None

        # 从分钟线内部推导前收盘价，不再依赖外部接口
        if len(trade_dates) >= 2:
            prev_date = trade_dates[-2]
            prev_day_df = df[df.index.date == prev_date]
            if not prev_day_df.empty:
                pre_close = float(prev_day_df.iloc[-1]['close'])
            else:
                pre_close = None
        else:
            # 仅1个交易日（如新股上市首日），用当日第一笔开盘价兜底
            pre_close = float(target_df.iloc[0]['open']) if not target_df.empty else None

        return target_df, pre_close

    except Exception:
        return None, None


def _is_trading_time(dt):
    """
    判断给定时间是否在交易时段内
    """
    sec = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (AM_START <= sec <= AM_END) or (PM_START <= sec <= PM_END)


def _calc_tick_params(df, pre_close, deci=2):
    """
    计算 Y 轴范围 (tick_min, tick_max) 和刻度间隔 (tick_itv)
    以前收盘价为中心，上下各扩展实际波动的 10%，保证至少 ±1%
    """
    if df.empty:
        return 0, 0, 0
    min_c = df['close'].min()
    max_c = df['close'].max()

    # 实际波动范围
    range_c = max_c - min_c
    if range_c == 0:
        range_c = abs(pre_close) * 0.01 if pre_close != 0 else 0.01

    # 扩展 10%
    lower = min(min_c, pre_close) - range_c * 0.1
    upper = max(max_c, pre_close) + range_c * 0.1

    # 保证最小范围（至少 ±1%）
    if upper - lower < abs(pre_close) * 0.01:
        upper = pre_close * 1.01
        lower = pre_close * 0.99

    tick_itv = (upper - lower) / 5
    tick_itv = round(tick_itv, deci)
    if tick_itv <= 0:
        tick_itv = 0.01

    return lower, upper, tick_itv