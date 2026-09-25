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
from .forms.forms import CAT_CHOICES, MARKET_CHOICES, INTENT_CHOICES, FocusStockForm
from . import cash, func, chart
from .models.models import CashConfig, StockList, FocusStock
from django.db import connection, transaction


# ===================== 关注清单 =====================
def focus_list(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的JSON'}, status=400)

        # 分页 / 每页数量（独立处理，可同时接收 page + per_page）
        if 'page' in data or 'per_page' in data:
            if 'page' in data:
                func.set_cache(request.session, 'focus-list-page', int(data['page']))
            if 'per_page' in data:
                func.set_page_size(request.session, data['per_page'])
            return JsonResponse({'status': 'success'})

        if data.get('action') == 'sort':
            ordered_codes = data.get('codes', [])
            for i, c in enumerate(ordered_codes):
                # 排序从 1 开始
                FocusStock.objects.filter(code=c[0], market=c[1]).update(sort_order=i+1)
            return JsonResponse({'status': 'success'})

        # 股价刷新：只查询当前页的股票（前端传来 codes，格式为 "code.market"）
        if 'codes' in data:
            result = []
            for code_market in data['codes']:
                parts = code_market.split('.')
                if len(parts) != 2:
                    continue
                code, market = parts
                fs = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
                if fs:
                    deci = 3 if fs.cat in ('fund', 'bond') else 2
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

    # 统一分页
    pg = func.paginate_queryset(request, focus_qs, 'focus-list-page')

    for fs in pg['items']:
        deci = 3 if fs.cat in ('fund', 'bond') else 2
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
    func.set_view_back(request.session, '/focus/list')
    return render(request, 'focus-list.html', {
        'list': items,
        'interval': quote.QUOTE_REQUEST_INTERVAL,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
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
                with transaction.atomic():
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
        'cash': CashConfig.get_config().cash,
        'available': CashConfig.get_config().allowance - CashConfig.get_config().risk,  
        # 需转换为 JSON 字符串
        'chart': json.dumps(chart_init)   
    })


def focus_view(request, market, code):
    site = '/focus/view'
    focus = get_object_or_404(FocusStock, code=code, market=market, status=FocusStock.STATUS_WATCHING)

    if request.method == 'POST':
        form = FocusStockForm(request.POST, instance=focus, view_mode=True)
        
        if form.is_valid():
            with transaction.atomic():
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

        histories = focus.histories.all().order_by('edit_date') if focus else None
        pilot_idx = navi_data.get('navi_params', {}).get('pilotIndex', 0)
        pilot_history = histories[pilot_idx] if histories and pilot_idx < len(histories) else None
        is_latest = (not histories) or (pilot_idx == len(histories) - 1)

        initial_data = get_focus_data_dict(focus, pilot_history)

        # 因为表单是 ModelForm，同时传入 instance 和 initial，initial 会覆盖显示值
        form = FocusStockForm(instance=focus, initial=initial_data, view_mode=True)
        view_mode = func.get_cache(request.session, 'view', 'kline')

        chart_init = {
            'site': site,
            'code': code,
            'market': market,
            'name': focus.name,
            'cat': focus.cat,
            'view': view_mode,
            'backUrl': func.get_view_back(request.session) or '/focus/list',
        }
        
        return render(request, 'focus-view.html', {
            'form': form,
            'chart': json.dumps(chart_init),
            'edit_mode': False,
            'is_latest': is_latest,
            'cash': CashConfig.get_config().cash,
            'available': CashConfig.get_config().allowance - CashConfig.get_config().risk,
        })


@require_http_methods(["POST"])
def focus_close(request, market, code):
    """
    关闭关注股票（标记为已关闭）
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '无效的JSON'}, status=400)
    try:
        focus = get_object_or_404(FocusStock, code=code, market=market, status=FocusStock.STATUS_WATCHING)
        
        close_date_str = data.get('close_date')
        if close_date_str:
            focus.close_date = datetime.datetime.strptime(close_date_str, "%Y-%m-%d").date()
        else:
            focus.close_date = timezone.now().date()

        focus.status = FocusStock.STATUS_CLOSED
        focus.close_reason = data.get('reason', FocusStock.CLOSE_REASON_MANUAL)
        focus.comments = data.get('comments', None)
        focus.save()
        focus.save_history(action='close')
        func.delete_cache(request.session, '/focus/view-navi-data')
        print(focus.close_date)
        return JsonResponse({'status': 'success', 'message': '已关闭'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message':  str(e)})


def get_focus_data_dict(focus, history=None):
    """
    将 FocusStock 实例（及可选的历史记录）转换为字典，
    所有价格字段按类别格式化为指定位数的字符串。
    """
    if not focus:
        return {}

    deci = 3 if focus.cat in ('fund', 'bond') else 2
    # 优先使用 history，否则使用 focus
    target = history if history else focus

    def fmt_price(value):
        """将 Decimal 或数字格式化为指定位数的字符串，若为空则返回空字符串"""
        if value is None:
            return ''
        return format(Decimal(str(value)), f'.{deci}f')

    return {
        'code': focus.code,
        'market': focus.market,
        'name': focus.name,
        'cat': focus.cat,
        'focus_date': target.edit_date.strftime('%Y-%m-%d') if history else focus.focus_date.strftime('%Y-%m-%d'),
        'plan_price': fmt_price(target.plan_price),
        'plan_qty': target.plan_qty,
        'target_price': fmt_price(target.target_price),
        'stop_price': fmt_price(target.stop_price),
        'allowed_qty': focus.allowed_qty,
        'win_ratio': target.win_ratio,
        'comments': target.comments,
        'intent': target.intent if history else focus.intent,
        'market_display': dict(MARKET_CHOICES).get(focus.market, focus.market),
        'cat_display': dict(CAT_CHOICES).get(focus.cat, focus.cat),
        'intent_display': dict(INTENT_CHOICES).get(target.intent if history else focus.intent, '')
    }


