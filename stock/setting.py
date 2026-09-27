# -*- coding: utf-8 -*-
"""
全站参数设置页面
- 佣金、印花税、过户费、分红税
"""
from decimal import Decimal
from django.shortcuts import render, redirect
from .models.models import WebSetting


def web_setting(request):
    """全站参数设置页面：佣金、印花税、过户费、分红税"""
    if request.method == 'POST':
        setting = WebSetting.get_setting()
        # 比率字段：前端显示百分比，保存时除以100
        setting.commission_ratio = Decimal(request.POST.get('commission_ratio', '0')) / 100
        setting.commission_min = Decimal(request.POST.get('commission_min', '0'))
        setting.stamp_buy_ratio = Decimal(request.POST.get('stamp_buy_ratio', '0')) / 100
        setting.stamp_sell_ratio = Decimal(request.POST.get('stamp_sell_ratio', '0')) / 100
        setting.transfer_fee_sh = Decimal(request.POST.get('transfer_fee_sh', '0')) / 100
        setting.transfer_fee_sz = Decimal(request.POST.get('transfer_fee_sz', '0')) / 100
        setting.transfer_fee_bj = Decimal(request.POST.get('transfer_fee_bj', '0')) / 100
        setting.dividend_tax_long = Decimal(request.POST.get('dividend_tax_long', '0')) / 100
        setting.dividend_tax_mid = Decimal(request.POST.get('dividend_tax_mid', '0')) / 100
        setting.dividend_tax_short = Decimal(request.POST.get('dividend_tax_short', '0')) / 100
        setting.save()
        request.session['setting_saved'] = True
        return redirect('web_setting')

    # GET：从 session 读取保存成功标志（只显示一次）
    saved = request.session.pop('setting_saved', False)
    setting = WebSetting.get_setting()

    # 比率字段乘以100，以百分比形式显示；值为0时显示整数
    def _fmt_pct(val):
        v = float(val) * 100
        return int(v) if v == 0 else v
    context = {
        'setting': setting,
        'saved': saved,
        'commission_ratio_pct': _fmt_pct(setting.commission_ratio),
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
