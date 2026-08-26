import os
import json
import datetime
from decimal import Decimal
import pandas as pd
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from .fetch import tushare, kline, trend, quote
from . import func
from .models.models import FocusStock, FocusHistory, TransOrder, TransDeal, TransReview
from .forms.forms import FocusStockForm, TransDealForm, CashConfigForm, ReviewForm

NAVI_PARAMS_INIT = {
    'showNavi': False,
    'naviIndex': 0,
    'naviCount': 0,
    'naviPrev': False,
    'naviNext': False,
    'showPilot': False,
    'pilotPrev': False,
    'pilotNext': False,
    'backList':False
}

TREND_PARAMS_INIT = {
    'plus': False, 
    'exit': False, 
    'edit': False, 
    'deal': False, 
    'divd': False
}


@require_http_methods(["POST"])
def chart_data_api(request):
    try:
        params = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error('无效JSON')
    params_func = params.get('func')
    params_code = params.get('code', None)
    params_market = params.get('market', None)    
    params_cat = params.get('cat', 'E')

    if (params_code and params_market):
        if params_func == 'get-kline-data':
            return kline.kline_data_for_chart(request.session, params_cat, params_market, params_code)
        elif params_func == 'get-trend-data':
            step = params.get('step')
            data = trend.trend_data_for_chart(request.session, f'{params_code}.{params_market}', step)
            return JsonResponse(data)
        elif params_func == 'navi':
            return _navi_switch(params.get('site', ''), params_code, params.get('value', ''))
        else:
            return _json_error('不支持的功能')
    else:
         return _json_error('缺少股票信息')


