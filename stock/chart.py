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
from .models.models import FocusStock, FocusHistory, TransOrder, TransDeal, TransReview
from .forms.forms import FocusStockForm, TransDealForm, CashConfigForm, ReviewForm


@require_http_methods(["POST"])
def chart_data_api(request):
    try:
        params = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error('无效JSON')
    func = params.get('func')
    code = params.get('code', '')
    market = params.get('market', '')

    if (code and market):
        if func == 'get-kline-data':
            return kline.kline_data_for_chart('E', f'{code}.{market}')
        elif func == 'get-trend-data':
            init = params.get('init')
            data = trend.get_trend_data(code, init, request.session)
            return JsonResponse(data)
        elif func == 'navi':
            return _navi_switch(params.get('site', ''), code, params.get('value', ''))
        else:
            return _json_error('不支持的功能')
    else:
         return _json_error('缺少股票信息')


@require_http_methods(["GET"])
def chart_view_api(request):
    """视图切换，返回局部 HTML（func.js reloadChartView 用 innerHTML 替换）"""
    """
    try:
        params = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error('无效JSON')
    code = params.get('code', '')
    func = params.get('func')
    value = params.get('value', '')
    
    focus = FocusStock.objects.filter(code=code).first()
    view_mode = 'trend'
    if func == 'view':
        view_mode = value
    elif func in ('period', 'freq'):
        view_mode = 'kline'
    watching_qs = FocusStock.objects.filter(
        status=FocusStock.STATUS_WATCHING).order_by('sort_order', '-focus_time')
    navi = _navi_context('focus/view', code, watching_qs)
    context = {
        "name": focus.name if focus else '',
        "code": code, "display_code": pure_code_of(code),
        "cat": focus.cat if focus else 'stock',
        "view": view_mode, "screen": "norm",
        "interval": TREND_REQUEST_INTERVAL,
        "trend_act": {"exit": "end", "edit": "edit", "deal": "deal"},
        "show_pilot": False, "pilot_prev": False, "pilot_next": False,
        "show_tool_bar": True, "is_linkable": True,
        "focus": focus, "deci": calc.get_price_decimal(pure_code_of(code)),
    }
    context.update(navi)
    """
    view = request.GET.get('view', 'kline') 
    template = 'chart-kline.html' if view == 'kline' else 'chart-trend.html'

    return render(request, template, {})


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