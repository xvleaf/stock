# -*- coding: utf-8 -*-
"""
fetch 模块统一配置获取
从 WebSetting Key-Value 表读取交易时间、K线参数、行情刷新间隔、界面配置等
所有读取均带模块级永久缓存，修改时主动清除
"""

# 全站配置模块级缓存（永久缓存，修改时主动清除）
_web_setting_cache = None


def _convert_value(value, value_type):
    """将字符串值按类型转换"""
    if value is None:
        return None
    if value_type == 'int':
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if value_type == 'float':
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    if value_type == 'bool':
        return str(value).lower() in ('true', '1', 'yes')
    return str(value)


def get_all_config():
    """一次性读取所有配置，转为 {key: value} 字典，带模块级永久缓存"""
    global _web_setting_cache
    if _web_setting_cache is not None:
        return _web_setting_cache

    from ..models.models import WebSetting, WEB_SETTING_DEFAULTS
    result = {}

    # 从数据库读取
    try:
        for item in WebSetting.objects.all():
            result[item.key] = _convert_value(item.value, item.value_type)
    except Exception:
        pass

    # 补全默认值（数据库中不存在的键）
    for key, meta in WEB_SETTING_DEFAULTS.items():
        if key not in result:
            result[key] = _convert_value(meta['value'], meta['type'])

    _web_setting_cache = result
    return result


def get_config(key, default=None):
    """获取单个配置值"""
    return get_all_config().get(key, default)


def set_config(key, value):
    """保存单个配置（upsert），并清除缓存"""
    from ..models.models import WebSetting, WEB_SETTING_DEFAULTS
    meta = WEB_SETTING_DEFAULTS.get(key, {})
    value_type = meta.get('type', 'string')
    group_name = meta.get('group', 'general')
    label = meta.get('label', key)
    sort_order = meta.get('sort', 0)

    WebSetting.objects.update_or_create(
        key=key,
        defaults={
            'value': str(value),
            'value_type': value_type,
            'group_name': group_name,
            'label': label,
            'sort_order': sort_order,
        }
    )
    clear_web_setting_cache()


def clear_web_setting_cache():
    """清除全站配置缓存"""
    global _web_setting_cache
    _web_setting_cache = None


# ===================== 各分组配置获取函数（接口不变，内部改用 get_config） =====================

def get_trade_times():
    """获取交易时间段（秒，从零点开始）"""
    cfg = get_all_config()
    return {
        'am_start': cfg.get('trade_am_start', 34200),
        'am_end': cfg.get('trade_am_end', 41400),
        'pm_start': cfg.get('trade_pm_start', 46800),
        'pm_end': cfg.get('trade_pm_end', 54000),
    }


def clear_trade_times_cache():
    """清除交易时间缓存（已合并到统一缓存，保留接口兼容）"""
    clear_web_setting_cache()


def get_quote_interval():
    """获取行情刷新间隔（毫秒）"""
    return get_config('quote_interval', 60000)


def clear_quote_interval_cache():
    """清除行情刷新间隔缓存（已合并到统一缓存，保留接口兼容）"""
    clear_web_setting_cache()


def get_kline_start_date(freq='D'):
    """获取K线起始日期"""
    cfg = get_all_config()
    if freq == 'W':
        return cfg.get('kline_start_date_week', '19801020')
    if freq == 'M':
        return cfg.get('kline_start_date_month', '19801020')
    return cfg.get('kline_start_date_day', '19801020')


def get_kline_ma_period(freq='D'):
    """获取MA周期"""
    cfg = get_all_config()
    if freq == 'W':
        return cfg.get('kline_ma_week', 60)
    if freq == 'M':
        return cfg.get('kline_ma_month', 30)
    return cfg.get('kline_ma_day', 200)


def get_kline_mv_period(freq='D'):
    """获取MV周期"""
    cfg = get_all_config()
    if freq == 'W':
        return cfg.get('kline_mv_week', 30)
    if freq == 'M':
        return cfg.get('kline_mv_month', 30)
    return cfg.get('kline_mv_day', 60)


def clear_kline_param_cache():
    """清除MA/MV/起始日期缓存（已合并到统一缓存，保留接口兼容）"""
    clear_web_setting_cache()


def get_kline_ema_k(freq='D'):
    """获取EMA-K值"""
    cfg = get_all_config()
    if freq == 'W':
        return cfg.get('kline_ema_k_week', 20)
    if freq == 'M':
        return cfg.get('kline_ema_k_month', 20)
    return cfg.get('kline_ema_k_day', 10)


def get_kline_ema_d(freq='D'):
    """获取EMA-D值"""
    cfg = get_all_config()
    if freq == 'W':
        return cfg.get('kline_ema_d_week', 30)
    if freq == 'M':
        return cfg.get('kline_ema_d_month', 30)
    return cfg.get('kline_ema_d_day', 30)


def get_kline_density():
    """获取K线密度配置"""
    cfg = get_all_config()
    return {
        'max': cfg.get('density_max', 20),
        'std': cfg.get('density_std', 13),
        'min': cfg.get('density_min', 5),
    }


def clear_kline_density_ema_cache():
    """清除密度和EMA缓存（已合并到统一缓存，保留接口兼容）"""
    clear_web_setting_cache()


def get_ui_config():
    """获取界面配置（导航栏/内容布局/图表布局）"""
    cfg = get_all_config()
    return {
        # 导航栏
        'nav_locked': cfg.get('nav_locked', False),
        'screen_height_threshold': cfg.get('screen_height_threshold', 800),
        'nav_height': cfg.get('nav_height', 50),
        'nav_height_mobile': cfg.get('nav_height_mobile', 40),
        'gap_height': cfg.get('gap_height', 2),
        'navi_bar_height': cfg.get('navi_bar_height', 25),
        # 内容布局
        'mobile_breakpoint': cfg.get('mobile_breakpoint', 992),
        'mobile_breakpoint_plus_1': cfg.get('mobile_breakpoint', 992) + 1,
        'w1': cfg.get('w1', 100),
        'bp1': cfg.get('bp1', 1200),
        'w2': cfg.get('w2', 85),
        'bp2': cfg.get('bp2', 1440),
        'w3': cfg.get('w3', 70),
        'bp3': cfg.get('bp3', 1920),
        'w4': cfg.get('w4', 60),
        # 图表布局
        'h1': cfg.get('h1', 100),
        'h2': cfg.get('h2', 90),
        'h3': cfg.get('h3', 80),
        'h4': cfg.get('h4', 75),
        'cash_chart_height': cfg.get('cash_chart_height', 400),
        'chart_placeholder_height': cfg.get('chart_placeholder_height', 400),
        'trend_main_ratio': cfg.get('trend_main_ratio', 75),
        'kline_main_ratio': cfg.get('kline_main_ratio', 80),
    }


def clear_ui_config_cache():
    """清除界面配置缓存（已合并到统一缓存，保留接口兼容）"""
    clear_web_setting_cache()
