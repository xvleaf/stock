"""
交易页面：买入/卖出填报
"""
import json
import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction

from .models.models import (
    CashConfig, CashHistory, FocusStock, TransOrder, TransHistory,
)
from .forms.forms import CAT_CHOICES, MARKET_CHOICES
from . import cash as cash_utils
from . import func
from . import chart
from .fetch import quote


def _q(value, places='0.01'):
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def trans_deal(request, market, code):
    """交易页面：买入/卖出填报"""
    site = '/trans/deal'

    # 查找持仓中的交易订单
    order = TransOrder.objects.filter(
        code=code, market=market, status=TransOrder.STATUS_OPEN
    ).first()

    # 查找关注中的股票
    focus = FocusStock.objects.filter(
        code=code, market=market, status=FocusStock.STATUS_WATCHING
    ).first()

    # 都没找到 → 重定向到关注列表
    if not order and not focus:
        return redirect('focus_list')

    # 确定股票基本信息
    if order:
        stock_name = order.name
        stock_cat = order.cat
        stock_market = order.market
    else:
        stock_name = focus.name
        stock_cat = focus.cat
        stock_market = focus.market

    if request.method == 'POST':
        return _handle_trans_post(request, market, code, order, focus, stock_name, stock_cat)

    # GET：准备页面数据
    config = CashConfig.get_config()

    # 初始表单数据
    if order:
        # 持仓中：默认卖出
        initial = {
            'intent': 'S',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'price': float(order.avg_cost) if order.avg_cost > 0 else 0,
            'qty': order.position_qty,
            'target_price': float(order.target_price) if order.target_price else 0,
            'stop_price': float(order.stop_price) if order.stop_price else 0,
            'win_ratio': 0,
            'comments': '',
        }
        avg_cost = float(order.avg_cost)
        position_qty = order.position_qty
    else:
        # 关注中：默认买入
        initial = {
            'intent': 'B',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'price': float(focus.plan_price) if focus.plan_price else 0,
            'qty': focus.plan_qty,
            'target_price': float(focus.target_price) if focus.target_price else 0,
            'stop_price': float(focus.stop_price) if focus.stop_price else 0,
            'win_ratio': float(focus.win_ratio) if focus.win_ratio else 0,
            'comments': '',
        }
        avg_cost = 0
        position_qty = 0

    # 中文显示映射
    CAT_DISPLAY = {'stock': '股票', 'index': '指数', 'fund': '基金', 'bond': '债券'}
    MARKET_DISPLAY = {'SH': '上海', 'SZ': '深圳', 'BJ': '北京'}
    cat_display = CAT_DISPLAY.get(stock_cat, stock_cat)
    market_display = MARKET_DISPLAY.get(stock_market, stock_market)

    # 图表配置
    view_mode = func.get_cache(request.session, 'view', 'kline')
    chart_init = {
        'site': site,
        'code': code,
        'market': market,
        'name': stock_name,
        'cat': stock_cat,
        'view': view_mode,
    }

    return render(request, 'trans-deal.html', {
        'order': order,
        'focus': focus,
        'initial': initial,
        'avg_cost': avg_cost,
        'position_qty': position_qty,
        'cash': float(config.cash),
        'available': float(config.allowance - config.risk),
        'current_risk': float(config.risk),
        'commission_ratio': float(config.commission_ratio),
        'commission_min': float(config.commission_min),
        'stamp_sell_ratio': float(config.stamp_sell_ratio),
        'chart': json.dumps(chart_init),
        'stock_name': stock_name,
        'stock_cat': stock_cat,
        'stock_market': stock_market,
        'stock_code': code,
        'cat_display': cat_display,
        'market_display': market_display,
    })


