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
from .forms.forms import FocusStockForm, TransDealForm, CashConfigForm, ReviewForm, CAT_CHOICES, MARKET_CHOICES, INTENT_CHOICES

NAVI_PARAMS_INIT = {
    'showNavi': False,
    'naviIndex': -1,
    'naviCount': 0,
    'naviPrev': False,
    'naviNext': False,
    'showPilot': False,
    'pilotIndex': -1,
    'pilotCount': 0,
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
    params_site= params.get('site', '')
    params_func = params.get('func')
    params_code = params.get('code', None)
    params_market = params.get('market', None)
    params_cat = params.get('cat', 'E')

    if (params_code and params_market):
        if params_func == 'get-kline-data':
            return kline.kline_data_for_chart(request.session, params_site, params_cat, params_market, params_code)
        elif params_func == 'get-trend-data':
            step = params.get('step')
            data = trend.trend_data_for_chart(request.session, f'{params_code}.{params_market}', step)
            return JsonResponse(data)
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
        func.set_cache(request.session, 'view', param_value)
    elif param_func in ['k', 'd']:
        kline.set_kline_params(request.session, param_func, int(param_value))
    elif param_func == 'right':
        kline.set_kline_params(request.session, param_func, param_value)
    elif param_func == 'freq':
        kline.set_kline_params(request.session, param_func, param_value)
        deadline_params = func.get_cache(request.session, 'kline-deadline')
        if deadline_params and (param_site, param_code, param_market) == deadline_params.get('site_code_market', None):
            kline.set_kline_params(request.session, 'deadline', deadline_params.get('deadline', -1))
    elif param_func in ['navi', 'pilot']:
        navi_data = set_navi_data(
            request.session,
            param_site,
            param_code,
            param_market,
            param_func,
            param_value
        )
        if navi_data:
            idx = navi_data['navi_params']['naviIndex']
            code, market = navi_data['navi_list'][idx]
            # 如果是 pilot 切换，需要知道当前选中的历史记录 ID
            history_id = None
            if param_func == 'pilot':
                pilot_idx = navi_data['navi_params']['pilotIndex']
                pilot_list = navi_data['pilot_list']
                if pilot_list and 0 <= pilot_idx < len(pilot_list):
                    history_id = pilot_list[pilot_idx][0] 
            detail = _get_stock_detail(param_site, code, market, history_id)
            if detail:
                return JsonResponse(detail)
            else:
                return JsonResponse({'error': '股票不存在'}, status=404)
        else:
            return JsonResponse({'error': '无可用股票'}, status=400)
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

    view_mode = func.get_cache(request.session, 'view', 'kline')
    html_template = 'chart-kline.html' if  view_mode == 'kline' else 'chart-trend.html'
    html_content = render(request, html_template, {}).content.decode('utf-8')

    return JsonResponse({'html': html_content, 'chart': context})


def get_page_config(session, site, cat):   
    view_init = func.get_cache(session, 'view', 'kline')
    deci = 2 if cat == 'stock' else 3
        
    trend_params_map = {
        '/focus/view': {'plus': False, 'exit': True, 'edit': True, 'deal': True, 'divd': False},
        '/trans/view': {'plus': False, 'exit': False, 'edit': True, 'deal': True, 'divd': True},
        '/review/focus/view': {'plus': True, 'exit': False, 'edit': False, 'deal': False, 'divd': False},
        '/review/trans/view': {'plus': True, 'exit': False, 'edit': False, 'deal': False, 'divd': False}
    }
    
    if (view_init == 'kline'):
        kline.set_kline_params(session, 'deci', deci)
        kline_init = kline.get_kline_params(session)
        trend_init = {}
    else:
        kline_init = {}
        trend_init = trend_params_map[site] if site in trend_params_map else TREND_PARAMS_INIT

    navi_init = get_navi_params(session, site)

    return {
        'view': view_init,
        'kline': kline_init,
        'trend': trend_init,
        'navi': navi_init,
        'deci': deci
    }


def get_navi_params(session, site):
    navi_params_limited = ['/focus/view', '/trans/view', '/review/focus/view', '/review/trans/view']
    if site in navi_params_limited:
        navi_data = func.get_cache(session, f'{site}-navi-data', {})
        navi_params = navi_data.get('navi_params', NAVI_PARAMS_INIT)
    else:
        navi_params = NAVI_PARAMS_INIT
    return navi_params


def set_navi_data(session, site, code, market, function, action):
    show_pilot_limited = ['/focus/view', '/trans/view', '/review/focus/view', '/review/trans/view']    
    navi_data = func.get_cache(session, f'{site}-navi-data', {})
    if (site, code, market) != navi_data.get('site_code_market', None):
        navi_data = {}

    if navi_data:
        navi_params = navi_data['navi_params']
        navi_list = navi_data['navi_list']
        pilot_list = navi_data['pilot_list']
        navi_idx = navi_params['naviIndex']
        navi_total = navi_params['naviCount']
        showPilot = navi_params['showPilot']
        pilot_idx = navi_params['pilotIndex']
        pilot_total = navi_params['pilotCount']
    else:
        navi_list = get_navi_list(site)
        if not navi_list:
            return {}
        navi_total = len(navi_list)

        if site in show_pilot_limited:
            showPilot = True
            pilot_list = get_pilot_list(site, code, market)
            pilot_total = len(pilot_list)
            pilot_idx = pilot_total - 1
        else:
            showPilot = False
            pilot_list = {}
            pilot_total = 0
            pilot_idx = -1

    if function == 'navi': 
        shift = 1 if action == 'next' else -1
    else:
        shift = 0
    navi_idx = navi_list.index((code, market)) + shift

    if showPilot and function == 'pilot':        
        shift = 1 if action == 'next' else -1 if action == 'prev' else 0
        pilot_idx += shift

    pilotPrev = pilot_idx > 0
    pilotNext = pilot_idx < pilot_total - 1

    if (pilotNext):
        pilot_id, pilot_date = pilot_list[pilot_idx]
        deadline = pilot_date.strftime('%Y%m%d')        
        func.set_cache(
            session, 
            'kline-deadline', 
            {'site_code_market':(site, code, market), 'deadline': deadline}, 
            600
        )
    else:
        func.delete_cache(session, 'kline-deadline')

    navi_params = {
        'showNavi': True,
        'naviIndex': navi_idx,
        'naviCount': navi_total,
        'naviPrev': navi_idx > 0,
        'naviNext': navi_idx < navi_total - 1,
        'showPilot': showPilot,
        'pilotIndex': pilot_idx,
        'pilotCount': pilot_total,
        'pilotPrev': pilotPrev,
        'pilotNext': pilotNext,
        'backList':True
    }

    navi_data = {
        'site_code_market':(site, code, market),
        'navi_params': navi_params,
        'navi_list': navi_list,
        'pilot_list': pilot_list,
    }

    func.set_cache(session, f'{site}-navi-data', navi_data, 600)

    return navi_data


def get_navi_list(site):
    if site == '/focus/view':
        qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).order_by('sort_order')
        navi_list = list(qs.values_list('code', 'market')) 

    elif site == '/trans/view':
        qs = TransOrder.objects.filter(status=TransOrder.STATUS_OPEN).order_by('-created_at')
        navi_list = list(qs.values_list('code', 'market')) 
    elif site == '/review/focus/view':
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
    elif site == 'review/trans/view':
        pass
    else:
        navi_list = []

    return navi_list


