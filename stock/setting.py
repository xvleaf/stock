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


def web_setting(request):
    """全站参数设置页面"""
    if request.method == 'POST':
        # 校验所有字段
        fields_num = [
            'commission_ratio', 'commission_min', 'stamp_buy_ratio', 'stamp_sell_ratio',
            'transfer_fee_sh', 'transfer_fee_sz', 'transfer_fee_bj',
            'dividend_tax_long', 'dividend_tax_mid', 'dividend_tax_short',
        ]
        fields_int = [
            'default_page_size', 'quote_interval',
            'kline_ma_day', 'kline_ma_week', 'kline_ma_month',
            'kline_mv_day', 'kline_mv_week', 'kline_mv_month',
            'kline_ema_k_day', 'kline_ema_k_week', 'kline_ema_k_month',
            'kline_ema_d_day', 'kline_ema_d_week', 'kline_ema_d_month',
        ]
        fields_date = [
            'kline_start_date_day', 'kline_start_date_week', 'kline_start_date_month',
        ]
        fields_time = [
            'trade_am_start', 'trade_am_end', 'trade_pm_start', 'trade_pm_end',
        ]

        for f in fields_num + fields_int + fields_date + fields_time:
            val = request.POST.get(f, '')
            if f in fields_num and not _is_valid_number(val):
                request.session['setting_error'] = True
                return redirect('web_setting')
            if f in fields_int and not _is_valid_integer(val):
                request.session['setting_error'] = True
                return redirect('web_setting')
            if f in fields_date and not _is_valid_date(val):
                request.session['setting_error'] = True
                return redirect('web_setting')
            if f in fields_time and not _is_valid_time(val):
                request.session['setting_error'] = True
                return redirect('web_setting')

        # 所有字段合法，保存
        setting = WebSetting.get_setting()
        # 交易费用（比率字段除以100）
        setting.commission_ratio = Decimal(request.POST['commission_ratio']) / 100
        setting.commission_min = Decimal(request.POST['commission_min'])
        setting.stamp_buy_ratio = Decimal(request.POST['stamp_buy_ratio']) / 100
        setting.stamp_sell_ratio = Decimal(request.POST['stamp_sell_ratio']) / 100
        setting.transfer_fee_sh = Decimal(request.POST['transfer_fee_sh']) / 100
        setting.transfer_fee_sz = Decimal(request.POST['transfer_fee_sz']) / 100
        setting.transfer_fee_bj = Decimal(request.POST['transfer_fee_bj']) / 100
        setting.dividend_tax_long = Decimal(request.POST['dividend_tax_long']) / 100
        setting.dividend_tax_mid = Decimal(request.POST['dividend_tax_mid']) / 100
        setting.dividend_tax_short = Decimal(request.POST['dividend_tax_short']) / 100
        # 通用设置
        setting.default_page_size = int(request.POST['default_page_size'])
        setting.quote_interval = int(request.POST['quote_interval']) * 1000  # 秒转毫秒
        setting.icp_number = request.POST.get('icp_number', '').strip()
        setting.icp_website = request.POST.get('icp_website', '').strip()
        # 交易时间（HH:MM 转秒）
        setting.trade_am_start = _hms_to_seconds(request.POST['trade_am_start'])
        setting.trade_am_end = _hms_to_seconds(request.POST['trade_am_end'])
        setting.trade_pm_start = _hms_to_seconds(request.POST['trade_pm_start'])
        setting.trade_pm_end = _hms_to_seconds(request.POST['trade_pm_end'])
        # K线起始日期
        setting.kline_start_date_day = request.POST['kline_start_date_day']
        setting.kline_start_date_week = request.POST['kline_start_date_week']
        setting.kline_start_date_month = request.POST['kline_start_date_month']
        # K线MA周期
        setting.kline_ma_day = int(request.POST['kline_ma_day'])
        setting.kline_ma_week = int(request.POST['kline_ma_week'])
        setting.kline_ma_month = int(request.POST['kline_ma_month'])
        # K线MV周期
        setting.kline_mv_day = int(request.POST['kline_mv_day'])
        setting.kline_mv_week = int(request.POST['kline_mv_week'])
        setting.kline_mv_month = int(request.POST['kline_mv_month'])
        # K线EMA-K值
        setting.kline_ema_k_day = int(request.POST['kline_ema_k_day'])
        setting.kline_ema_k_week = int(request.POST['kline_ema_k_week'])
        setting.kline_ema_k_month = int(request.POST['kline_ema_k_month'])
        # K线EMA-D值
        setting.kline_ema_d_day = int(request.POST['kline_ema_d_day'])
        setting.kline_ema_d_week = int(request.POST['kline_ema_d_week'])
        setting.kline_ema_d_month = int(request.POST['kline_ema_d_month'])
        setting.save()

        # 清除K线缓存（K线参数修改后重新获取）
        from django.core.cache import cache
        cache.clear()

        request.session['setting_saved'] = True
        return redirect('web_setting')

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
                  'kline_ema_d_day', 'kline_ema_d_week', 'kline_ema_d_month'}
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

        # K线参数修改后清除缓存
        if field.startswith('kline_'):
            from django.core.cache import cache
            cache.clear()

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
