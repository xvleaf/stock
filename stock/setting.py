# -*- coding: utf-8 -*-
"""
全站参数设置页面
- 通用设置、交易费用、交易时间、K线参数、界面配置
- 使用 WebSetting Key-Value 表存储
"""
import re
from django.shortcuts import render
from django.http import JsonResponse
from .fetch.config import get_all_config, set_config, clear_web_setting_cache


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


def _apply_setting_change(request, field):
    """根据修改的字段，处理相关缓存（WebSetting 统一缓存已在 set_config 中清除）"""
    from . import func

    # EMA/密度修改时清除 session 中的 kline_params
    KLINE_PARAM_FIELDS = {
        'kline_ema_k_day', 'kline_ema_k_week', 'kline_ema_k_month',
        'kline_ema_d_day', 'kline_ema_d_week', 'kline_ema_d_month',
        'density_max', 'density_std', 'density_min'
    }

    if field in KLINE_PARAM_FIELDS:
        func.delete_cache(request.session, 'kline_params')

    if field == 'default_page_size':
        # 清除所有列表的分页数量缓存
        for key in ('global-per-page', 'cash-per-page', 'focus-per-page', 'filter-per-page',
                    'refer-per-page', 'sector-per-page', 'trans-per-page'):
            func.delete_cache(request.session, key)


def web_setting(request):
    """全站参数设置页面（仅GET，POST由setting_save单字段AJAX处理）"""
    saved = request.session.pop('setting_saved', False)
    error = request.session.pop('setting_error', False)

    # 首次进入时初始化数据库（按默认配置字典顺序写入所有默认值）
    from .models.models import WebSetting, WEB_SETTING_DEFAULTS
    if WebSetting.objects.count() == 0:
        for key, meta in WEB_SETTING_DEFAULTS.items():
            WebSetting.objects.create(
                key=key,
                value=meta['value'],
                value_type=meta['type'],
                group_name=meta['group'],
                label=meta['label'],
                remark=meta.get('remark', ''),
                sort_order=meta['sort'],
            )
        clear_web_setting_cache()

    cfg = get_all_config()

    # 比率字段乘以100，以百分比形式显示；值为0时显示整数
    def _fmt_pct(val):
        v = float(val) * 100
        return int(v) if v == 0 else v

    def _fmt_num(val):
        v = float(val)
        return int(v) if v == 0 else v

    # 构建 setting 字典，模板中用 {{ setting.xxx }} 访问
    setting = dict(cfg)
    # 行情刷新间隔：毫秒转秒显示
    setting['quote_interval'] = int(cfg.get('quote_interval', 60000)) // 1000

    # 构建 remarks 字典，用于输入框 placeholder
    remarks = {}
    try:
        for item in WebSetting.objects.all():
            remarks[item.key] = item.remark or ''
    except Exception:
        pass

    context = {
        'setting': setting,
        'remarks': remarks,
        'saved': saved,
        'error': error,
        # 交易费用（百分比形式）
        'commission_ratio_pct': _fmt_pct(cfg.get('commission_ratio', 0)),
        'commission_min_fmt': _fmt_num(cfg.get('commission_min', 0)),
        'stamp_buy_ratio_pct': _fmt_pct(cfg.get('stamp_buy_ratio', 0)),
        'stamp_sell_ratio_pct': _fmt_pct(cfg.get('stamp_sell_ratio', 0)),
        'transfer_fee_sh_pct': _fmt_pct(cfg.get('transfer_fee_sh', 0)),
        'transfer_fee_sz_pct': _fmt_pct(cfg.get('transfer_fee_sz', 0)),
        'transfer_fee_bj_pct': _fmt_pct(cfg.get('transfer_fee_bj', 0)),
        'dividend_tax_long_pct': _fmt_pct(cfg.get('dividend_tax_long', 0)),
        'dividend_tax_mid_pct': _fmt_pct(cfg.get('dividend_tax_mid', 0)),
        'dividend_tax_short_pct': _fmt_pct(cfg.get('dividend_tax_short', 0)),
        # 交易时间（秒转 HH:MM）
        'trade_am_start_fmt': _seconds_to_hms(cfg.get('trade_am_start', 34200)),
        'trade_am_end_fmt': _seconds_to_hms(cfg.get('trade_am_end', 41400)),
        'trade_pm_start_fmt': _seconds_to_hms(cfg.get('trade_pm_start', 46800)),
        'trade_pm_end_fmt': _seconds_to_hms(cfg.get('trade_pm_end', 54000)),
    }
    return render(request, 'web-setting.html', context)


