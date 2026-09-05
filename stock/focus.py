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
            deci = 3 if (fs.cat == 'fund' or fs.cat == 'bond') else 2
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
        deci = 3 if (fs.cat == 'fund' or fs.cat == 'bond') else 2
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
    site = '/focus/plus'

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
                focus.created_at = focus.focus_date
                focus.updated_at = focus.focus_date
                focus.code = code
                focus.market = market
                focus.cat = cat
                focus.win_ratio = cash.calc_win_ratio(focus.plan_price, focus.target_price, focus.stop_price)
                focus.allowed_qty = cash.calc_allowed_qty(focus.plan_price)
                max_sort = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).count()
                focus.sort_order = max_sort
                focus.save()
                focus.save_history(action='create')
                return redirect('focus_view', market=focus.market, code=focus.code)
    else:
        initial = {}
        form = FocusStockForm(initial=initial)
    
    view_mode = func.get_cache(request.session, 'view', 'kline') 
    chart_init = {
        'site': site,
        'code': code,
        'market': market,
        'name': name,
        'cat': cat,
        'view': view_mode
    }

    return render(request, 'focus-plus.html', {
        'form': form, 
        'available': CashConfig.get_config().available,  
        # 需转换为 JSON 字符串
        'chart': json.dumps(chart_init)   
    })


def focus_view(request, market, code):
    site = '/focus/view'
    if request.method == 'POST':
        focus = get_object_or_404(FocusStock, code=code, market=market, status=FocusStock.STATUS_WATCHING)
        form = FocusStockForm(request.POST, instance=focus, view_mode=True)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.win_ratio = cash.calc_win_ratio(updated.plan_price, updated.target_price, updated.stop_price)
            updated.allowed_qty = cash.calc_allowed_qty(updated.plan_price)
            updated.updated_at = updated.focus_date 
            updated.save()
            updated.save_history(action='edit')
            func.delete_cache(request.session, f'{site}-navi-data')
        
        return redirect('focus_view', market=market, code=code)
    else:
        navi_data = func.get_cache(request.session, f'{site}-navi-data', {})
        if (site, code, market) != navi_data.get('site_code_market', None):
            navi_data = chart.set_navi_data(request.session, site, code, market, 'pilot', 'init')

        focus = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
        histories = focus.histories.all().order_by('edit_date') if focus else None
        pilot_idx = navi_data.get('navi_params', {}).get('pilotIndex', 0)
        pilot_history = histories[pilot_idx]

        focus.focus_date = pilot_history.edit_date
        focus.intent = pilot_history.intent
        focus.plan_price = pilot_history.plan_price
        focus.plan_qty = pilot_history.plan_qty
        focus.target_price = pilot_history.target_price
        focus.stop_price = pilot_history.stop_price
        focus.win_ratio = pilot_history.win_ratio
        focus.comments = pilot_history.comments

        form = FocusStockForm(instance=focus, view_mode=True)
        view_mode = func.get_cache(request.session, 'view', 'kline') 

        # 图表配置
        chart_init = {
            'site': site,
            'code': code,
            'market': market,
            'name': focus.name,
            'cat': focus.cat,
            'view': view_mode
        }
        
        return render(request, 'focus-view.html', {
            'form': form,
            'chart': json.dumps(chart_init),
            'edit_mode': False,
            'available': CashConfig.get_config().available
        })
