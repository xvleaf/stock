# -*- coding: utf-8 -*-
"""
fetch 模块统一配置获取
从 WebSetting 数据库读取交易时间、K线参数、行情刷新间隔等
"""

# 交易时间模块级缓存（永久缓存，修改时主动清除）
_trade_times_cache = None

# 行情刷新间隔模块级缓存（永久缓存，修改时主动清除）
_quote_interval_cache = None

# MA/MV/起始日期 模块级缓存（永久缓存，修改时主动清除）
_kline_ma_cache = {}
_kline_mv_cache = {}
_kline_start_date_cache = {}

# 密度/EMA 模块级缓存（永久缓存，修改时主动清除）
_kline_density_ema_cache = None


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
    """获取行情刷新间隔（毫秒），带模块级缓存"""
    global _quote_interval_cache

    if _quote_interval_cache is not None:
        return _quote_interval_cache

    try:
        from ..models.models import WebSetting
        result = int(WebSetting.get_setting().quote_interval)
    except Exception:
        result = 60000

    _quote_interval_cache = result
    return result


def clear_quote_interval_cache():
    """清除行情刷新间隔缓存"""
    global _quote_interval_cache
    _quote_interval_cache = None


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


def _load_kline_density_ema():
    """从数据库读取密度和EMA配置"""
    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        return {
            'density': {
                'max': int(s.density_max),
                'std': int(s.density_std),
                'min': int(s.density_min),
            },
            'ema_k': {
                'D': int(s.kline_ema_k_day),
                'W': int(s.kline_ema_k_week),
                'M': int(s.kline_ema_k_month),
            },
            'ema_d': {
                'D': int(s.kline_ema_d_day),
                'W': int(s.kline_ema_d_week),
                'M': int(s.kline_ema_d_month),
            },
        }
    except Exception:
        return {
            'density': {'max': 20, 'std': 13, 'min': 5},
            'ema_k': {'D': 10, 'W': 20, 'M': 20},
            'ema_d': {'D': 30, 'W': 30, 'M': 30},
        }


def _get_kline_density_ema():
    """获取密度和EMA配置（带模块级缓存）"""
    global _kline_density_ema_cache
    if _kline_density_ema_cache is not None:
        return _kline_density_ema_cache
    _kline_density_ema_cache = _load_kline_density_ema()
    return _kline_density_ema_cache


def clear_kline_density_ema_cache():
    """清除密度和EMA缓存"""
    global _kline_density_ema_cache
    _kline_density_ema_cache = None


def get_kline_ema_k(freq='D'):
    """获取EMA-K值（带模块级缓存）"""
    return _get_kline_density_ema()['ema_k'].get(freq, 10)


def get_kline_ema_d(freq='D'):
    """获取EMA-D值（带模块级缓存）"""
    return _get_kline_density_ema()['ema_d'].get(freq, 30)


def get_kline_density():
    """获取K线密度配置（带模块级缓存）"""
    return _get_kline_density_ema()['density']


# 界面配置模块级缓存（永久缓存，修改时主动清除）
_ui_config_cache = None


def get_ui_config():
    """获取界面配置（导航栏/内容布局/图表布局），带模块级缓存"""
    global _ui_config_cache

    if _ui_config_cache:
        return _ui_config_cache

    try:
        from ..models.models import WebSetting
        s = WebSetting.get_setting()
        result = {
            # 导航栏
            'nav_locked': bool(s.nav_locked),
            'screen_height_threshold': int(s.screen_height_threshold),
            'nav_height': int(s.nav_height),
            'nav_height_mobile': int(s.nav_height_mobile),
            'gap_height': int(s.gap_height),
            'navi_bar_height': int(s.navi_bar_height),
            # 内容布局
            'mobile_breakpoint': int(s.mobile_breakpoint),
            'mobile_breakpoint_plus_1': int(s.mobile_breakpoint) + 1,
            'w1': int(s.w1),
            'bp1': int(s.bp1),
            'w2': int(s.w2),
            'bp2': int(s.bp2),
            'w3': int(s.w3),
            'bp3': int(s.bp3),
            'w4': int(s.w4),
            # 图表布局
            'h1': int(s.h1),
            'h2': int(s.h2),
            'h3': int(s.h3),
            'h4': int(s.h4),
            'cash_chart_height': int(s.cash_chart_height),
            'chart_placeholder_height': int(s.chart_placeholder_height),
            'trend_main_ratio': int(s.trend_main_ratio),
            'kline_main_ratio': int(s.kline_main_ratio),
        }
    except Exception:
        result = {
            'nav_locked': False,
            'screen_height_threshold': 800,
            'nav_height': 50,
            'nav_height_mobile': 40,
            'gap_height': 2,
            'navi_bar_height': 25,
            'mobile_breakpoint': 992,
            'mobile_breakpoint_plus_1': 993,
            'w1': 100, 'bp1': 1200, 'w2': 85, 'bp2': 1440,
            'w3': 70, 'bp3': 1920, 'w4': 60,
            'h1': 100, 'h2': 90, 'h3': 80, 'h4': 75,
            'cash_chart_height': 400,
            'chart_placeholder_height': 400,
            'trend_main_ratio': 75,
            'kline_main_ratio': 80,
        }

    _ui_config_cache = result
    return result


def clear_ui_config_cache():
    """清除界面配置缓存"""
    global _ui_config_cache
    _ui_config_cache = None