def get_pilot_list(site, code, market):
    if site == '/focus/view':
        focus = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
        pilot_list = list(focus.histories.all().order_by('edit_date').values_list('id', 'edit_date')) if focus else []
    else:
        pass
    return pilot_list


def _get_stock_detail(site, code, market, history_id=None):
    if site in ['/focus/view', '/review/focus/view']:
        if history_id:
            history = FocusHistory.objects.filter(id=history_id).first()
            if not history:
                return {}
            focus = history.focus
            data = {
                'code': focus.code,
                'market': focus.market,
                'name': focus.name,
                'cat': focus.cat,
                'focus_date': history.edit_date.strftime('%Y-%m-%d'),
                'plan_price': float(history.plan_price) if history.plan_price else 0,
                'plan_qty': history.plan_qty,
                'target_price': float(history.target_price) if history.target_price else 0,
                'stop_price': float(history.stop_price) if history.stop_price else 0,
                'allowed_qty': focus.allowed_qty,
                'win_ratio': float(history.win_ratio) if history.win_ratio else 0,
                'comments': history.comments,
                'intent': history.intent,
                'market_display': dict(MARKET_CHOICES).get(focus.market, focus.market),
                'cat_display': dict(CAT_CHOICES).get(focus.cat, focus.cat),
                'intent_display': dict(INTENT_CHOICES).get(history.intent, history.intent),
            }
            return data
        else:
            stock = FocusStock.objects.filter(code=code, market=market).first()
            if not stock:
                return {}
            data = {
                'code': stock.code,
                'market': stock.market,
                'name': stock.name,
                'cat': stock.cat,
                'focus_date': stock.focus_date.strftime('%Y-%m-%d'),
                'plan_price': float(stock.plan_price) if stock.plan_price else 0,
                'plan_qty': stock.plan_qty,
                'target_price': float(stock.target_price) if stock.target_price else 0,
                'stop_price': float(stock.stop_price) if stock.stop_price else 0,
                'allowed_qty': stock.allowed_qty,
                'win_ratio': float(stock.win_ratio) if stock.win_ratio else 0,
                'comments': stock.comments,
                'intent': stock.intent,
                'market_display': dict(MARKET_CHOICES).get(stock.market, stock.market),
                'cat_display': dict(CAT_CHOICES).get(stock.cat, stock.cat),
                'intent_display': dict(INTENT_CHOICES).get(stock.intent, stock.intent),
            }
            return data
    # 其他站点类似处理...
    return {}



# 备用
def _navi_switch(site, current_code, direction):
    if site == '/focus/view':
        qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).order_by('sort_order', '-focus_date')
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
    elif site == '/review/focus/view':
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