def setting_save(request):
    """AJAX单字段保存接口"""
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
    FLOAT_FIELDS = {'commission_min'}
    TIME_FIELDS = {'trade_am_start', 'trade_am_end', 'trade_pm_start', 'trade_pm_end'}
    INT_FIELDS = {'default_page_size', 'quote_interval',
                  'kline_ma_day', 'kline_ma_week', 'kline_ma_month',
                  'kline_mv_day', 'kline_mv_week', 'kline_mv_month',
                  'kline_ema_k_day', 'kline_ema_k_week', 'kline_ema_k_month',
                  'kline_ema_d_day', 'kline_ema_d_week', 'kline_ema_d_month',
                  'density_max', 'density_std', 'density_min',
                  'nav_locked_screen_height', 'nav_height', 'nav_height_mobile',
                  'gap_height', 'navi_bar_height',
                  'mobile_breakpoint', 'bp1', 'bp2', 'bp3',
                  'w1', 'w2', 'w3', 'w4', 'w5', 'w6', 'w7', 'w8',
                  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8',
                  'cash_chart_height', 'trend_main_ratio', 'kline_main_ratio'}
    BOOL_FIELDS = {'stock_chart_visible'}
    TEXT_FIELDS = {'icp_number', 'icp_website',
                   'kline_start_date_day', 'kline_start_date_week', 'kline_start_date_month',
                   'chart_vertical_align_fullscreen'}

    try:
        if field in PCT_FIELDS:
            # 百分比转小数
            if not _is_valid_number(value):
                return JsonResponse({'success': False, 'error': '请输入有效数字'})
            save_value = str(float(value) / 100)
        elif field in FLOAT_FIELDS:
            # 金额类数字（如最低佣金）
            if not _is_valid_number(value):
                return JsonResponse({'success': False, 'error': '请输入有效数字'})
            save_value = value
        elif field in TIME_FIELDS:
            # HH:MM 转秒
            if not re.match(r'^\d{2}:\d{2}$', value):
                return JsonResponse({'success': False, 'error': '请输入HH:MM格式'})
            save_value = str(_hms_to_seconds(value))
        elif field == 'quote_interval':
            # 秒转毫秒
            if not value.isdigit():
                return JsonResponse({'success': False, 'error': '请输入整数'})
            save_value = str(int(value) * 1000)
        elif field in INT_FIELDS:
            if field == 'nav_locked_screen_height':
                # 允许 -1（锁定导航栏）或正整数（高度阈值）
                if value != '-1' and not value.isdigit():
                    return JsonResponse({'success': False, 'error': '请输入整数或-1'})
            else:
                if not value.isdigit():
                    return JsonResponse({'success': False, 'error': '请输入整数'})
            save_value = value
        elif field in BOOL_FIELDS:
            save_value = 'true' if value.lower() in ('true', '1', '是') else 'false'
        elif field in TEXT_FIELDS:
            save_value = value
        else:
            return JsonResponse({'success': False, 'error': f'未知字段: {field}'})

        # 保存到 WebSetting（upsert），内部会清除统一缓存
        set_config(field, save_value)

        # 处理 session 级缓存
        _apply_setting_change(request, field)

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


def ui_config(request):
    """模板上下文处理器：注入界面配置到所有页面"""
    from .fetch.config import get_ui_config
    return {'ui_config': get_ui_config()}
