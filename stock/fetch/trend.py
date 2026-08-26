import os
import datetime
import pytz
import pandas as pd
from . import ashare
from stock import func

QUOTE_REQUEST_INTERVAL = int(os.environ.get('QUOTE_REQUEST_INTERVAL', 20000))   # 09:30
AM_START = int(os.environ.get('STOCK_TRADE_AM_START', 34200))   # 09:30
AM_END   = int(os.environ.get('STOCK_TRADE_AM_END', 41400))     # 11:30
PM_START = int(os.environ.get('STOCK_TRADE_PM_START', 46800))   # 13:00
PM_END   = int(os.environ.get('STOCK_TRADE_PM_END', 54000))     # 15:00


def trend_data_for_chart(session, tscode, step, deci=2):
    """
    获取分时图数据
    :param tscode: 股票代码（如 '000333.SZ'）
    :param step: 字符串 '0' 表示初始化，'1' 表示增量更新
    :param session: django session 对象
    :return: 字典，格式与 trend.js 的预期一致
    """
    tscode = tscode.upper()
    if tscode.endswith('.SZ'):
        code = 'sz' + tscode.replace('.SZ', '')
    else:
        code = 'sh' + tscode.replace('.SH', '')

    df, pre_close = _get_today_minute_data(code)
    if df is None or pre_close is None:
        # 无数据时重置 session 时间戳
        session['last_timestamp'] = None
        return {
            'ohlc': [],
            'volume': [],
            'pc': 0.0,
            'deci': deci,
            'tick_itv': 0,
            'tick_max': 0,
            'tick_min': 0,
            'reset': False,
        }

    current_trade_date = df.index.date[-1].strftime('%Y-%m-%d')
    session_trade_date = session.get('current_trade_date', None)
    need_reset = (step == '0') or (session_trade_date != current_trade_date)

    last_valid_ts = int(df.index[-1].timestamp() * 1000)
    tick_min, tick_max, tick_itv = _calc_tick_params(df, pre_close, deci)

    # ----- 重置场景：返回全天完整数据 -----
    if need_reset:
        full_ohlc, full_volume, _ = _build_full_day_data(df, pre_close)
        session['current_trade_date'] = current_trade_date
        session['last_timestamp'] = last_valid_ts
        return {
            'ohlc': full_ohlc,
            'volume': full_volume,
            'pc': pre_close,
            'deci': deci,
            'tick_itv': tick_itv,
            'tick_max': tick_max,
            'tick_min': tick_min,
            'reset': True,
        }

    # ----- 增量更新：仅返回新数据 -----
    last_ts = session.get('last_timestamp', None)
    new_ohlc = []
    new_volume = []

    if last_ts is not None:
        for idx, row in df.iterrows():
            ts = int(idx.timestamp() * 1000)
            if ts > last_ts:
                close = row['close']
                delta = close - pre_close
                percent = (delta / pre_close * 100) if pre_close != 0 else 0.0
                new_ohlc.append([ts, close, percent, delta])
                new_volume.append([ts, row['volume']])
    else:
        # session 丢失时间戳，强制返回全量数据并标记重置
        full_ohlc, full_volume, _ = _build_full_day_data(df, pre_close)
        session['current_trade_date'] = current_trade_date
        session['last_timestamp'] = last_valid_ts
        return {
            'ohlc': full_ohlc,
            'volume': full_volume,
            'pc': pre_close,
            'deci': deci,
            'tick_itv': tick_itv,
            'tick_max': tick_max,
            'tick_min': tick_min,
            'reset': True,
        }

    if new_ohlc:
        session['last_timestamp'] = new_ohlc[-1][0]

    return {
        'ohlc': new_ohlc,
        'volume': new_volume,
        'pc': pre_close,
        'deci': deci,
        'tick_itv': tick_itv,
        'tick_max': tick_max,
        'tick_min': tick_min,
        'reset': False,
    }


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


def _build_full_day_data(df, pre_close, deci=2):
    """
    根据实际分钟数据 df 和前收盘价 pre_close，生成全天交易时段（仅 AM_START~AM_END 和 PM_START~PM_END）的完整分钟序列。
    对缺失的数据点（无成交）保留 NaN（不填充任何值），前端可识别为空。
    返回 (ohlc, volume, last_valid_idx)
        ohlc: 完整列表，每个元素为 [timestamp, close, percent, delta]，若 close 为 NaN，则 percent/delta 为 None
        volume: 完整列表，每个元素为 [timestamp, volume]，若 volume 缺失则为 None
        last_valid_idx: 最后一个有效数据在 ohlc 中的索引（基于原始 df 的最后一个时间戳）
    """
    if df is None or df.empty:
        return [], [], -1

    tz = pytz.timezone('Asia/Shanghai')
    target_date = df.index.date[-1]

    # 构造上午时段索引
    am_start_dt = datetime.datetime.combine(
        target_date,
        datetime.time(AM_START // 3600, (AM_START % 3600) // 60)
    )
    am_end_dt = datetime.datetime.combine(
        target_date,
        datetime.time(AM_END // 3600, (AM_END % 3600) // 60)
    )
    am_index = pd.date_range(start=am_start_dt, end=am_end_dt, freq='1min', tz=tz)

    # 构造下午时段索引
    pm_start_dt = datetime.datetime.combine(
        target_date,
        datetime.time(PM_START // 3600, (PM_START % 3600) // 60)
    )
    pm_end_dt = datetime.datetime.combine(
        target_date,
        datetime.time(PM_END // 3600, (PM_END % 3600) // 60)
    )
    pm_index = pd.date_range(start=pm_start_dt, end=pm_end_dt, freq='1min', tz=tz)

    full_index = am_index.union(pm_index).sort_values()

    # 重新索引，保留 NaN，不填充任何值
    full_df = df.reindex(full_index)

    # 提取 close 和 volume（可能为 NaN）
    close_series = full_df['close']
    volume_series = full_df['volume']

    ohlc = []
    volume = []
    for idx in full_index:
        ts = int(idx.timestamp() * 1000)
        close_val = close_series.loc[idx]
        if pd.isna(close_val):
            # 空数据点：close 为 NaN，delta 和 percent 为 None
            ohlc.append([ts, None, None, None])
        else:
            # 有效数据点：计算涨跌幅
            delta = close_val - pre_close
            percent = (delta / pre_close * 100) if pre_close != 0 else 0.0
            ohlc.append([ts, close_val, percent, delta])

        # volume：如果缺失则为 None
        vol_val = volume_series.loc[idx]
        if pd.isna(vol_val):
            volume.append([ts, None])
        else:
            volume.append([ts, vol_val])

    # 查找最后一个有效数据的位置（基于原始 df 的最后一条记录）
    last_valid_ts = int(df.index[-1].timestamp() * 1000)
    last_valid_idx = -1
    for i, item in enumerate(ohlc):
        if item[0] == last_valid_ts:
            last_valid_idx = i
            break

    return ohlc, volume, last_valid_idx


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


