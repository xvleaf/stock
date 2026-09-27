# -*- coding: utf-8 -*-
"""
全站参数设置页面
- 通用设置、交易费用、交易时间、K线参数
"""
import re
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect
from .models.models import WebSetting


def _seconds_to_hms(seconds):
    """秒转 HH:MM 格式"""
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f'{h:02d}:{m:02d}'


def _hms_to_seconds(hms):
    """HH:MM 格式转秒"""
    try:
        h, m = hms.split(':')
        return int(h) * 3600 + int(m) * 60
    except (ValueError, AttributeError):
        return 0


def _is_valid_number(value):
    """校验是否为合法的非负数字（整数或小数）"""
    if value is None:
        return False
    value = str(value).strip()
    if value == '':
        return False
    return bool(re.match(r'^\d+(\.\d+)?$', value))


def _is_valid_integer(value):
    """校验是否为合法的非负整数"""
    if value is None:
        return False
    value = str(value).strip()
    return bool(re.match(r'^\d+$', value))


def _is_valid_date(value):
    """校验是否为合法的日期（YYYYMMDD）"""
    if value is None:
        return False
    value = str(value).strip()
    return bool(re.match(r'^\d{8}$', value))


def _is_valid_time(value):
    """校验是否为合法的时间（HH:MM）"""
    if value is None:
        return False
    value = str(value).strip()
    return bool(re.match(r'^\d{2}:\d{2}$', value))


def _apply_setting_change(request, field):
    """根据修改的字段，精确处理相关缓存"""
    from . import func

    # 需要清除 kline_params 的字段（EMA参数、密度）
    KLINE_PARAM_FIELDS = {
        'kline_ema_k_day', 'kline_ema_k_week', 'kline_ema_k_month',
        'kline_ema_d_day', 'kline_ema_d_week', 'kline_ema_d_month',
        'density_max', 'density_std', 'density_min'
    }

    # 交易时间字段
    TRADE_TIME_FIELDS = {'trade_am_start', 'trade_am_end', 'trade_pm_start', 'trade_pm_end'}

    if field in KLINE_PARAM_FIELDS:
        # 只清除 kline_params，不清除 kline-deadline
        func.set_cache(request.session, 'kline_params', None)

    if field in TRADE_TIME_FIELDS:
        # 清除交易时间模块缓存
        from .fetch.config import clear_trade_times_cache
        clear_trade_times_cache()

    if field == 'default_page_size':
        # 清除所有列表的分页数量缓存
        for key in ('cash-per-page', 'focus-per-page', 'filter-per-page',
                    'refer-per-page', 'sector-per-page', 'trans-per-page'):
            func.set_cache(request.session, key, None)


def web_setting(request):
    """全站参数设置页面（仅GET，POST由setting_save单字段AJAX处理）"""
    # GET：从 session 读取标志（只显示一次）
    saved = request.session.pop('setting_saved', False)
    error = request.session.pop('setting_error', False)
    setting = WebSetting.get_setting()

    # 行情刷新间隔：毫秒转秒显示（数据库存毫秒，页面显示秒）
    setting.quote_interval = int(setting.quote_interval) // 1000

    # 比率字段乘以100，以百分比形式显示；值为0时显示整数
    def _fmt_pct(val):
        v = float(val) * 100
        return int(v) if v == 0 else v
    # 数值字段：值为0时显示整数0
    def _fmt_num(val):
        v = float(val)
        return int(v) if v == 0 else v

    context = {
        'setting': setting,
        'saved': saved,
        'error': error,
        # 交易费用
        'commission_ratio_pct': _fmt_pct(setting.commission_ratio),
        'commission_min_fmt': _fmt_num(setting.commission_min),
        'stamp_buy_ratio_pct': _fmt_pct(setting.stamp_buy_ratio),
        'stamp_sell_ratio_pct': _fmt_pct(setting.stamp_sell_ratio),
        'transfer_fee_sh_pct': _fmt_pct(setting.transfer_fee_sh),
        'transfer_fee_sz_pct': _fmt_pct(setting.transfer_fee_sz),
        'transfer_fee_bj_pct': _fmt_pct(setting.transfer_fee_bj),
        'dividend_tax_long_pct': _fmt_pct(setting.dividend_tax_long),
        'dividend_tax_mid_pct': _fmt_pct(setting.dividend_tax_mid),
        'dividend_tax_short_pct': _fmt_pct(setting.dividend_tax_short),
        # 交易时间（秒转 HH:MM）
        'trade_am_start_fmt': _seconds_to_hms(setting.trade_am_start),
        'trade_am_end_fmt': _seconds_to_hms(setting.trade_am_end),
        'trade_pm_start_fmt': _seconds_to_hms(setting.trade_pm_start),
        'trade_pm_end_fmt': _seconds_to_hms(setting.trade_pm_end),
    }
    return render(request, 'web-setting.html', context)


def setting_save(request):
    """AJAX单字段保存接口"""
    from django.http import JsonResponse
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': '方法不允许'}, status=405)

    field = request.POST.get('field', '').strip()
    value = request.POST.get('value', '').strip()

    if not field:
        return JsonResponse({'success': False, 'error': '字段名不能为空'})

    # 字段类型映射
    PCT_FIELDS = {'commission_ratio', 'stamp_buy_ratio', 'stamp_sell_ratio',
                  'transfer_fee_sh', 'transfer_fee_sz', 'transfer_fee_bj',
                  'dividend_tax_long', 'dividend_tax_mid', 'dividend_tax_short'}
    TIME_FIELDS = {'trade_am_start', 'trade_am_end', 'trade_pm_start', 'trade_pm_end'}
    INT_FIELDS = {'default_page_size', 'quote_interval',
                  'kline_ma_day', 'kline_ma_week', 'kline_ma_month',
                  'kline_mv_day', 'kline_mv_week', 'kline_mv_month',
                  'kline_ema_k_day', 'kline_ema_k_week', 'kline_ema_k_month',
                  'kline_ema_d_day', 'kline_ema_d_week', 'kline_ema_d_month',
                  'density_max', 'density_std', 'density_min'}
    TEXT_FIELDS = {'icp_number', 'icp_website',
                   'kline_start_date_day', 'kline_start_date_week', 'kline_start_date_month'}

    try:
        setting = WebSetting.get_setting()

        if field in PCT_FIELDS:
            # 百分比转小数
            if not _is_valid_number(value):
                return JsonResponse({'success': False, 'error': '请输入有效数字'})
            setattr(setting, field, Decimal(value) / 100)
        elif field in TIME_FIELDS:
            # HH:MM 转秒
            if not re.match(r'^\d{2}:\d{2}$', value):
                return JsonResponse({'success': False, 'error': '请输入HH:MM格式'})
            setattr(setting, field, _hms_to_seconds(value))
        elif field == 'quote_interval':
            # 秒转毫秒
            if not value.isdigit():
                return JsonResponse({'success': False, 'error': '请输入整数'})
            setting.quote_interval = int(value) * 1000
        elif field in INT_FIELDS:
            if not value.isdigit():
                return JsonResponse({'success': False, 'error': '请输入整数'})
            setattr(setting, field, int(value))
        elif field in TEXT_FIELDS:
            setattr(setting, field, value)
        else:
            return JsonResponse({'success': False, 'error': f'未知字段: {field}'})

        setting.save()

        # 精确处理相关缓存
        _apply_setting_change(request, field)

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
