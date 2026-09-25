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
from . import func, focus
from .models.models import (SectorList, StockList, FocusStock, FocusHistory, TransOrder,
                            TransHistory, TransReview, FilterTask, FilterResult)
from .forms.forms import FocusStockForm, TransHistoryForm, CashConfigForm, ReviewForm, CAT_CHOICES, MARKET_CHOICES, INTENT_CHOICES

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

MARK_CONFIG_INIT = {
    'showMark': False,
    'focus': 0,
    'status': 0,
    'hide': 0
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
    params_cat = params.get('cat', None)

    if (params_code and params_market):
        if params_cat is None:
            params_cat = get_cat_from_code(params_code, params_market)
        
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
def _build_chart_response(request, site, code, market, name, cat, view_mode):
    """
    构建图表页面响应的共用函数：返回 (html_content, context_dict)
    消除 navi/pilot 路径与通用路径中的重复代码（构建 context、设置 backUrl、获取 page_config、渲染模板）
    """
    context = {
        'site': site,
        'code': code,
        'name': name,
        'market': market,
        'cat': cat,
        'view': view_mode
    }
    # 统一 backUrl 处理：所有 view 页面使用 set_view_back/get_view_back 机制
    # 新增 view 类型时务必在此添加对应条目，否则 loadChartPage 后 backUrl 会被覆盖丢失
    backUrl_defaults = {
        '/filter/view': '/filter/list',
        '/stocks/view': '/sector/list',
        '/refer/view': '/refer/list',
        '/sector/view': '/sector/list',
        '/focus/view': '/focus/list',
        '/trans/view': '/trans/list',
        '/review/focus/view': '/review/focus/list',
        '/review/trans/view': '/review/trans/list',
    }
    if site in backUrl_defaults:
        context['backUrl'] = func.get_view_back(request.session) or backUrl_defaults[site]

    page_config = get_page_config(request.session, site, cat)
    context.update(page_config)

    html_template = 'chart-kline.html' if view_mode == 'kline' else 'chart-trend.html'
    html_content = render(request, html_template, {}).content.decode('utf-8')

    return html_content, context


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

    if param_cat is None:
        param_cat = get_cat_from_code(param_code, param_market)

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
        navi_data = func.get_cache(request.session, f'{param_site}-navi-data', {})
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
                # pilot_idx=-1 表示汇总，不需要 history_id
                if pilot_list and 0 <= pilot_idx < len(pilot_list):
                    history_id = pilot_list[pilot_idx][0]
            detail = _get_stock_detail(param_site, code, market, history_id)
            if detail:
                view_mode = func.get_cache(request.session, 'view', 'kline')
                # 更新当前股票 code，供返回列表时页码定位（navi 切换是 AJAX，不经过 filter_view）
                func.set_view_current_code(request.session, code)
                html_content, context = _build_chart_response(
                    request, param_site, code, market,
                    detail.get('name', ''), detail.get('cat', 'stock'), view_mode
                )
                # 将 html 和 chart 配置附加到 detail
                detail['html'] = html_content
                detail['chart'] = context
                # pilot 切换时附加指示器数据
                if param_func == 'pilot':
                    pilot_idx = navi_data['navi_params']['pilotIndex']
                    pilot_total = navi_data['navi_params']['pilotCount']
                    pilot_list = navi_data.get('pilot_list', [])
                    pilot_date = ''
                    pilot_action = ''
                    is_summary = (pilot_idx == -1)
                    if not is_summary and pilot_list and 0 <= pilot_idx < len(pilot_list):
                        pilot_date = pilot_list[pilot_idx][1].strftime('%Y-%m-%d') if pilot_list[pilot_idx][1] else ''
                        # 获取操作类型
                        from .trans import TransHistory
                        history = TransHistory.objects.filter(id=pilot_list[pilot_idx][0]).first()
                        if history:
                            pilot_action = history.get_action_display()
                    detail['pilot_idx'] = pilot_idx
                    detail['pilot_total'] = pilot_total
                    detail['pilot_date'] = pilot_date
                    detail['pilot_action'] = pilot_action
                    detail['is_summary'] = is_summary
                return JsonResponse(detail)
            else:
                return JsonResponse({'error': '股票不存在'}, status=404)
        else:
            return JsonResponse({'error': '无可用股票'}, status=400)
    else:
        return JsonResponse({'error': f'未知功能: {param_func}'}, status=400)

    view_mode = func.get_cache(request.session, 'view', 'kline')
    # 更新当前股票 code，供返回列表时页码定位（loadChartPage 是 AJAX，不经过 filter_view）
    func.set_view_current_code(request.session, param_code)

    # 导航缓存失效（如 hide 后被删除）时，重新构建，避免底部导航栏丢失
    navi_data = func.get_cache(request.session, f'{param_site}-navi-data', {})
    if (param_site, param_code, param_market) != navi_data.get('site_code_market', None):
        set_navi_data(request.session, param_site, param_code, param_market, None, 'init')

    html_content, context = _build_chart_response(
        request, param_site, param_code, param_market,
        param_name, param_cat, view_mode
    )
    return JsonResponse({'html': html_content, 'chart': context})


def get_page_config(session, site, cat):
    deci = 3 if cat in ('fund', 'bond') else 2
        
    trend_params_map = {
        '/focus/view': {'plus': False, 'exit': True, 'edit': True, 'deal': True, 'divd': False},
        '/trans/view': {'plus': False, 'exit': False, 'edit': True, 'deal': True, 'divd': True},
        '/review/focus/view': {'plus': True, 'exit': False, 'edit': False, 'deal': False, 'divd': False},
        '/review/trans/view': {'plus': True, 'exit': False, 'edit': False, 'deal': False, 'divd': False}
    }

    view = func.get_cache(session, 'view', 'kline')
    if (view == 'kline'): 
        kline.set_kline_params(session, 'deci', deci)
        kline_init = kline.get_kline_params(session)
        trend_init = {}
    else:
        kline_init = {}
        trend_init = trend_params_map[site] if site in trend_params_map else TREND_PARAMS_INIT

    navi_data = func.get_cache(session, f'{site}-navi-data', {})
    navi_init = get_navi_params(session, site, navi_data)
    mark_init = get_mark_config(session, site, navi_data)

    return {
        'kline': kline_init,
        'trend': trend_init,
        'navi': navi_init,
        'mark': mark_init,
        'deci': deci
    }


def get_mark_config(session, site, navi_data):
    if site == '/sector/view':
        if navi_data:
            get_site, code, market = navi_data.get('site_code_market')
            if get_site == site:
                instance = SectorList.objects.filter(code=code).first()
            else:
                return MARK_CONFIG_INIT
        else:
            return MARK_CONFIG_INIT

        mark_config = {
            'showMark': True,
            'showFocus': False,
            'showStatus': True,
            'showHide': False,
            'focus': 0,
            'status': instance.mark
        }
    elif site == '/filter/view':
        # 筛选结果页：显示 关注/1(优先股)/2(潜力股)/隐藏 按钮
        if navi_data:
            get_site, code, market = navi_data.get('site_code_market')
            if get_site == site:
                task_id = func.get_cache(session, 'filter-current-task')
                instance = FilterResult.objects.filter(task_id=task_id, code=code, market=market).first()
                focused = FocusStock.objects.filter(
                    code=code, market=market, status=FocusStock.STATUS_WATCHING).exists()
            else:
                return MARK_CONFIG_INIT
        else:
            return MARK_CONFIG_INIT

        mark_config = {
            'showMark': True,
            'showFocus': True,
            'showStatus': True,
            'showHide': True,
            'focus': 1 if focused else 0,
            'status': instance.mark if instance else ''
        }
    elif site == '/stocks/view':
        # 板块股票等通用股票页：显示 关注/标记/隐藏 按钮
        if navi_data:
            get_site, code, market = navi_data.get('site_code_market')
            if get_site == site:
                instance = StockList.objects.filter(code=code, market=market).first()
                focused = FocusStock.objects.filter(
                    code=code, market=market, status=FocusStock.STATUS_WATCHING).exists()
            else:
                return MARK_CONFIG_INIT
        else:
            return MARK_CONFIG_INIT

        mark_config = {
            'showMark': True,
            'showFocus': True,
            'showStatus': True,
            'showHide': True,
            'focus': 1 if focused else 0,
            'status': instance.mark if instance else ''
        }
    elif site == '/refer/view':
        # 筛选对比结果页：显示 关注/标记/隐藏 按钮
        if navi_data:
            get_site, code, market = navi_data.get('site_code_market')
            if get_site == site:
                instance = StockList.objects.filter(code=code, market=market).first()
                focused = FocusStock.objects.filter(
                    code=code, market=market, status=FocusStock.STATUS_WATCHING).exists()
            else:
                return MARK_CONFIG_INIT
        else:
            return MARK_CONFIG_INIT

        mark_config = {
            'showMark': True,
            'showFocus': True,
            'showStatus': True,
            'showHide': True,
            'focus': 1 if focused else 0,
            'status': instance.mark if instance else ''
        }
    else:
        mark_config = MARK_CONFIG_INIT

    return mark_config


def get_navi_params(session, site, navi_data):
    navi_params_limited = ['/sector/view', '/focus/view', '/trans/view',
                           '/review/focus/view', '/review/trans/view', '/filter/view', '/stocks/view', '/refer/view']
    if site in navi_params_limited:
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
        navi_idx = navi_params['naviIndex']
        navi_total = navi_params['naviCount']
        showPilot = navi_params['showPilot']
        # 页面初始化时（function != 'pilot'），重新查询 pilot_list，确保数据最新
        if function != 'pilot' and site in show_pilot_limited:
            pilot_list = get_pilot_list(site, code, market)
            pilot_total = len(pilot_list)
            if site in ['/trans/view', '/review/trans/view']:
                pilot_idx = func.get_cache(session, f'{site}-pilot', -1)
                if pilot_idx >= pilot_total:
                    pilot_idx = pilot_total - 1
                if pilot_idx < -1:
                    pilot_idx = -1
            else:
                pilot_idx = func.get_cache(session, f'{site}-pilot', pilot_total - 1)
                if pilot_idx >= pilot_total:
                    pilot_idx = pilot_total - 1
                if pilot_idx < 0:
                    pilot_idx = 0
        else:
            pilot_list = navi_data['pilot_list']
            pilot_total = navi_params['pilotCount']
            pilot_idx = navi_params['pilotIndex']
    else:
        navi_list = get_navi_list(site, session)
        if not navi_list:
            return {}
        navi_total = len(navi_list)

        if site in show_pilot_limited:
            showPilot = True
            pilot_list = get_pilot_list(site, code, market)
            pilot_total = len(pilot_list)
            if site in ['/trans/view', '/review/trans/view']:
                # trans/view: pilot_idx=-1 表示汇总
                pilot_idx = func.get_cache(session, f'{site}-pilot', -1)
                if pilot_idx >= pilot_total:
                    pilot_idx = pilot_total - 1
                if pilot_idx < -1:
                    pilot_idx = -1
            else:
                pilot_idx = func.get_cache(session, f'{site}-pilot', pilot_total - 1)
                if pilot_idx >= pilot_total:
                    pilot_idx = pilot_total - 1
                if pilot_idx < 0:
                    pilot_idx = 0
        else:
            showPilot = False
            pilot_list = {}
            pilot_total = 0
            pilot_idx = -1

    if function == 'navi': 
        shift = 1 if action == 'next' else -1
    else:
        shift = 0
    try:
        navi_idx = navi_list.index((code, market)) + shift
    except ValueError:
        # 股票不在导航列表中（已被 hide 或不存在）：删除旧缓存，确保 get_page_config 读到空
        # 否则旧缓存（如下一只股票的导航数据）会导致 showNavi=true 但导航列表不含当前股票，页面状态异常
        func.delete_cache(session, f'{site}-navi-data')
        return {}
    code, market = navi_list[navi_idx]

    if showPilot and function == 'pilot':
        if site in ['/trans/view', '/review/trans/view']:
            # trans/view: up=prev(更早), down=next(更晚/汇总)
            if action == 'prev':
                if pilot_idx == -1:
                    pilot_idx = pilot_total - 1  # 汇总 → 最近一笔
                else:
                    pilot_idx -= 1  # 历史 → 更早的历史
            elif action == 'next':
                if pilot_idx == pilot_total - 1:
                    pilot_idx = -1  # 最近一笔 → 汇总
                else:
                    pilot_idx += 1  # 历史 → 更晚的历史
        else:
            shift = 1 if action == 'next' else -1 if action == 'prev' else 0
            pilot_idx += shift

    # pilot 按钮可用性
    if site in ['/trans/view', '/review/trans/view']:
        # up(prev): 汇总时 pilot_total>1 可用；历史时 i>0 可用
        pilotPrev = (pilot_idx == -1 and pilot_total > 1) or (pilot_idx > 0)
        # down(next): 汇总时禁用；历史时始终可用（最近一笔点down回汇总）
        pilotNext = (pilot_idx >= 0)
    else:
        pilotPrev = pilot_idx > 0
        pilotNext = pilot_idx < pilot_total - 1

    # kline-deadline: 历史模式下设为该笔日期，汇总模式下删除
    if pilot_idx >= 0 and pilot_list and 0 <= pilot_idx < len(pilot_list):
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

    # 同步保存 pilot_idx 到 trans_view 使用的 session key
    if showPilot:
        func.set_cache(session, f'{site}-pilot', pilot_idx, 600)

    navi_data = func.get_cache(session, f'{site}-navi-data', {})
    return navi_data


def get_navi_list(site, session=None):
    if site == '/focus/view':
        qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).order_by('sort_order')
        navi_list = list(qs.values_list('code', 'market')) 

    elif site == '/trans/view':
        qs = TransOrder.objects.filter(status=TransOrder.STATUS_OPEN).order_by('-created_at')
        navi_list = list(qs.values_list('code', 'market')) 
    elif site == '/sector/view':
        # 优先使用板块清单传入的自定义 navi 列表（标记筛选后）；否则用全部板块
        custom = func.get_cache(session, 'sector-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            qs = SectorList.objects.all()
            navi_list = list(qs.values_list('code', 'market'))
    elif site == '/filter/view':
        # 优先使用对比页传入的自定义 navi 列表；否则用当前 task 全部结果
        custom = func.get_cache(session, 'filter-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            task_id = func.get_cache(session, 'filter-current-task') if session else None
            qs = FilterResult.objects.filter(task_id=task_id).exclude(hide='1').order_by('sort_order', 'id')
            navi_list = list(qs.values_list('code', 'market'))
    elif site == '/stocks/view':
        # 优先使用板块股票清单传入的自定义 navi 列表；否则用全部未 hide 股票
        custom = func.get_cache(session, 'stocks-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            qs = StockList.objects.exclude(hide='1').order_by('code')
            navi_list = list(qs.values_list('code', 'market'))
    elif site == '/refer/view':
        # 优先使用筛选对比页传入的自定义 navi 列表；否则用全部未 hide 股票
        custom = func.get_cache(session, 'refer-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            qs = StockList.objects.exclude(hide='1').order_by('code')
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
    elif site == '/trans/view':
        order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
        pilot_list = list(order.histories.all().order_by('date', 'id').values_list('id', 'date')) if order else []
    else:
        pilot_list = []
    return pilot_list


def get_cat_from_code(code, market):
    """从 StockList 获取 cat，若不存在则判断是否为指数（默认 index），否则 stock"""
    stock = StockList.objects.filter(code=code, market=market).first()
    if stock and stock.cat:
        return stock.cat
    # 若不存在或 cat 为空，根据代码判断是否为指数（简单判断）
    # 指数通常以 000、399、688 等开头
    if code.startswith(('000', '399', '688')):
        return 'index'
    return 'stock'


def _get_stock_detail(site, code, market, history_id=None):
    if site in ['/focus/view', '/review/focus/view']:
        focus_inst = FocusStock.objects.filter(code=code, market=market).first()
        if not focus_inst:
            return {}
        history = None
        if history_id:
            history = focus_inst.histories.filter(id=history_id).first()
        return focus.get_focus_data_dict(focus_inst, history)   # 直接调用统一函数

    elif site == '/sector/view':
        sector = SectorList.objects.filter(code=code).first()
        if not sector:
            return {}
        data = {
            'code': sector.code,
            'market': sector.market,
            'name': sector.name,
            'cat': sector.cat
        }
        return data
    elif site == '/stocks/view':
        stock = StockList.objects.filter(code=code, market=market).first()
        if not stock:
            return {}
        return {
            'code': code,
            'market': market,
            'name': stock.name,
            'cat': stock.cat,
        }
    elif site == '/refer/view':
        # 优先从 FilterResult 找最新记录（获取名称），兜底 StockList
        res = FilterResult.objects.filter(code=code, market=market).order_by('-task_id').first()
        if res:
            return {'code': code, 'market': market, 'name': res.name, 'cat': res.cat}
        stock = StockList.objects.filter(code=code, market=market).first()
        if not stock:
            return {}
        return {'code': code, 'market': market, 'name': stock.name, 'cat': stock.cat}
    elif site == '/filter/view':
        # 筛选结果股：返回最新所属任务中的基本信息
        res = FilterResult.objects.filter(code=code, market=market).order_by('-task_id').first()
        if not res:
            return {}
        return {
            'code': code,
            'market': market,
            'name': res.name,
            'cat': res.cat,
        }
    elif site in ['/trans/view', '/review/trans/view']:
        from .trans import TransOrder, get_trans_data_dict
        order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
        if not order:
            return {}
        history = None
        if history_id:
            history = order.histories.filter(id=history_id).first()
        return get_trans_data_dict(order, history)
    return {}


def _json_error(msg, status=400):
    return JsonResponse({'error': msg}, status=status)


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