@require_http_methods(["POST"])
def chart_view_api(request):
    """
    处理图表视图切换、参数更新，返回新的图表 HTML 片段
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '无效JSON'}, status=400)

    param_func = data.get('func')
    param_value = data.get('value')
    param_site = data.get('site')
    param_code = data.get('code')
    param_name = data.get('name')
    param_market = data.get('market')
    param_cat = data.get('cat')
    
    if not all([param_func, param_code, param_market]):
        return JsonResponse({'error': '参数缺失'}, status=400)

    if param_func == 'view':
        func.set_session(request.session, 'view', param_value)
    elif param_func in ['k', 'd']:
        kline.set_kline_params(request.session, param_func, int(param_value))
    elif param_func == 'right':
        kline.set_kline_params(request.session, param_func, param_value)
    elif param_func == 'freq':
        kline.set_kline_params(request.session, param_func, param_value)
    else:
        return JsonResponse({'error': f'未知功能: {param_func}'}, status=400)

    context = {
        'site': param_site,
        'code': param_code,
        'name': param_name,
        'market': param_market,
        'cat': param_cat
    }
    page_config = get_page_config(request.session, param_site, param_cat)
    context.update(page_config)

    view_mode = func.get_session(request.session, 'view', 'kline')
    html_template = 'chart-kline.html' if  view_mode == 'kline' else 'chart-trend.html'
    html_content = render(request, html_template, context).content.decode('utf-8')

    return JsonResponse({'html': html_content})


def get_page_config(session, site, cat):   
    view_init = func.get_session(session, 'view', 'kline')
    deci = 2 if cat == 'stock' else 3
        
    trend_params_map = {
        'focus/plus': {'plus': False, 'exit': True, 'edit': False, 'deal': True, 'divd': False},
        'focus/view': {'plus': False, 'exit': True, 'edit': True, 'deal': True, 'divd': False},
        'trans/view': {'plus': False, 'exit': False, 'edit': True, 'deal': True, 'divd': True},
        'review/view': {'plus': True, 'exit': False, 'edit': False, 'deal': False, 'divd': False}
    }
    
    if (view_init == 'kline'):
        kline.set_kline_params(session, 'deci', deci)
        kline_init = kline.get_kline_params(session)
        trend_init = {}
    else:
        kline_init = {}
        trend_init = trend_params_map[site] if site in trend_params_map else TREND_PARAMS_INIT

    navi_init = get_navi_params(session)

    return {
        'view': view_init,
        'kline': kline_init,
        'trend': trend_init,
        'navi': navi_init,
        'deci': deci
    }


def get_navi_params(session):
    navi_params = func.get_session(session, 'navi_params', NAVI_PARAMS_INIT)
    return navi_params


def set_navi_params(session, key, value):
    navi_params = func.get_session(session, 'navi_params', NAVI_PARAMS_INIT)
    navi_params[key] = value
    func.set_session(session, 'navi_params', navi_params)


def _navi_context(site, current_code, queryset, code_field='code'):
    codes = list(queryset.values_list(code_field, flat=True))
    total = len(codes)
    try:
        idx = codes.index(current_code)
    except ValueError:
        idx = 0
    return {
        'navi': total > 1,
        'navi_index': idx,
        'navi_count': total,
        'navi_prev': idx > 0,
        'navi_next': idx < total - 1,
        'navi_prev_code': codes[idx - 1] if idx > 0 else '',
        'navi_next_code': codes[idx + 1] if idx < total - 1 else '',
    }


def _navi_switch(site, current_code, direction):
    if site == 'focus/view':
        qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).order_by('sort_order', '-focus_time')
        codes = list(qs.values_list('code', flat=True))
    elif site == 'trans/view':
        qs = TransOrder.objects.filter(status=TransOrder.STATUS_OPEN).order_by('-created_at')
        codes = list(qs.values_list('code', flat=True))
    elif site == 'review/view':
        # 已交易复盘：左右切换不同股票
        all_closed = TransOrder.objects.filter(status=TransOrder.STATUS_CLOSED).order_by('close_time')
        stock_latest = {}
        for o in all_closed:
            if o.code not in stock_latest or o.close_time > stock_latest[o.code].close_time:
                stock_latest[o.code] = o
        unique_stocks = list(stock_latest.values())
        unique_stocks.sort(key=lambda x: x.close_time, reverse=True)
        codes = [s.code for s in unique_stocks]
        if not codes or current_code not in codes:
            return JsonResponse({'code': current_code, 'url': f'/review/view/{current_code}/'})
        idx = codes.index(current_code)
        if direction == 'prev' and idx > 0:
            target = codes[idx - 1]
        elif direction == 'next' and idx < len(codes) - 1:
            target = codes[idx + 1]
        else:
            target = current_code
        orders = TransOrder.objects.filter(code=target, status=TransOrder.STATUS_CLOSED).order_by('close_time')
        round_num = len(orders)
        return JsonResponse({'code': target, 'url': f'/review/view/{target}/?round={round_num}'})
    elif site == 'review/focus/view':
        # 未交易关注：左右切换不同股票
        qs = FocusStock.objects.filter(
            status=FocusStock.STATUS_CLOSED,
            close_reason=FocusStock.CLOSE_REASON_MANUAL
        ).exclude(orders__isnull=False).order_by('-close_time')
        stock_latest = {}
        for f in qs:
            if f.code not in stock_latest or f.close_time > stock_latest[f.code].close_time:
                stock_latest[f.code] = f
        codes = sorted(stock_latest.keys(), key=lambda c: stock_latest[c].close_time, reverse=True)
        if not codes or current_code not in codes:
            return JsonResponse({'code': current_code, 'url': f'/review/focus/view/{current_code}/'})
        idx = codes.index(current_code)
        if direction == 'prev' and idx > 0:
            target = codes[idx - 1]
        elif direction == 'next' and idx < len(codes) - 1:
            target = codes[idx + 1]
        else:
            target = current_code
        # 获取目标股票的最新轮次（总轮次数）
        target_round = FocusStock.objects.filter(
            code=target,
            status=FocusStock.STATUS_CLOSED,
            close_reason=FocusStock.CLOSE_REASON_MANUAL
        ).exclude(orders__isnull=False).count()
        return JsonResponse({'code': target, 'url': f'/review/focus/view/{target}/?round={target_round}'})
    else:
        codes = []

    # 处理其他站点...
    if not codes or current_code not in codes:
        return JsonResponse({'code': current_code})
    idx = codes.index(current_code)
    if direction == 'prev' and idx > 0:
        target = codes[idx - 1]
    elif direction == 'next' and idx < len(codes) - 1:
        target = codes[idx + 1]
    else:
        target = current_code
    return JsonResponse({'code': target})


def _json_error(msg, status=400):
    return JsonResponse({'error': msg}, status=status)