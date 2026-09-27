# -*- coding: utf-8 -*-
"""
全站参数设置页面
- 佣金、印花税、过户费、分红税
"""
import re
from decimal import Decimal
from django.shortcuts import render, redirect
from .models.models import WebSetting


def _is_valid_number(value):
    """校验是否为合法的非负数字（整数或小数）"""
    if value is None:
        return False
    value = str(value).strip()
    if value == '':
        return False
    return bool(re.match(r'^\d+(\.\d+)?$', value))


def web_setting(request):
    """全站参数设置页面：佣金、印花税、过户费、分红税"""
    if request.method == 'POST':
        # 需要校验的字段
        fields = [
            'commission_ratio', 'commission_min',
            'stamp_buy_ratio', 'stamp_sell_ratio',
            'transfer_fee_sh', 'transfer_fee_sz', 'transfer_fee_bj',
            'dividend_tax_long', 'dividend_tax_mid', 'dividend_tax_short',
        ]
        # 校验所有字段
        for field in fields:
            if not _is_valid_number(request.POST.get(field, '')):
                request.session['setting_error'] = True
                return redirect('web_setting')

        # 所有字段合法，保存
        setting = WebSetting.get_setting()
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
        setting.save()
        request.session['setting_saved'] = True
        return redirect('web_setting')

    # GET：从 session 读取标志（只显示一次）
    saved = request.session.pop('setting_saved', False)
    error = request.session.pop('setting_error', False)
    setting = WebSetting.get_setting()

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
    }
    return render(request, 'web-setting.html', context)
