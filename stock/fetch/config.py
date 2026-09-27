# -*- coding: utf-8 -*-
"""
fetch 模块统一配置获取
从 WebSetting 数据库读取交易时间、K线参数、行情刷新间隔等
"""


def get_trade_times():
    """获取交易时间段（秒，从零点开始）"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        return {
            'am_start': int(s.trade_am_start),
            'am_end': int(s.trade_am_end),
            'pm_start': int(s.trade_pm_start),
            'pm_end': int(s.trade_pm_end),
        }
    except Exception:
        return {
            'am_start': 34200,   # 09:30
            'am_end': 41400,     # 11:30
            'pm_start': 46800,   # 13:00
            'pm_end': 54000,     # 15:00
        }


def get_quote_interval():
    """获取行情刷新间隔（毫秒）"""
    try:
        from ..models.models import WebSetting
        return int(WebSetting.get_setting().quote_interval)
    except Exception:
        return 60000


def get_kline_start_date(freq='D'):
    """获取K线起始日期"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            return s.kline_start_date_week
        elif freq == 'M':
            return s.kline_start_date_month
        return s.kline_start_date_day
    except Exception:
        return '19801020'


def get_kline_ma_period(freq='D'):
    """获取MA周期"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            return int(s.kline_ma_week)
        elif freq == 'M':
            return int(s.kline_ma_month)
        return int(s.kline_ma_day)
    except Exception:
        return {'D': 200, 'W': 60, 'M': 30}.get(freq, 200)


def get_kline_mv_period(freq='D'):
    """获取MV周期"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            return int(s.kline_mv_week)
        elif freq == 'M':
            return int(s.kline_mv_month)
        return int(s.kline_mv_day)
    except Exception:
        return {'D': 60, 'W': 30, 'M': 30}.get(freq, 60)


def get_kline_ema_k(freq='D'):
    """获取EMA-K值"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            return int(s.kline_ema_k_week)
        elif freq == 'M':
            return int(s.kline_ema_k_month)
        return int(s.kline_ema_k_day)
    except Exception:
        return {'D': 10, 'W': 20, 'M': 20}.get(freq, 10)


def get_kline_ema_d(freq='D'):
    """获取EMA-D值"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            return int(s.kline_ema_d_week)
        elif freq == 'M':
            return int(s.kline_ema_d_month)
        return int(s.kline_ema_d_day)
    except Exception:
        return {'D': 30, 'W': 30, 'M': 30}.get(freq, 30)
