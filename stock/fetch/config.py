# -*- coding: utf-8 -*-
"""
fetch 模块统一配置获取
从 WebSetting 数据库读取交易时间、K线参数、行情刷新间隔等
"""

# 交易时间模块级缓存（永久缓存，修改时主动清除）
_trade_times_cache = None

# MA/MV/起始日期 模块级缓存（永久缓存，修改时主动清除）
_kline_ma_cache = {}
_kline_mv_cache = {}
_kline_start_date_cache = {}


def get_trade_times():
    """获取交易时间段（秒，从零点开始），带模块级缓存"""
    global _trade_times_cache

    if _trade_times_cache:
        return _trade_times_cache

    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        result = {
            'am_start': int(s.trade_am_start),
            'am_end': int(s.trade_am_end),
            'pm_start': int(s.trade_pm_start),
            'pm_end': int(s.trade_pm_end),
        }
    except Exception:
        result = {
            'am_start': 34200,   # 09:30
            'am_end': 41400,     # 11:30
            'pm_start': 46800,   # 13:00
            'pm_end': 54000,     # 15:00
        }

    _trade_times_cache = result
    return result


def clear_trade_times_cache():
    """清除交易时间缓存"""
    global _trade_times_cache
    _trade_times_cache = None


def get_quote_interval():
    """获取行情刷新间隔（毫秒）"""
    try:
        from ..models.models import WebSetting
        return int(WebSetting.get_setting().quote_interval)
    except Exception:
        return 60000


def get_kline_start_date(freq='D'):
    """获取K线起始日期，带模块级缓存"""
    global _kline_start_date_cache

    if freq in _kline_start_date_cache:
        return _kline_start_date_cache[freq]

    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            result = s.kline_start_date_week
        elif freq == 'M':
            result = s.kline_start_date_month
        else:
            result = s.kline_start_date_day
    except Exception:
        result = '19801020'

    _kline_start_date_cache[freq] = result
    return result


def get_kline_ma_period(freq='D'):
    """获取MA周期，带模块级缓存"""
    global _kline_ma_cache

    if freq in _kline_ma_cache:
        return _kline_ma_cache[freq]

    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            result = int(s.kline_ma_week)
        elif freq == 'M':
            result = int(s.kline_ma_month)
        else:
            result = int(s.kline_ma_day)
    except Exception:
        result = {'D': 200, 'W': 60, 'M': 30}.get(freq, 200)

    _kline_ma_cache[freq] = result
    return result


def get_kline_mv_period(freq='D'):
    """获取MV周期，带模块级缓存"""
    global _kline_mv_cache

    if freq in _kline_mv_cache:
        return _kline_mv_cache[freq]

    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        if freq == 'W':
            result = int(s.kline_mv_week)
        elif freq == 'M':
            result = int(s.kline_mv_month)
        else:
            result = int(s.kline_mv_day)
    except Exception:
        result = {'D': 60, 'W': 30, 'M': 30}.get(freq, 60)

    _kline_mv_cache[freq] = result
    return result


def clear_kline_param_cache():
    """清除MA/MV/起始日期缓存"""
    global _kline_ma_cache, _kline_mv_cache, _kline_start_date_cache
    _kline_ma_cache = {}
    _kline_mv_cache = {}
    _kline_start_date_cache = {}


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


def get_kline_density():
    """获取K线密度配置"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        return {
            'max': int(s.density_max),
            'std': int(s.density_std),
            'min': int(s.density_min),
        }
    except Exception:
        return {'max': 20, 'std': 13, 'min': 5}
