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
from ..fetch import tushare, kline, trend, quote
from . import focus
from .. import utils
from ..models import (SectorList, StockList, FocusStock, FocusHistory, TransOrder,
                            TransHistory, TransReview, FilterTask, FilterResult, ReviewList)
from ..forms import FocusStockForm, TransHistoryForm, CashConfigForm, ReviewForm, CAT_CHOICES, MARKET_CHOICES, INTENT_CHOICES

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
def check_focus_api(request):
    """检查股票是否已关注，未关注时返回最后一个 EMA 值"""
    try:
        params = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error('无效JSON')

    code = params.get('code')
    market = params.get('market')
    cat = params.get('cat', 'stock')
    site = params.get('site', '')

    if not code or not market:
        return _json_error('缺少股票信息')

    # 查询是否已关注
    from ..models import FocusStock
    is_focused = FocusStock.objects.filter(
        code=code, market=market, status=FocusStock.STATUS_WATCHING
    ).exists()

    if is_focused:
        return JsonResponse({'focused': True})

    # 未关注，获取最新 K线数据，直接取最后一个 EMA 值
    from ..fetch.kline import kline_data_for_chart
    kline_response = kline_data_for_chart(request.session, site, cat, market, code)
    # kline_data_for_chart 返回 JsonResponse，需要解析 content 获取数据字典
    kline_data = json.loads(kline_response.content)
    av = kline_data.get('av', [])
    ema = None
    if av:
        last = av[-1]
        ema = last[1] if isinstance(last, (list, tuple)) else last

    return JsonResponse({'focused': False, 'ema': ema})


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
        context['backUrl'] = utils.get_view_back(request.session) or backUrl_defaults[site]

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
    param_navi_id = data.get('navi_id')
    
    if not all([param_func, param_code, param_market]):
        return JsonResponse({'error': '参数缺失'}, status=400)

    if param_cat is None:
        param_cat = get_cat_from_code(param_code, param_market)

    if param_func == 'view':
        utils.set_cache(request.session, 'view', param_value)
    elif param_func in ['k', 'd']:
        kline.set_kline_params(request.session, param_func, int(param_value))
    elif param_func == 'right':
        kline.set_kline_params(request.session, param_func, param_value)
    elif param_func == 'freq':
        kline.set_kline_params(request.session, param_func, param_value)
        # 切换周期时，同步更新对应周期的 EMA-K 和 EMA-D 值
        from ..fetch.config import get_kline_ema_k, get_kline_ema_d
        kline.set_kline_params(request.session, 'k', get_kline_ema_k(param_value))
        kline.set_kline_params(request.session, 'd', get_kline_ema_d(param_value))
        deadline_params = utils.get_cache(request.session, 'kline-deadline')
        if deadline_params and (param_site, param_code, param_market) == deadline_params.get('site_code_market', None):
            kline.set_kline_params(request.session, 'deadline', deadline_params.get('deadline', -1))
    elif param_func in ['navi', 'pilot']:        
        navi_data = utils.get_cache(request.session, f'{param_site}-navi-data', {})
        navi_data = set_navi_data(
            request.session,
            param_site,
            param_code,
            param_market,
            param_func,
            param_value,
            param_navi_id
        )
        if navi_data:
            idx = navi_data['navi_params']['naviIndex']
            navi_id, code, market = navi_data['navi_list'][idx]
            # 如果是 pilot 切换，需要知道当前选中的历史记录 ID 和类型
            history_id = None
            history_type = None
            if param_func == 'pilot':
                pilot_idx = navi_data['navi_params']['pilotIndex']
                pilot_list = navi_data['pilot_list']
                # pilot_idx=-1 表示汇总，不需要 history_id
                if pilot_list and 0 <= pilot_idx < len(pilot_list):
                    history_id = pilot_list[pilot_idx][0]
                    history_type = pilot_list[pilot_idx][2] if len(pilot_list[pilot_idx]) > 2 else None
            detail = _get_stock_detail(param_site, code, market, history_id, history_type, navi_id)
            if detail:
                view_mode = utils.get_cache(request.session, 'view', 'kline')
                # 更新当前股票 code，供返回列表时页码定位（navi 切换是 AJAX，不经过 filter_view）
                utils.set_view_current_code(request.session, code)
                html_content, context = _build_chart_response(
                    request, param_site, code, market,
                    detail.get('name', ''), detail.get('cat', 'stock'), view_mode
                )
                # 将 html 和 chart 配置附加到 detail
                detail['html'] = html_content
                detail['chart'] = context
                detail['navi_id'] = navi_id
                # 统一添加 pilot 相关数据
                detail['pilot_idx'] = navi_data['navi_params']['pilotIndex']
                detail['pilot_total'] = navi_data['navi_params']['pilotCount']
                detail['is_summary'] = (navi_data['navi_params']['pilotIndex'] == -1)
                detail['pilotPrev'] = navi_data.get('navi_params', {}).get('pilotPrev', False)
                detail['pilotNext'] = navi_data.get('navi_params', {}).get('pilotNext', False)
                # pilot 切换时附加指示器数据（pilot_date/pilot_action）
                if param_func == 'pilot':
                    pilot_idx = navi_data['navi_params']['pilotIndex']
                    pilot_list = navi_data.get('pilot_list', [])
                    pilot_date = ''
                    pilot_action = ''
                    pilot_qty = ''
                    pilot_price = ''
                    pilot_dividend_amount = ''  # 分红现金金额，前端用于与 tooltip 一致描述
                    is_summary = (pilot_idx == -1)

                    # 字段连接辅助函数：1个直接，2个用"和"，超过2个前面用"、"最后用"和"
                    def format_changes(changes, default='调整计划'):
                        if not changes:
                            return default
                        if len(changes) == 1:
                            return '调整' + changes[0]
                        if len(changes) == 2:
                            return '调整' + changes[0] + '和' + changes[1]
                        return '调整' + '、'.join(changes[:-1]) + '和' + changes[-1]

                    if not is_summary and pilot_list and 0 <= pilot_idx < len(pilot_list):
                        pilot_date = pilot_list[pilot_idx][1].strftime('%Y-%m-%d') if pilot_list[pilot_idx][1] else ''
                        # 获取 history 类型（trans/focus），兼容旧格式（只有两个元素）
                        pilot_type = pilot_list[pilot_idx][2] if len(pilot_list[pilot_idx]) > 2 else 'trans'

                        # trans 类型历史
                        if pilot_type == 'trans':
                            from .trans import TransHistory
                            history = TransHistory.objects.filter(id=pilot_list[pilot_idx][0]).first()
                            if history:
                                if history.action == TransHistory.ACTION_EDIT:
                                    # 编辑操作：对比上一条同类型记录，找出修改的目标价格和止损价格
                                    changes = []
                                    if pilot_idx > 0:
                                        # 找上一条同类型记录
                                        for prev_i in range(pilot_idx - 1, -1, -1):
                                            if len(pilot_list[prev_i]) > 2 and pilot_list[prev_i][2] == 'trans':
                                                prev_history = TransHistory.objects.filter(id=pilot_list[prev_i][0]).first()
                                                if prev_history:
                                                    if history.target_price != prev_history.target_price:
                                                        changes.append('目标价格')
                                                    if history.stop_price != prev_history.stop_price:
                                                        changes.append('止损价格')
                                                break
                                    pilot_action = format_changes(changes, default='调整目标和止损价格')
                                else:
                                    pilot_action = history.get_action_display()
                                pilot_qty = history.qty
                                cat = detail.get('cat', 'stock')
                                deci = 3 if cat in ('fund', 'bond') else 2
                                pilot_price = f"{float(history.price):.{deci}f}"
                                # 分红时携带现金分红金额，供前端 transPilotIndicator 与 tooltip 一致描述
                                pilot_dividend_amount = float(history.dividend_amount) if history.action == TransHistory.ACTION_DIVIDEND else ''
                                detail['comments'] = history.comments or ''
                                
                                # 设置历史快照字段
                                detail['price'] = float(history.avg_cost)
                                detail['qty'] = history.position_qty
                                detail['amount'] = float(history.avg_cost) * history.position_qty
                                detail['profit'] = float(history.profit)
                                detail['target_price'] = float(history.target_price)
                                detail['stop_price'] = float(history.stop_price)
                                detail['win_ratio'] = history.win_ratio
                                detail['risk_amount'] = float(history.risk_amount)
                                
                                # 判断是否是清仓交易（交易后持仓为0，包括多头卖出清仓和空头买入清仓）
                                is_close_trade = (history.position_qty == 0 and history.action in (TransHistory.ACTION_SELL, TransHistory.ACTION_BUY))
                                detail['is_close_trade'] = is_close_trade
                                
                                # 如果是清仓交易，设置清仓特有字段
                                if is_close_trade:
                                    from .review import calc_weighted_return
                                    detail['deal_price'] = float(history.price)
                                    detail['deal_qty'] = history.qty
                                    detail['total_profit'] = float(history.profit)
                                    detail['profit_ratio'] = float(calc_weighted_return(history.order))
                        # focus 类型历史
                        else:
                            from ..models import FocusHistory
                            history = FocusHistory.objects.filter(id=pilot_list[pilot_idx][0]).first()
                            if history:
                                if history.action == FocusHistory.ACTION_CREATE:
                                    pilot_action = '创建关注'
                                elif history.action == FocusHistory.ACTION_CLOSE:
                                    pilot_action = '关闭关注'
                                elif history.action == FocusHistory.ACTION_DEAL:
                                    pilot_action = '已交易'
                                else:
                                    # 编辑操作：对比上一条同类型记录，找出修改的字段
                                    changes = []
                                    if pilot_idx > 0:
                                        # 找上一条同类型记录
                                        for prev_i in range(pilot_idx - 1, -1, -1):
                                            if len(pilot_list[prev_i]) > 2 and pilot_list[prev_i][2] == 'focus':
                                                prev_history = FocusHistory.objects.filter(id=pilot_list[prev_i][0]).first()
                                                if prev_history:
                                                    if history.intent != prev_history.intent:
                                                        changes.append('交易方向')
                                                    if history.plan_price != prev_history.plan_price:
                                                        changes.append('计划报价')
                                                    if history.plan_qty != prev_history.plan_qty:
                                                        changes.append('计划数量')
                                                    if history.target_price != prev_history.target_price:
                                                        changes.append('目标价格')
                                                    if history.stop_price != prev_history.stop_price:
                                                        changes.append('止损价格')
                                                break
                                    pilot_action = format_changes(changes, default='调整计划')
                                pilot_qty = ''
                                pilot_price = ''
                                detail['comments'] = history.comments or ''
                    detail['pilot_date'] = pilot_date
                    detail['pilot_action'] = pilot_action
                    detail['pilot_qty'] = pilot_qty
                    detail['pilot_price'] = pilot_price
                    detail['pilot_dividend_amount'] = pilot_dividend_amount
                    detail['pilot_idx'] = pilot_idx
                    detail['pilot_total'] = len(pilot_list) if pilot_list else 0
                    # 历史模式下附加 history_id 和 history_type
                    if not is_summary and pilot_list and 0 <= pilot_idx < len(pilot_list):
                        detail['history_id'] = pilot_list[pilot_idx][0]
                        detail['history_type'] = pilot_list[pilot_idx][2] if len(pilot_list[pilot_idx]) > 2 else 'trans'
                    # 汇总模式下，focus/view 返回汇总备注
                    if is_summary and param_site in ['/focus/view', '/review/focus/view']:
                        from ..models import FocusStock
                        focus_inst = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
                        if focus_inst:
                            comments_list = []
                            for h in focus_inst.histories.all().order_by('-id'):
                                if h.comments:
                                    date_str = h.edit_date.strftime('%Y-%m-%d') if h.edit_date else ''
                                    comments_list.append(f'{date_str}：{h.comments}')
                            detail['comments'] = '\n'.join(comments_list)
                return JsonResponse(detail)
            else:
                return JsonResponse({'error': '股票不存在'}, status=404)
        else:
            return JsonResponse({'error': '无可用股票'}, status=400)
    else:
        return JsonResponse({'error': f'未知功能: {param_func}'}, status=400)

    view_mode = utils.get_cache(request.session, 'view', 'kline')
    # 更新当前股票 code，供返回列表时页码定位（loadChartPage 是 AJAX，不经过 filter_view）
    utils.set_view_current_code(request.session, param_code)

    # 导航缓存失效（如 hide 后被删除）时，重新构建，避免底部导航栏丢失
    navi_data = utils.get_cache(request.session, f'{param_site}-navi-data', {})
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

    view = utils.get_cache(session, 'view', 'kline')
    if (view == 'kline'): 
        kline.set_kline_params(session, 'deci', deci)
        kline_init = kline.get_kline_params(session)
        trend_init = {}
    else:
        kline_init = {}
        trend_init = trend_params_map[site] if site in trend_params_map else TREND_PARAMS_INIT

    navi_data = utils.get_cache(session, f'{site}-navi-data', {})
    navi_init = get_navi_params(session, site, navi_data)
    # review 页面始终强制汇总模式，避免缓存导致指示器位置错误
    if site.startswith('/review/'):
        navi_init['pilotIndex'] = -1
    mark_init = get_mark_config(session, site, navi_data)

    return {
        'kline': kline_init,
        'trend': trend_init,
        'navi': navi_init,
        'mark': mark_init,
        'deci': deci,
        'interval': quote.get_quote_interval_ms()
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
                task_id = utils.get_cache(session, 'filter-current-task')
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


def set_navi_data(session, site, code, market, function, action, navi_id=None):
    show_pilot_limited = ['/focus/view', '/trans/view', '/review/focus/view', '/review/trans/view']    
    navi_data = utils.get_cache(session, f'{site}-navi-data', {})
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
            navi_id = navi_list[navi_idx][0] if navi_list else None
            pilot_list = get_pilot_list(site, code, market, navi_id)
            pilot_total = len(pilot_list)
            if site in ['/trans/view', '/review/trans/view']:
                if site.startswith('/review/'):
                    # review 页面刷新后始终进入汇总模式
                    pilot_idx = -1
                else:
                    pilot_idx = utils.get_cache(session, f'{site}-pilot', -1)
                if pilot_idx >= pilot_total:
                    pilot_idx = pilot_total - 1
                if pilot_idx < -1:
                    pilot_idx = -1
            else:
                pilot_idx = utils.get_cache(session, f'{site}-pilot', pilot_total - 1)
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
            # 查找当前股票的 navi_id
            current_navi_id = None
            for item in navi_list:
                if item[1] == code and item[2] == market:
                    current_navi_id = item[0]
                    break
            pilot_list = get_pilot_list(site, code, market, current_navi_id)
            pilot_total = len(pilot_list)
            if site in ['/trans/view', '/review/trans/view', '/focus/view', '/review/focus/view']:
                # trans/view 和 focus/view: pilot_idx=-1 表示汇总
                if site.startswith('/review/'):
                    # review 页面刷新后始终进入汇总模式
                    pilot_idx = -1
                else:
                    pilot_idx = utils.get_cache(session, f'{site}-pilot', -1)
                if pilot_idx >= pilot_total:
                    pilot_idx = pilot_total - 1
                if pilot_idx < -1:
                    pilot_idx = -1
            else:
                pilot_idx = utils.get_cache(session, f'{site}-pilot', pilot_total - 1)
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
    # 查找当前索引（匹配 navi_id、code 和 market，navi_list 格式为 (id, code, market)）
    try:
        navi_idx = None
        for i, item in enumerate(navi_list):
            # 如果有 navi_id，优先匹配 navi_id；否则只匹配 code 和 market
            if navi_id:
                if item[0] == int(navi_id) and item[1] == code and item[2] == market:
                    navi_idx = i
                    break
            else:
                if item[1] == code and item[2] == market:
                    navi_idx = i
                    break
        if navi_idx is None:
            raise ValueError
        navi_idx = navi_idx + shift
    except ValueError:
        # 股票不在导航列表中（已被 hide 或不存在）：删除旧缓存，确保 get_page_config 读到空
        # 否则旧缓存（如下一只股票的导航数据）会导致 showNavi=true 但导航列表不含当前股票，页面状态异常
        utils.delete_cache(session, f'{site}-navi-data')
        return {}
    navi_id, code, market = navi_list[navi_idx]

    # 切换股票后，重新获取新股票的 pilot_list 并重置为汇总模式
    if function == 'navi' and showPilot:
        pilot_list = get_pilot_list(site, code, market, navi_id)
        pilot_total = len(pilot_list)
        pilot_idx = -1
        utils.set_cache(session, f'{site}-pilot', -1)

    if showPilot and function == 'pilot':
        if pilot_total <= 0:
            pilot_idx = -1
        elif site in ['/trans/view', '/review/trans/view', '/focus/view', '/review/focus/view']:
            # 先修正当前 pilot_idx 边界，防止快速点击导致越界
            if pilot_idx < -1:
                pilot_idx = -1
            if pilot_idx >= pilot_total:
                pilot_idx = pilot_total - 1
            # trans/view 和 focus/view: up=prev(更早), down=next(更晚/汇总)
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
            # 先修正边界
            if pilot_idx < 0:
                pilot_idx = 0
            if pilot_idx >= pilot_total:
                pilot_idx = pilot_total - 1
            shift = 1 if action == 'next' else -1 if action == 'prev' else 0
            pilot_idx += shift
            # 计算后再次修正边界
            if pilot_idx < 0:
                pilot_idx = 0
            if pilot_idx >= pilot_total:
                pilot_idx = pilot_total - 1

    # pilot 按钮可用性
    if site in ['/trans/view', '/review/trans/view', '/focus/view', '/review/focus/view']:
        # up(prev): 汇总时 pilot_total>1 可用；历史时 i>0 可用
        pilotPrev = (pilot_idx == -1 and pilot_total > 1) or (pilot_idx > 0)
        # down(next): 汇总时禁用；历史时始终可用（最近一笔点down回汇总）
        pilotNext = (pilot_idx >= 0)
    else:
        pilotPrev = pilot_idx > 0
        pilotNext = pilot_idx < pilot_total - 1

    # kline-deadline: 历史模式下设为该笔日期，汇总模式下删除
    if pilot_idx >= 0 and pilot_list and 0 <= pilot_idx < len(pilot_list):
        pilot_id = pilot_list[pilot_idx][0]
        pilot_date = pilot_list[pilot_idx][1]
        deadline = pilot_date.strftime('%Y%m%d')
        utils.set_cache(
            session,
            'kline-deadline',
            {'site_code_market':(site, code, market), 'deadline': deadline},
            600
        )
    else:
        utils.delete_cache(session, 'kline-deadline')

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

    utils.set_cache(session, f'{site}-navi-data', navi_data, 600)

    # 同步保存 pilot_idx 到 trans_view 使用的 session key
    if showPilot:
        utils.set_cache(session, f'{site}-pilot', pilot_idx, 600)

    navi_data = utils.get_cache(session, f'{site}-navi-data', {})
    return navi_data


def get_navi_list(site, session=None):
    if site == '/focus/view':
        qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).order_by('sort_order')
        navi_list = list(qs.values_list('id', 'code', 'market')) 

    elif site == '/trans/view':
        qs = TransOrder.objects.filter(status=TransOrder.STATUS_OPEN).order_by('-created_at')
        navi_list = list(qs.values_list('id', 'code', 'market')) 
    elif site == '/sector/view':
        # 优先使用板块清单传入的自定义 navi 列表（标记筛选后）；否则用全部板块
        custom = utils.get_cache(session, 'sector-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            qs = SectorList.objects.all()
            navi_list = list(qs.values_list('id', 'code', 'market'))
    elif site == '/filter/view':
        # 优先使用对比页传入的自定义 navi 列表；否则用当前 task 全部结果
        custom = utils.get_cache(session, 'filter-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            task_id = utils.get_cache(session, 'filter-current-task') if session else None
            qs = FilterResult.objects.filter(task_id=task_id).exclude(hide='1').order_by('sort_order', 'id')
            navi_list = list(qs.values_list('id', 'code', 'market'))
    elif site == '/stocks/view':
        # 优先使用板块股票清单传入的自定义 navi 列表；否则用全部未 hide 股票
        custom = utils.get_cache(session, 'stocks-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            qs = StockList.objects.exclude(hide='1').order_by('code')
            navi_list = list(qs.values_list('id', 'code', 'market'))
    elif site == '/refer/view':
        # 优先使用筛选对比页传入的自定义 navi 列表；否则用全部未 hide 股票
        custom = utils.get_cache(session, 'refer-view-custom-navi') if session else None
        if custom:
            navi_list = [tuple(x) for x in custom]
        else:
            qs = StockList.objects.exclude(hide='1').order_by('code')
            navi_list = list(qs.values_list('id', 'code', 'market'))
    elif site == '/review/focus/view':
        # 从 ReviewList 中查询 focus 类型的记录（与复盘列表页面一致，不去重）
        qs = ReviewList.objects.filter(
            review_type=ReviewList.TYPE_FOCUS
        ).order_by('-close_date', '-id')
        navi_list = [(r.id, r.code, r.market) for r in qs]
    elif site == '/review/trans/view':
        # 从 ReviewList 中查询 trans 类型的记录（与复盘列表页面一致，不去重）
        qs = ReviewList.objects.filter(
            review_type=ReviewList.TYPE_TRANS
        ).order_by('-close_date', '-id')
        navi_list = [(r.id, r.code, r.market) for r in qs]
    else:
        navi_list = []

    return navi_list


def get_pilot_list(site, code, market, navi_id=None):
    if site == '/focus/view':
        focus = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
        pilot_list = [(h.id, h.edit_date, 'focus') for h in focus.histories.all().order_by('id')] if focus else []
    elif site == '/trans/view':
        order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
        pilot_list = [(h.id, h.date, 'trans') for h in order.histories.all().order_by('id')] if order else []
    elif site == '/review/focus/view':
        # 根据 navi_id 查找对应的 ReviewList 记录
        if navi_id:
            review = ReviewList.objects.filter(id=navi_id, review_type=ReviewList.TYPE_FOCUS).first()
            if review and review.focus_stock:
                focus = review.focus_stock
            else:
                focus = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_CLOSED).order_by('-close_date').first()
        else:
            focus = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_CLOSED).order_by('-close_date').first()
        pilot_list = [(h.id, h.edit_date, 'focus') for h in focus.histories.all().order_by('id')] if focus else []
    elif site == '/review/trans/view':
        # 复盘交易页面：关注历史始终排在交易历史前面，内部按数据库顺序排序
        # 根据 navi_id 查找对应的 ReviewList 记录
        if navi_id:
            review = ReviewList.objects.filter(id=navi_id, review_type=ReviewList.TYPE_TRANS).first()
            if review and review.trans_order:
                order = review.trans_order
            else:
                order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_CLOSED).order_by('-close_date').first()
        else:
            order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_CLOSED).order_by('-close_date').first()
        pilot_list = []
        if order:
            # 先放关注历史（按数据库顺序）
            if order.focus_id:
                focus = order.focus
                if focus:
                    focus_histories = list(focus.histories.all().order_by('id'))
                    for h in focus_histories:
                        pilot_list.append((h.id, h.edit_date, 'focus'))
            # 再放交易历史（按数据库顺序）
            trans_histories = list(order.histories.all().order_by('id'))
            for h in trans_histories:
                pilot_list.append((h.id, h.date, 'trans'))
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


