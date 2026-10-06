import json
import datetime
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from ..fetch import quote
from ..forms import CAT_CHOICES, MARKET_CHOICES, INTENT_CHOICES, FocusStockForm
from . import chart
from .. import utils
from ..models import CashConfig, FocusStock, FocusHistory, ReviewList
from django.db import transaction


# ===================== 关注清单 =====================
def focus_list(request):
    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err

        # 分页 / 每页数量（独立处理，可同时接收 page + per_page）
        if 'page' in data or 'per_page' in data:
            if 'page' in data:
                utils.set_cache(request.session, 'focus-list-page', int(data['page']))
            if 'per_page' in data:
                utils.set_page_size(request.session, data['per_page'])
            return JsonResponse({'status': 'success'})

        if data.get('action') == 'sort':
            ordered_codes = data.get('codes', [])
            for i, c in enumerate(ordered_codes):
                # 排序从 1 开始
                FocusStock.objects.filter(code=c[0], market=c[1]).update(sort_order=i+1)
            return JsonResponse({'status': 'success'})

        # 股价刷新：只查询当前页的股票（前端传来 codes，格式为 "code.market"）
        if 'codes' in data:
            result = utils.refresh_prices(
                data['codes'], FocusStock, 'status', FocusStock.STATUS_WATCHING)
            return JsonResponse(result, safe=False, json_dumps_params={'ensure_ascii': False})

    items = []
    # models 自带 sort_order 排序，因此不需要进行排序
    focus_qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING)

    # 统一分页
    pg = utils.paginate_queryset(request, focus_qs, 'focus-list-page')

    for fs in pg['items']:
        deci = utils.price_places(fs.cat)
        items.append({
            'code': fs.code,
            'market': fs.market,
            'name': fs.name,
            'plan_price': round(fs.plan_price, deci),
            'win_ratio': fs.win_ratio,
            'close': '--',
            'change': '--',
            'deci': deci
        })
    utils.set_view_back(request.session, '/focus/list')
    return render(request, 'focus-list.html', {
        'list': items,
        'interval': quote.get_quote_interval_ms(),
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
                    focus.intent = form.cleaned_data['intent_choice']
                    focus.created_at = focus.focus_date
                    focus.updated_at = focus.focus_date
                    focus.code = code
                    focus.market = market
                    focus.cat = cat
                    focus.win_ratio = utils.calc_win_ratio(focus.plan_price, focus.target_price, focus.stop_price, focus.intent)
                    focus.allowed_qty = utils.calc_allowed_qty(focus.plan_price, focus.stop_price, focus.intent)
                    max_sort = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).count()
                    focus.sort_order = max_sort
                    focus.save()
                    focus.save_history(action='create', comments=form.cleaned_data.get('comments', ''))
                return redirect('focus_view', market=focus.market, code=focus.code)
    else:
        initial = {}
        form = FocusStockForm(initial=initial)
    
    chart_init = utils.build_chart_init(site, code, market, name, cat)

    return render(request, 'focus-plus.html', {
        'form': form, 
        'cash': CashConfig.get_config().cash,
        'available': CashConfig.get_config().allowance - CashConfig.get_config().risk,  
        # 需转换为 JSON 字符串
        'chart': json.dumps(chart_init)   
    })


def _apply_focus_edit(form):
    """
    保存关注编辑的统一逻辑：设置 intent/win_ratio/allowed_qty/updated_at 并写编辑历史。
    必须在调用方的 transaction.atomic() 内使用，返回保存后的 focus 实例。
    """
    updated = form.save(commit=False)
    updated.intent = form.cleaned_data['intent_choice']
    updated.win_ratio = utils.calc_win_ratio(
        updated.plan_price, updated.target_price, updated.stop_price, updated.intent)
    updated.allowed_qty = utils.calc_allowed_qty(
        updated.plan_price, updated.stop_price, updated.intent)
    updated.updated_at = updated.focus_date
    updated.save()
    updated.save_history(action='edit',
                         comments=form.cleaned_data.get('comments', ''))
    return updated


def focus_view(request, market, code):
    site = '/focus/view'
    focus = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
    if not focus:
        return redirect('focus_list')

    if request.method == 'POST':
        form = FocusStockForm(request.POST, instance=focus, view_mode=True)

        if form.is_valid():
            with transaction.atomic():
                _apply_focus_edit(form)
            utils.delete_cache(request.session, f'{site}-navi-data')

        return redirect('focus_view', market=market, code=code)
    else:
        # 历史记录（按数据库顺序排序）
        histories = list(focus.histories.all().order_by('id'))
        # 进入页面时强制重置为汇总模式（pilot_idx=-1）
        utils.set_cache(request.session, f'{site}-pilot', -1)
        utils.delete_cache(request.session, f'{site}-navi-data')
        is_summary = True

        chart.set_navi_data(request.session, site, code, market, 'focus', 'init')

        # 汇总模式：备注汇总所有历史记录的备注（按近期到远期顺序）
        comments_list = []
        for h in reversed(histories):
            if h.comments:
                date_str = h.edit_date.strftime('%Y-%m-%d') if h.edit_date else ''
                comments_list.append(f'{date_str}：{h.comments}')
        comments_text = '\n'.join(comments_list)

        initial_data = get_focus_data_dict(focus, None)
        initial_data['comments'] = comments_text

        # 因为表单是 ModelForm，同时传入 instance 和 initial，initial 会覆盖显示值
        form = FocusStockForm(instance=focus, initial=initial_data, view_mode=True)

        chart_init = utils.build_chart_init(
            site, code, market, focus.name, focus.cat,
            back_url=utils.get_view_back(request.session) or '/focus/list')

        return render(request, 'focus-view.html', {
            'form': form,
            'chart': json.dumps(chart_init),
            'is_summary': is_summary,
            'cash': CashConfig.get_config().cash,
            'available': CashConfig.get_config().allowance - CashConfig.get_config().risk,
        })


def focus_edit(request, market, code):
    """编辑关注股票页面"""
    site = '/focus/edit'
    focus = FocusStock.objects.filter(code=code, market=market, status=FocusStock.STATUS_WATCHING).first()
    if not focus:
        return redirect('focus_list')

    if request.method == 'POST':
        form = FocusStockForm(request.POST, instance=focus)
        if form.is_valid():
            with transaction.atomic():
                _apply_focus_edit(form)
            utils.delete_cache(request.session, '/focus/view-navi-data')
            return redirect('focus_view', market=market, code=code)
    else:
        # 自动填入数据库数据，更新日期默认为今天
        initial = {
            'focus_date': timezone.now().date(),
            'plan_price': focus.plan_price,
            'plan_qty': focus.plan_qty,
            'target_price': focus.target_price,
            'stop_price': focus.stop_price,
            'win_ratio': focus.win_ratio,
            'allowed_qty': focus.allowed_qty,
            'comments': '',
            'intent_choice': focus.intent,
        }
        form = FocusStockForm(instance=focus, initial=initial)

    cat_display = dict(CAT_CHOICES).get(focus.cat, focus.cat)
    market_display = dict(MARKET_CHOICES).get(focus.market, focus.market)
    intent_display = dict(INTENT_CHOICES).get(focus.intent, focus.intent)

    chart_init = utils.build_chart_init(
        site, code, market, focus.name, focus.cat,
        back_url=f'/focus/view/{market}/{code}')

    return render(request, 'focus-edit.html', {
        'form': form,
        'focus': focus,
        'initial': initial,
        'stock_code': focus.code,
        'stock_name': focus.name,
        'cat_display': cat_display,
        'market_display': market_display,
        'intent_display': intent_display,
        'cash': CashConfig.get_config().cash,
        'available': CashConfig.get_config().allowance - CashConfig.get_config().risk,
        'chart': json.dumps(chart_init),
    })


@require_http_methods(["POST"])
def focus_close(request, market, code):
    """
    关闭关注股票（标记为已关闭）
    """
    data, err = utils.parse_json_body(request)
    if err is not None:
        return err
    try:
        focus = get_object_or_404(FocusStock, code=code, market=market, status=FocusStock.STATUS_WATCHING)
        
        close_date_str = data.get('close_date')
        if close_date_str:
            focus.close_date = datetime.datetime.strptime(close_date_str, "%Y-%m-%d").date()
        else:
            focus.close_date = timezone.now().date()

        focus.status = FocusStock.STATUS_CLOSED
        focus.close_reason = data.get('reason', FocusStock.CLOSE_REASON_MANUAL)
        close_comments = data.get('comments', '') or ''
        focus.save()
        focus.save_history(action='close', comments=close_comments)
        utils.delete_cache(request.session, '/focus/view-navi-data')

        # 创建复盘记录
        ReviewList.objects.update_or_create(
            focus_stock=focus,
            defaults={
                'review_type': ReviewList.TYPE_FOCUS,
                'code': focus.code,
                'market': focus.market,
                'name': focus.name,
                'cat': focus.cat,
                'open_date': focus.focus_date,
                'close_date': focus.close_date,
                'plan_price': focus.plan_price,
                'target_price': focus.target_price,
            }
        )

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

    deci = utils.price_places(focus.cat)
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
        'comments': target.comments if history else '',
        'intent': target.intent if history else focus.intent,
        'market_display': dict(MARKET_CHOICES).get(focus.market, focus.market),
        'cat_display': dict(CAT_CHOICES).get(focus.cat, focus.cat),
        'intent_display': dict(INTENT_CHOICES).get(target.intent if history else focus.intent, '')
    }


@require_http_methods(["POST"])
def focus_calc(request):
    """关注页面计算接口：允许数量、盈利机会"""
    data, err = utils.parse_json_body(request)
    if err is not None:
        return err

    intent = data.get('intent', 'B')
    plan_price = float(data.get('plan_price', 0) or 0)
    target_price = float(data.get('target_price', 0) or 0)
    stop_price = float(data.get('stop_price', 0) or 0)

    # 允许数量
    allowed_qty = utils.calc_allowed_qty(plan_price, stop_price, intent) if plan_price > 0 else 0

    # 盈利机会（0-99）
    win_ratio = utils.calc_win_ratio(plan_price, target_price, stop_price, intent)

    return JsonResponse({
        'allowed_qty': allowed_qty,
        'win_ratio': win_ratio,
    })


@require_http_methods(["POST"])
def save_history_comment(request):
    """保存关注历史记录的备注"""
    return utils.save_history_comment(request, FocusHistory)


