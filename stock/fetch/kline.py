import logging
import pandas as pd
import datetime
from bisect import bisect_left
from collections import defaultdict
from django.http import JsonResponse
from . import tushare
from .config import (get_kline_start_date, get_kline_ma_period, get_kline_mv_period,
                     get_kline_ema_k, get_kline_ema_d, get_kline_density)
import akshare as ak
from .. import utils
from ..models import TransHistory, TransOrder

logger = logging.getLogger('stock')


def _get_kline_ma_config(freq):
    """获取指定周期的MA/MV配置"""
    return {
        'ma': get_kline_ma_period(freq),
        'mv': get_kline_mv_period(freq),
    }


def _get_kline_ema_config(freq):
    """获取指定周期的EMA配置"""
    return {
        'k': get_kline_ema_k(freq),
        'd': get_kline_ema_d(freq),
    }


def _get_kline_params_init():
    """获取K线参数初始化值"""
    ema_d = _get_kline_ema_config('D')
    return {
        'freq': 'D',
        'right': 'qfq',
        'k': ema_d['k'],
        'd': ema_d['d'],
        'deci': 2,
        'deadline': -1,
        'density': get_kline_density()
    }


def kline_data_for_chart(session, site, cat, market, code):
    """
    tushare 获取 k 线，包括轨道线
    :param asset: E股票 I沪深指数 FD基金 CB可转债
    :param tscode: str '000333.SZ'
    :param freq：'D'日线 'W'周线 'M'月线
    :param right: 'qfq' 或 None
    """
    tscode = f'{code}.{market}'
    asset_map = {'stock': 'E', 'fund': 'FD', 'bond': 'CB', 'index': 'I'}

    kline_params = get_kline_params(session)
    freq = kline_params['freq']
    right = kline_params['right']
    k = int(kline_params['k'])
    d = int(kline_params['d'])
    deci = 3 if cat in ('fund', 'bond') else 2

    if cat == 'index':
        right = None

    if site == '/sector/view':
        period = {'D': 'day', 'W': 'week', 'M':'month'}
        df = ak.index_hist_sw(symbol=code, period=period[freq])
        df.rename(columns={
            '代码': 'ts_code', 
            '日期': 'trade_date', 
            '收盘': 'close', 
            '开盘': 'open', 
            '最高': 'high', 
            '最低': 'low', 
            '成交量': 'vol', 
            '成交额': 'amount'
            }, 
            inplace=True
        )

        start_date = pd.to_datetime(get_kline_start_date(freq))
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df[df['trade_date'] >= start_date]
        df.sort_values('trade_date', inplace=True)

        df['pre_close'] = df['close'].shift(1)
        df['change'] = df['close'] - df['pre_close']
        df['pct_chg'] = (df['change'] / df['pre_close'] * 100).round(2)
        df['vol'] = df['vol'] * 10000
        df = df.tail(-1)
        
    else:
        start = get_kline_start_date(freq)
        end = datetime.datetime.now().strftime('%Y%m%d')

        df = tushare.get_kline_data(
            asset=asset_map.get(cat, 'E'),
            tscode=tscode,
            start=start,
            end=end,
            freq=freq,
            adj=right
        )
    
    if df is None or df.empty:
        result = {
            'ohlc': [],
            'volume': [],
            'tp': [],
            'up': [],
            'av': [],
            'lw': [],
            'fl': [],
            'ma': [],
            'mv': [],
            'deal': [],
            'deadline': -1,
            'deci': deci,
            'k': k,
            'd': d,
            'right': right,
            'freq': freq,
        }
        return JsonResponse(result)

    df = df.dropna(subset=['open', 'high', 'low', 'close', 'vol'])
    df = df.sort_values('trade_date').reset_index(drop=True)

    deadline_params = utils.get_cache(session, 'kline-deadline')
    if deadline_params and (site, code, market) == deadline_params.get('site_code_market', None):
        deadline = deadline_params.get('deadline', -1)
        # 转换为字符串用于存储（确保 JSON 可序列化）
        if isinstance(deadline, (datetime.date, datetime.datetime)):
            deadline_str = deadline.strftime('%Y%m%d')
        else:
            deadline_str = str(deadline)
        # 存入 kline_params，以便前端或其他地方使用
        set_kline_params(session, 'deadline', deadline_str)

        # 转换 deadline 为时间戳（包含全天数据）
        if isinstance(deadline, (datetime.date, datetime.datetime)):
            if isinstance(deadline, datetime.date):
                dt = datetime.datetime.combine(deadline, datetime.time(23, 59, 59))
            else:
                dt = deadline.replace(hour=23, minute=59, second=59)
            deadline = utils.date_to_timestamp(dt)
        elif isinstance(deadline, str):
            # 假设日期字符串为 'YYYYMMDD'，转为当天 23:59:59
            dt = datetime.datetime.strptime(deadline, '%Y%m%d').replace(hour=23, minute=59, second=59)
            deadline = utils.date_to_timestamp(dt)
        else:
            # 其他类型（如 -1）视为无效，使用最后一天
            deadline = -1
    else:
        deadline = -1

    # 若 deadline 为 -1，使用最后一天（转为 23:59:59）
    if deadline == -1:
        last_date = df['trade_date'].iloc[-1]
        if isinstance(last_date, (datetime.date, datetime.datetime)):
            if isinstance(last_date, datetime.date):
                dt = datetime.datetime.combine(last_date, datetime.time(23, 59, 59))
            else:
                dt = last_date.replace(hour=23, minute=59, second=59)
            deadline = utils.date_to_timestamp(dt)
        else:
            # 若为字符串，先解析
            dt = datetime.datetime.strptime(str(last_date), '%Y%m%d').replace(hour=23, minute=59, second=59)
            deadline = utils.date_to_timestamp(dt)

    # 一次性返回完整数据
    result = _handle_kline_full(df, freq, right, k, d, deci, deadline, code, market)

    return JsonResponse(result)