def _get_stock_detail(site, code, market, history_id=None, history_type=None, navi_id=None):
    if site == '/focus/view':
        focus_inst = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
        if not focus_inst:
            return {}
        history = None
        if history_id:
            history = focus_inst.histories.filter(id=history_id).first()
        return focus.get_focus_data_dict(focus_inst, history)
    elif site == '/review/focus/view':
        # 根据 navi_id 查找对应的 ReviewList 记录
        if navi_id:
            review = ReviewList.objects.filter(id=navi_id, review_type=ReviewList.TYPE_FOCUS).first()
            if review and review.focus_stock:
                focus_inst = review.focus_stock
            else:
                focus_inst = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_CLOSED).order_by('-close_date').first()
        else:
            focus_inst = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_CLOSED).order_by('-close_date').first()
        if not focus_inst:
            return {}
        history = None
        if history_id:
            history = focus_inst.histories.filter(id=history_id).first()
        return focus.get_focus_data_dict(focus_inst, history)

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
    elif site == '/trans/view':
        from .trans import TransOrder, get_trans_data_dict
        order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
        if not order:
            return {}
        history = None
        if history_id:
            history = order.histories.filter(id=history_id).first()
        return get_trans_data_dict(order, history)
    elif site == '/review/trans/view':
        from .trans import TransOrder, get_trans_data_dict
        from .focus import get_focus_data_dict
        # 根据 navi_id 查找对应的 ReviewList 记录
        if navi_id:
            review = ReviewList.objects.filter(id=navi_id, review_type=ReviewList.TYPE_TRANS).first()
            if review and review.trans_order:
                order = review.trans_order
            else:
                order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_CLOSED).order_by('-close_date').first()
        else:
            order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_CLOSED).order_by('-close_date').first()
        if not order:
            return {}
        # 如果是 focus 类型历史，使用 focus 数据
        if history_type == 'focus' and order.focus_id:
            focus_inst = order.focus
            if focus_inst:
                history = None
                if history_id:
                    history = focus_inst.histories.filter(id=history_id).first()
                return get_focus_data_dict(focus_inst, history)
        # 默认使用 trans 数据
        history = None
        if history_id:
            history = order.histories.filter(id=history_id).first()
        data = get_trans_data_dict(order, history)
        # 增加复盘特有字段（仅汇总模式需要，历史模式下这些字段会被隐藏）
        if history is None:
            from .review import calc_weighted_return
            last_history = order.histories.order_by('-id').first()
            data['open_date'] = order.open_date.strftime('%Y-%m-%d') if order.open_date else ''
            data['close_date'] = order.close_date.strftime('%Y-%m-%d') if order.close_date else ''
            data['total_profit'] = round(float(last_history.profit), 2) if last_history else 0
            data['profit_ratio'] = round(float(calc_weighted_return(order)), 2)
        return data
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
        all_closed = TransOrder.objects.filter(status=TransOrder.STATUS_CLOSED).order_by('close_date')
        stock_latest = {}
        for o in all_closed:
            if o.code not in stock_latest or o.close_date > stock_latest[o.code].close_date:
                stock_latest[o.code] = o
        unique_stocks = list(stock_latest.values())
        unique_stocks.sort(key=lambda x: x.close_date, reverse=True)
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
        orders = TransOrder.objects.filter(code=target, status=TransOrder.STATUS_CLOSED).order_by('close_date')
        round_num = len(orders)
        return JsonResponse({'code': target, 'url': f'/review/view/{target}/?round={round_num}'})
    elif site == '/review/focus/view':
        # 从 ReviewList 中查询 focus 类型的记录
        qs = ReviewList.objects.filter(
            review_type=ReviewList.TYPE_FOCUS
        ).order_by('-close_date', '-id')
        codes = []
        for r in qs:
            if r.code not in codes:
                codes.append(r.code)
        if not codes or current_code not in codes:
            return JsonResponse({'code': current_code, 'url': f'/review/focus/view/{current_code}/'})
        idx = codes.index(current_code)
        if direction == 'prev' and idx > 0:
            target = codes[idx - 1]
        elif direction == 'next' and idx < len(codes) - 1:
            target = codes[idx + 1]
        else:
            target = current_code
        return JsonResponse({'code': target, 'url': f'/review/focus/view/{target}/'})
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
