import os
import json
import datetime
from decimal import Decimal
import pandas as pd
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from .fetch import quote, tushare, kline, trend
from .forms.forms import FocusStockForm
from . import cash, func, chart
from .models.models import CashConfig, StockList, FocusStock
from django.db import connection, transaction


# ===================== 关注清单 =====================
def focus_list(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        if data.get('action') == 'sort':
            ordered_codes = data.get('codes', [])
            for i, c in enumerate(ordered_codes):
                # 排序从 1 开始
                FocusStock.objects.filter(code=c[0], market=c[1]).update(sort_order=i+1)
            return JsonResponse({'msg': 'done'})

        result = []
        focus_qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING)
        for fs in focus_qs:
            deci = 2 if fs.cat == 'stock' else 3
            close, change = quote.get_last_price(fs.tscode, deci)  
            result.append({
                'code': fs.code,
                'market': fs.market,
                'close': close, 
                'change': change,
                'deci': deci
            })
            
        return JsonResponse(result, safe=False, json_dumps_params={'ensure_ascii': False})
    
    items = []
    # models 自带 sort_order 排序，因此不需要进行排序
    focus_qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING)
    for fs in focus_qs:
        deci = 2 if fs.cat == 'stock' else 3
        items.append({
            'code': fs.code,
            'market': fs.market,
            'name': fs.name,
            'plan_price': round(fs.plan_price, deci),
            'win_ratio': round(fs.win_ratio, 0),
            'close': '--',
            'change': '--',
            'deci': deci
        })
    return render(request, 'focus-list.html', {
        'list': items,
        'interval': trend.QUOTE_REQUEST_INTERVAL
    })


def focus_plus(request):
    code, name, market, cat = None, None, None, 'stock'

    if request.method == 'POST':
        form = FocusStockForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data.get('code')
            name = form.cleaned_data.get('name')
            market = form.cleaned_data.get('market_choice', 'SH')
            cat = form.cleaned_data.get('cat_choice', 'stock')
            # 检查是否已存在正在关注的记录
            if FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).exists():   
                form.add_error(None, '该股票关注中，不能重复添加')
            else:
                focus = form.save(commit=False)
                focus.code = code
                focus.market = market
                focus.win_ratio = _calc_win_ratio(focus.plan_price, focus.target_price, focus.stop_price)
                focus.allowed_qty = cash.calc_allowed_qty(focus.plan_price)
                max_sort = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).count()
                focus.sort_order = max_sort
                focus.save()
                focus.save_history(action='create')
                return redirect('focus_view', market=focus.market, code=focus.code)
    else:
        initial = {}
        form = FocusStockForm(initial=initial)
    
    chart_init = {
        'site': 'focus/plus',
        'code': code,
        'market': market,
        'name': name,
        'cat': cat
    }

    page_config = chart.get_page_config(request.session, 'focus/plus', cat)
    chart_init.update(page_config)

    return render(request, 'focus-plus.html', {
        'form': form, 
        'available': CashConfig.get_config().available,  
        # 需转换为 JSON 字符串
        'chart': json.dumps(chart_init)   
    })


def focus_view(request, market, code):
    focus = get_object_or_404(FocusStock, code=code, market=market, status=FocusStock.STATUS_WATCHING)

    if request.method == 'POST':
        form = FocusStockForm(request.POST, instance=focus, view_mode=True)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.win_ratio = _calc_win_ratio(updated.plan_price, updated.target_price, updated.stop_price)
            updated.allowed_qty = cash.calc_allowed_qty(updated.plan_price)
            updated.save()
            updated.save_history(action='edit')
            return redirect('focus_view', market=market, code=code)
    else:
        form = FocusStockForm(instance=focus, view_mode=True)

    navi_list = chart.get_navi_list('focus/view')
    
    if navi_list:
        code, market = chart.set_navi_params(
            request.session, 
            'focus/view', 
            code, 
            market, 
            navi_list, 
            0
        )
        
    # 图表配置
    chart_init = {
        'site': 'focus/view',
        'code': code,
        'market': market,
        'name': focus.name,
        'cat': focus.cat
    }
    
    page_config = chart.get_page_config(request.session, 'focus/view', focus.cat)
    chart_init.update(page_config)

    return render(request, 'focus-view.html', {
        'form': form,
        'chart': json.dumps(chart_init),
        'edit_mode': False,
        'available': CashConfig.get_config().available
    })


def _calc_win_ratio(buy_price, target_price, stop_price):
    """计算成功几率（0-99整数）"""
    try:
        buy = float(buy_price or 0)
        target = float(target_price or 0)
        stop = float(stop_price or 0)
    except (TypeError, ValueError):
        return 0
    if buy <= 0:
        return 0
    if stop >= buy:
        return 99
    if target <= buy:
        return 0
    prob = round((target - buy) / (target - stop) * 99)
    return max(0, min(99, prob))