def _handle_trans_post(request, market, code, order, focus, stock_name, stock_cat):
    """处理买入/卖出提交"""
    try:
        params = request.POST
        intent = params.get('intent', 'B')
        date_str = params.get('date', '')
        price = Decimal(str(params.get('price', 0)))
        qty = int(params.get('qty', 0))
        target_price = Decimal(str(params.get('target_price', 0) or 0))
        stop_price = Decimal(str(params.get('stop_price', 0) or 0))
        win_ratio = Decimal(str(params.get('win_ratio', 0) or 0))
        comments = params.get('comments', '')
    except (ValueError, TypeError):
        return JsonResponse({'status': 'error', 'error': '参数格式错误'})

    try:
        deal_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        deal_date = timezone.now().date()

    if qty <= 0 or price <= 0:
        return JsonResponse({'status': 'error', 'error': '价格和数量必须大于0'})

    config = CashConfig.get_config()
    amount = _q(price * qty)
    # 优先使用前端传入的费用（用户可手动修改），未传则自动计算
    fee_str = params.get('fee', '').strip()
    if fee_str:
        fee = _q(fee_str)
    else:
        fee_info = cash_utils.calc_fee(amount, intent, config)
        fee = fee_info['total']

    with transaction.atomic():
        if intent == 'B':
            # 买入
            total_cost = amount + fee
            if total_cost > config.cash:
                return JsonResponse({'status': 'error', 'error': f'现金不足，需要 {total_cost}，当前 {config.cash}'})

            # 创建或获取交易订单
            if not order:
                order = TransOrder(
                    focus=focus,
                    code=code,
                    name=stock_name,
                    market=market,
                    cat=stock_cat,
                    target_price=target_price,
                    stop_price=stop_price,
                )
                order.save()
            else:
                order.target_price = target_price
                order.stop_price = stop_price

            # 记录卖出前的 profit（用于计算本次收益）
            profit_before = order.profit if order.pk else Decimal('0')

            # 风险资金（买入）
            risk_amount = cash_utils.calc_risk_capital(price, stop_price, qty, 'B')

            # 创建成交明细
            deal = TransHistory.objects.create(
                order=order,
                action=TransHistory.ACTION_BUY,
                intent='B',
                date=deal_date,
                price=price,
                qty=qty,
                amount=amount,
                fee=fee,
                target_price=target_price,
                stop_price=stop_price,
                comments=comments,
            )

            # 重新计算订单所有汇总字段
            order.recalculate()

            # 本次收益 = recalculate后的profit - 之前的profit
            deal_profit = _q(order.profit - profit_before)

            # 更新风险资金（recalculate不计算risk_amount）
            order.risk_amount = _q(order.risk_amount + risk_amount)
            order.save()

            # 保存该笔交易后的持仓快照
            deal.profit = order.profit
            deal.win_ratio = cash_utils.calc_win_ratio(order.avg_cost, target_price, stop_price, 'B') if order.position_qty > 0 else 0
            deal.risk_amount = order.risk_amount
            deal.position_qty = order.position_qty
            deal.avg_cost = order.avg_cost
            deal.save(update_fields=['profit', 'win_ratio', 'risk_amount', 'position_qty', 'avg_cost'])
            if not order.open_date:
                order.open_date = deal_date
            order.save()

            # 更新资金配置
            config.cash -= total_cost
            config.stock += amount
            config.total = config.cash + config.stock
            config.risk += risk_amount
            config.profit += deal_profit
            config.save()

            # 写入资金历史
            CashHistory.snapshot(
                event=CashHistory.EVENT_BUY,
                change=-total_cost,
                profit=deal_profit,
                remark=f'买入{stock_name}{qty}股',
                order=order,
                date=deal_date,
            )

            # 更新关注状态
            if focus and focus.status == FocusStock.STATUS_WATCHING:
                focus.status = FocusStock.STATUS_CLOSED
                focus.close_reason = FocusStock.CLOSE_REASON_BOUGHT
                focus.close_date = deal_date
                focus.save()

        else:
            # 卖出
            if not order:
                return JsonResponse({'status': 'error', 'error': '该股票无持仓，无法卖出'})

            if qty > order.position_qty:
                return JsonResponse({'status': 'error', 'error': f'卖出数量超过持仓量（{order.position_qty}股）'})

            total_income = amount - fee

            # 记录卖出前的 profit 和持仓成本（含手续费）
            profit_before = order.profit
            position_cost_before = order.position_cost

            # 按比例冲抵风险资金
            if order.position_qty > 0:
                risk_ratio = Decimal(qty) / Decimal(order.position_qty)
                risk_reduce = _q(order.risk_amount * risk_ratio)
            else:
                risk_reduce = Decimal('0')

            # 创建成交明细
            deal = TransHistory.objects.create(
                order=order,
                action=TransHistory.ACTION_SELL,
                intent='S',
                date=deal_date,
                price=price,
                qty=qty,
                amount=amount,
                fee=fee,
                target_price=order.target_price,
                stop_price=order.stop_price,
                comments=comments,
            )

            # 重新计算订单所有汇总字段
            order.recalculate()

            # 本次收益 = recalculate后的profit - 之前的profit
            deal_profit = _q(order.profit - profit_before)

            # 卖出部分成本 = 卖出前持仓成本 - 卖出后持仓成本
            sold_cost = _q(position_cost_before - order.position_cost)

            # 更新风险资金
            order.risk_amount = _q(order.risk_amount - risk_reduce)
            if order.risk_amount < 0:
                order.risk_amount = Decimal('0')
            if order.position_qty <= 0:
                order.risk_amount = Decimal('0')
            order.save()

            # 保存该笔交易后的持仓快照
            deal.profit = order.profit
            deal.win_ratio = cash_utils.calc_win_ratio(order.avg_cost, order.target_price, order.stop_price, 'S') if order.position_qty > 0 else 0
            deal.risk_amount = order.risk_amount
            deal.position_qty = order.position_qty
            deal.avg_cost = order.avg_cost
            deal.save(update_fields=['profit', 'win_ratio', 'risk_amount', 'position_qty', 'avg_cost'])

            # 更新资金配置
            config.cash += total_income
            config.stock -= sold_cost
            config.total = config.cash + config.stock
            config.risk -= risk_reduce
            if config.risk < 0:
                config.risk = Decimal('0')
            config.profit += deal_profit
            config.save()

            # 写入资金历史
            CashHistory.snapshot(
                event=CashHistory.EVENT_SELL,
                change=total_income,
                profit=deal_profit,
                remark=f'卖出{stock_name}{qty}股',
                order=order,
                date=deal_date,
            )

    return JsonResponse({'status': 'success', 'redirect': f'/trans/view/{market}/{code}'})