def get_kline_params(session):
    kline_params = utils.get_cache(session, 'kline_params', _get_kline_params_init())
    return kline_params


def set_kline_params(session, key, value):
    kline_params = utils.get_cache(session, 'kline_params', _get_kline_params_init())
    kline_params[key] = value
    utils.set_cache(session, 'kline_params', kline_params)


def _handle_kline_full(df, freq, right, k, d, deci, deadline, code, market):
    ohlc = []
    volume = []

    for _, row in df.iterrows():
        ts = utils.date_to_timestamp(row['trade_date'])
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
    ma_config = _get_kline_ma_config(freq)
    ma = _calc_simple_ma_line(df, 'close', window=ma_config['ma'], deci=deci)
    mv = _calc_simple_ma_line(df, 'vol', window=ma_config['mv'], deci=0)

    # 交易信号：买入/卖出/分红标记
    deal = _build_trade_markers(df, code, market, deci, freq)

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


def _build_trade_markers(df, code, market, deci, freq='D'):
    """
    构建K线图交易标记数据（买入/卖出/分红），支持日线/周线/月线

    参数:
        df: K线数据 DataFrame，包含 trade_date, high, low 列
        code: 股票代码
        market: 股票市场
        deci: 价格小数位数
        freq: K线周期 'D'日线 'W'周线 'M'月线

    返回:
        dict: {
            'buy':  买入标记列表 [{x, y, date, trades: [{price, qty, amount}]}],
            'sell': 卖出标记列表,
            'divd': 分红标记列表 [{x, y, date, trades: [{amount, qty, bonus_qty, date}]}]
        }

    标记位置:
        买入：K线下方（low * 0.98）
        卖出：K线上方（high * 1.02）
        分红：K线上方（high * 1.02）

    周线/月线处理：
        将交易日期映射到对应周/月的K线日期，同一根K线内的多笔交易合并显示
    """
    result = {'buy': [], 'sell': [], 'divd': []}

    if df is None or df.empty:
        return result

    # 建立K线日期到 high/low 的映射，并收集所有K线日期
    kline_dates = []
    date_hl = {}
    for _, row in df.iterrows():
        td = row['trade_date']
        if hasattr(td, 'strftime'):
            date_str = td.strftime('%Y-%m-%d')
        else:
            # 处理 'YYYYMMDD' 字符串格式，转为 'YYYY-MM-DD'
            s = str(td)[:10]
            if len(s) == 8 and s.isdigit():
                date_str = f'{s[:4]}-{s[4:6]}-{s[6:8]}'
            else:
                date_str = s
        kline_dates.append(date_str)
        date_hl[date_str] = {
            'high': float(row['high']),
            'low': float(row['low'])
        }

    # kline_dates 已按日期升序排列
    # 查询该股票的所有交易订单
    try:
        orders = TransOrder.objects.filter(code=code, market=market)
        histories = TransHistory.objects.filter(
            order__in=orders
        ).select_related('order').order_by('date', 'id')
        # 分红标记的每笔金额/送股数直接取自 TransHistory 字段
        # （dividend_amount=该笔现金、qty=该笔送股数），不再用 DividendRecord 按
        # (order_id, date) 累计，保证 tooltip 显示"每笔"而非"合计"
    except Exception as e:
        print(f'[_build_trade_markers] 查询交易历史失败: {e}')
        return result

    # 按K线日期和类型分组（周线/月线会合并同一根K线内的多笔交易）
    buy_by_kline = defaultdict(list)
    sell_by_kline = defaultdict(list)
    divd_by_kline = defaultdict(list)

    # 仅显示该周期起始日期（含）之后的交易记录：
    # K线数据按「起始日期~今天」拉取，但交易标记原为全量映射——起始日期之前
    # 的历史交易会被就近映射到第一根可见K线而错误显示。此处按该周期起始日期
    # （get_kline_start_date(freq)，对应设置中日线/周线/月线起始日期）过滤，
    # 起始日期之前的买入/卖出/分红不再上屏。结束日期不做过滤（维持现状）。
    start_date = get_kline_start_date(freq)  # 格式 'YYYYMMDD'
    start_date_dt = None
    if isinstance(start_date, str) and len(start_date) == 8 and start_date.isdigit():
        start_date_dt = datetime.datetime.strptime(start_date, '%Y%m%d').date()
    # start_date_dt 为 None（配置缺失/非法）时不过滤，保持原全量显示

    for h in histories:
        # 起始日期之前的交易记录跳过（不显示在K线上）
        if start_date_dt is not None and h.date < start_date_dt:
            continue
        trade_date = h.date.strftime('%Y-%m-%d')
        # 找到交易日期之后最近的一个K线日期（>= 交易日期）。
        # kline_dates 已按升序排列，用 bisect 二分查找（O(log K)），替代逐条线性扫描。
        idx = bisect_left(kline_dates, trade_date)
        if idx < len(kline_dates):
            kline_date = kline_dates[idx]
        elif kline_dates:
            # 交易日期晚于最后一根K线：用最后一根
            kline_date = kline_dates[-1]
        else:
            kline_date = None
        if kline_date is None or kline_date not in date_hl:
            continue
        if h.action == TransHistory.ACTION_BUY:
            buy_by_kline[kline_date].append(h)
        elif h.action == TransHistory.ACTION_SELL:
            sell_by_kline[kline_date].append(h)
        elif h.action == TransHistory.ACTION_DIVIDEND:
            divd_by_kline[kline_date].append(h)

    # 构建买入标记
    for kline_date, items in buy_by_kline.items():
        ts = utils.date_to_timestamp(kline_date.replace('-', ''))
        y = round(date_hl[kline_date]['low'] * 0.98, deci)
        trades = []
        for h in items:
            price = float(h.price)
            qty = h.qty
            amount = float(h.amount)
            trades.append({
                'price': price,
                'qty': qty,
                'amount': amount,
                'date': h.date.strftime('%Y-%m-%d')
            })
        result['buy'].append({
            'x': ts,
            'y': y,
            'date': kline_date,
            'trades': trades
        })

    # 构建卖出标记
    for kline_date, items in sell_by_kline.items():
        ts = utils.date_to_timestamp(kline_date.replace('-', ''))
        y = round(date_hl[kline_date]['high'] * 1.02, deci)
        trades = []
        for h in items:
            price = float(h.price)
            qty = h.qty
            amount = float(h.amount)
            fee = float(h.fee)
            div_tax = float(h.dividend_tax)
            trades.append({
                'price': price,
                'qty': qty,
                'amount': amount,
                'fee': fee,
                'div_tax': div_tax,
                'date': h.date.strftime('%Y-%m-%d')
            })
        sell_point = {
            'x': ts,
            'y': y,
            'date': kline_date,
            'trades': trades
        }
        # 同一天有分红时，卖出图标隐藏，由分红点的星号图标统一显示
        if kline_date in divd_by_kline:
            sell_point['dataLabels'] = {'enabled': False}
        result['sell'].append(sell_point)

    # 构建分红标记
    for kline_date, items in divd_by_kline.items():
        ts = utils.date_to_timestamp(kline_date.replace('-', ''))
        y = round(date_hl[kline_date]['high'] * 1.02, deci)
        trades = []
        # 每笔分红金额/送股数量直接取 TransHistory 字段
        # （dividend_amount=该笔现金、qty=该笔送股数），保证 tooltip 显示"每笔"而非"合计"
        for h in items:
            trade_date = h.date.strftime('%Y-%m-%d')
            amount = float(h.dividend_amount)
            bonus_qty = h.qty
            qty = h.position_qty
            trades.append({
                'amount': amount,
                'qty': qty,
                'bonus_qty': bonus_qty,
                'date': trade_date
            })
        has_sell = kline_date in sell_by_kline
        point_data = {
            'x': ts,
            'y': y,
            'date': kline_date,
            'trades': trades,
            'icon': 'tabler:hexagon-asterisk' if has_sell else 'tabler:hexagon-letter-d'
        }
        # 若同一天有卖出，隐藏分红圆点 marker，星号图标放在正常卖出位置（不叠放）
        if has_sell:
            point_data['marker'] = {'enabled': False}
        result['divd'].append(point_data)

    return result


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
        ts = utils.date_to_timestamp(trade_date)
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
        ts = utils.date_to_timestamp(trade_date)
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