# ===================== 交易清单 =====================
def trans_list(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的JSON'}, status=400)

        if 'page' in data or 'per_page' in data:
            if 'page' in data:
                func.set_cache(request.session, 'trans-list-page', int(data['page']))
            if 'per_page' in data:
                func.set_page_size(request.session, data['per_page'])
            return JsonResponse({'status': 'success'})

        # 股价刷新：只查询当前页的股票
        if 'codes' in data:
            result = []
            for code_market in data['codes']:
                parts = code_market.split('.')
                if len(parts) != 2:
                    continue
                code, market = parts
                order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
                if order:
                    deci = 3 if order.cat in ('fund', 'bond') else 2
                    close, change = quote.get_last_price(order.tscode, deci)
                    result.append({
                        'code': order.code,
                        'market': order.market,
                        'close': close,
                        'change': change,
                        'deci': deci
                    })
            return JsonResponse(result, safe=False, json_dumps_params={'ensure_ascii': False})

    items = []
    qs = TransOrder.objects.filter(status=TransOrder.STATUS_OPEN).order_by('-created_at')
    pg = func.paginate_queryset(request, qs, 'trans-list-page')

    for o in pg['items']:
        deci = 3 if o.cat in ('fund', 'bond') else 2
        items.append({
            'code': o.code,
            'market': o.market,
            'name': o.name,
            'target_price': round(float(o.target_price), deci) if o.target_price else '--',
            'stop_price': round(float(o.stop_price), deci) if o.stop_price else '--',
            'close': '--',
            'change': '--',
            'deci': deci,
        })
    func.set_view_back(request.session, '/trans/list')
    return render(request, 'trans-list.html', {
        'list': items,
        'interval': quote.QUOTE_REQUEST_INTERVAL,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
    })


# ===================== 交易详情（只读） =====================
def get_trans_data_dict(order, history=None):
    """
    将 TransOrder 实例（及可选的历史记录）转换为字典，
    供 pilot 切换时 AJAX 局部更新使用。
    """
    if not order:
        return {}

    deci = 3 if order.cat in ('fund', 'bond') else 2
    cat_display = dict(CAT_CHOICES).get(order.cat, order.cat)
    market_display = dict(MARKET_CHOICES).get(order.market, order.market)

    if history is None:
        # 当前持仓汇总
        # 收集所有历史记录中的备注
        comments_list = []
        for h in order.histories.all().order_by('date', 'id'):
            if h.comments:
                date_str = h.date.strftime('%Y-%m-%d') if h.date else ''
                comments_list.append(f'{date_str}：{h.comments}')
        comments_text = '\n'.join(comments_list)

        return {
            'code': order.code,
            'market': order.market,
            'name': order.name,
            'cat': order.cat,
            'cat_display': cat_display,
            'market_display': market_display,
            'date': order.open_date.strftime('%Y-%m-%d') if order.open_date else '',
            'intent': '持仓中',
            'price': round(float(order.avg_cost), deci) if order.position_qty > 0 else 0,
            'qty': order.position_qty,
            'amount': round(float(order.position_cost), 2),
            'fee': round(float(order.total_fee), 2),
            'profit': round(float(order.profit), 2),
            'risk_amount': round(float(order.risk_amount), 2),
            'target_price': round(float(order.target_price), deci) if order.target_price else '',
            'stop_price': round(float(order.stop_price), deci) if order.stop_price else '',
            'win_ratio': cash_utils.calc_win_ratio(order.avg_cost, order.target_price, order.stop_price, order.focus.intent if order.focus else 'B') if order.position_qty > 0 else 0,
            'allowed_qty': 0,
            'comments': comments_text,
        }
    else:
        # 历史记录（从数据库快照字段读取）
        return {
            'code': order.code,
            'market': order.market,
            'name': order.name,
            'cat': order.cat,
            'cat_display': cat_display,
            'market_display': market_display,
            'date': history.date.strftime('%Y-%m-%d') if history.date else '',
            'intent': history.get_action_display(),
            'price': round(float(history.avg_cost), deci) if history.avg_cost else 0,
            'qty': history.position_qty,
            'amount': round(float(history.position_qty * history.avg_cost), 2) if history.avg_cost else 0,
            'fee': round(float(history.fee), 2),
            'profit': round(float(history.profit), 2),
            'risk_amount': round(float(history.risk_amount), 2),
            'target_price': round(float(history.target_price), deci) if history.target_price else '',
            'stop_price': round(float(history.stop_price), deci) if history.stop_price else '',
            'win_ratio': history.win_ratio,
            'allowed_qty': '',
            'comments': history.comments or '',
        }


def trans_view(request, market, code):
    site = '/trans/view'
    order = get_object_or_404(TransOrder, code=code, market=market, status=TransOrder.STATUS_OPEN)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效的JSON'}, status=400)

        # pilot 切换历史记录
        if 'pilot' in data:
            func.set_cache(request.session, f'{site}-pilot', int(data['pilot']))
            return JsonResponse({'status': 'success'})

    # 历史记录（所有操作按时间排序）
    histories = list(order.histories.all().order_by('date', 'id'))
    # 进入页面时强制重置为汇总模式（pilot_idx=-1）
    func.set_cache(request.session, f'{site}-pilot', -1)
    func.delete_cache(request.session, f'{site}-navi-data')
    pilot_idx = -1

    is_summary = (pilot_idx < 0)
    pilot = histories[pilot_idx] if not is_summary and histories else None

    # 导航数据
    navi_data = chart.set_navi_data(request.session, site, code, market, 'trans', 'init')

    # 表单初始值
    deci = 3 if order.cat in ('fund', 'bond') else 2
    cat_display = dict(CAT_CHOICES).get(order.cat, order.cat)
    market_display = dict(MARKET_CHOICES).get(order.market, order.market)
    if is_summary or pilot is None:
        # 显示当前持仓汇总
        # 收集所有历史记录中的备注
        comments_list = []
        for h in histories:
            if h.comments:
                date_str = h.date.strftime('%Y-%m-%d') if h.date else ''
                comments_list.append(f'{date_str}：{h.comments}')
        comments_text = '\n'.join(comments_list)

        initial = {
            'cat': cat_display,
            'market': market_display,
            'code': order.code,
            'name': order.name,
            'date': order.open_date.strftime('%Y-%m-%d') if order.open_date else '',
            'intent': '持仓中',
            'price': round(float(order.avg_cost), deci) if order.position_qty > 0 else 0,
            'qty': order.position_qty,
            'amount': round(float(order.position_cost), 2),
            'fee': round(float(order.total_fee), 2),
            'profit': round(float(order.profit), 2),
            'risk_amount': round(float(order.risk_amount), 2),
            'target_price': round(float(order.target_price), deci) if order.target_price else '',
            'stop_price': round(float(order.stop_price), deci) if order.stop_price else '',
            'win_ratio': cash_utils.calc_win_ratio(order.avg_cost, order.target_price, order.stop_price) if order.position_qty > 0 else 0,
            'allowed_qty': 0,
            'comments': comments_text,
        }
        latest_history = histories[-1] if histories else None
        pilot_date = latest_history.date.strftime('%Y-%m-%d') if latest_history and latest_history.date else ''
        pilot_action = ''
    else:
        # 显示历史记录
        h = pilot
        initial = {
            'cat': cat_display,
            'market': market_display,
            'code': order.code,
            'name': order.name,
            'date': h.date.strftime('%Y-%m-%d') if h.date else '',
            'intent': h.get_action_display(),
            'price': round(float(h.price), deci) if h.price else 0,
            'qty': h.qty,
            'amount': round(float(h.amount), 2),
            'fee': round(float(h.fee), 2),
            'profit': round(float(h.profit), 2),
            'risk_amount': round(float(h.risk_amount), 2),
            'target_price': round(float(h.target_price), deci) if h.target_price else '',
            'stop_price': round(float(h.stop_price), deci) if h.stop_price else '',
            'win_ratio': h.win_ratio,
            'allowed_qty': '',
            'comments': h.comments or '',
        }
        pilot_date = h.date.strftime('%Y-%m-%d') if h.date else ''
        pilot_action = h.get_action_display()

    view_mode = func.get_cache(request.session, 'view', 'kline')
    chart_init = {
        'site': site,
        'code': code,
        'market': market,
        'name': order.name,
        'cat': order.cat,
        'view': view_mode,
        'backUrl': '/trans/list',
    }

    return render(request, 'trans-view.html', {
        'order': order,
        'initial': initial,
        'is_summary': is_summary,
        'pilot_idx': pilot_idx,
        'pilot_total': len(histories),
        'pilot_date': pilot_date,
        'pilot_action': pilot_action,
        'chart': json.dumps(chart_init),
        'cash': CashConfig.get_config().cash,
        'available': CashConfig.get_config().allowance - CashConfig.get_config().risk,
    })


# ===================== 交易编辑（仅目标/止损可改） =====================
def trans_edit(request, market, code):
    site = '/trans/edit'
    order = get_object_or_404(TransOrder, code=code, market=market, status=TransOrder.STATUS_OPEN)
    config = CashConfig.get_config()

    if request.method == 'POST':
        target_price = request.POST.get('target_price', '')
        stop_price = request.POST.get('stop_price', '')
        comments = request.POST.get('comments', '')
        update_date = request.POST.get('update_date', '')

        with transaction.atomic():
            old_risk = order.risk_amount
            order.target_price = Decimal(target_price) if target_price else Decimal('0')
            order.stop_price = Decimal(stop_price) if stop_price else Decimal('0')
            # 重新计算风险资金（根据交易方向）
            edit_intent = order.focus.intent if order.focus else 'B'
            order.risk_amount = cash_utils.calc_risk_capital(order.avg_cost_no_fee, order.stop_price, order.position_qty, edit_intent)
            order.save()
            # 更新 config.risk
            config.risk = config.risk - old_risk + order.risk_amount
            if config.risk < 0:
                config.risk = Decimal('0')
            config.save()
            # 记录编辑历史
            deal = TransHistory.objects.create(
                order=order,
                action=TransHistory.ACTION_EDIT,
                intent=edit_intent,
                date=datetime.datetime.strptime(update_date, '%Y-%m-%d').date() if update_date else timezone.now().date(),
                target_price=order.target_price,
                stop_price=order.stop_price,
                comments=comments or '修改目标/止损',
            )
            # 保存该笔编辑后的持仓快照
            deal.profit = order.profit
            deal.win_ratio = cash_utils.calc_win_ratio(order.avg_cost, order.target_price, order.stop_price, edit_intent) if order.position_qty > 0 else 0
            deal.risk_amount = order.risk_amount
            deal.position_qty = order.position_qty
            deal.avg_cost = order.avg_cost
            deal.save(update_fields=['profit', 'win_ratio', 'risk_amount', 'position_qty', 'avg_cost'])
        return redirect('trans_view', market=market, code=code)

    deci = 3 if order.cat in ('fund', 'bond') else 2
    cat_display = dict(CAT_CHOICES).get(order.cat, order.cat)
    market_display = dict(MARKET_CHOICES).get(order.market, order.market)

    # 预期收益 = 卖出收入 - 卖出费用 - 持仓成本(含买入手续费)
    expected_profit = 0
    if order.position_qty > 0 and order.target_price:
        sell_amount = float(order.target_price) * order.position_qty
        commission = max(sell_amount * float(config.commission_ratio), float(config.commission_min))
        stamp = sell_amount * float(config.stamp_sell_ratio)
        sell_fee = commission + stamp
        expected_profit = round(sell_amount - sell_fee - float(order.position_cost), 2)

    # 风险资金 = (不含手续费均价 - 止损价) × 数量，止损价>=均价时为0
    risk_amount = 0
    if order.position_qty > 0 and order.stop_price and order.avg_cost_no_fee > order.stop_price:
        risk_amount = round(float(order.avg_cost_no_fee - order.stop_price) * order.position_qty, 2)

    initial = {
        'cat': cat_display,
        'market': market_display,
        'code': order.code,
        'name': order.name,
        'date': order.updated_at.strftime('%Y-%m-%d') if order.updated_at else '',
        'intent': '持仓中',
        'price': round(float(order.avg_cost), deci) if order.position_qty > 0 else 0,
        'qty': order.position_qty,
        'amount': round(float(order.position_cost), 2),
        'fee': round(float(order.total_fee), 2),
        'profit': expected_profit,
        'risk_amount': risk_amount,
        'target_price': round(float(order.target_price), deci) if order.target_price else '',
        'stop_price': round(float(order.stop_price), deci) if order.stop_price else '',
        'win_ratio': cash_utils.calc_win_ratio(order.avg_cost, order.target_price, order.stop_price) if order.position_qty > 0 else 0,
        'allowed_qty': 0,
        'comments': '',
    }

    view_mode = func.get_cache(request.session, 'view', 'kline')
    chart_init = {
        'site': site,
        'code': code,
        'market': market,
        'name': order.name,
        'cat': order.cat,
        'view': view_mode,
        'backUrl': '/trans/list',
    }

    return render(request, 'trans-edit.html', {
        'order': order,
        'initial': initial,
        'chart': json.dumps(chart_init),
        'cash': config.cash,
        'available': config.allowance - config.risk,
        'avg_cost': round(float(order.avg_cost), 3) if order.position_qty > 0 else 0,
        'avg_cost_no_fee': round(float(order.avg_cost_no_fee), 3) if order.position_qty > 0 else 0,
        'position_qty': order.position_qty,
        'position_cost': round(float(order.position_cost), 2),
        'commission_ratio': float(config.commission_ratio),
        'commission_min': float(config.commission_min),
        'stamp_sell_ratio': float(config.stamp_sell_ratio),
    })
