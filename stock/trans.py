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
    # 根据股票类型设置小数位数：基金/债券3位，股票2位
    deci = 3 if stock_cat in ('fund', 'bond') else 2

    # 初始表单数据
    can_choose_intent = not order  # 无持仓时可选择交易方向
    if order:
        # 持仓中：根据订单方向决定默认操作
        if order.intent == 'S':
            # 空头持仓：默认买入平仓
            default_intent = 'B'
        else:
            # 多头持仓：默认卖出平仓
            default_intent = 'S'
        initial = {
            'intent': default_intent,
            'date': timezone.now().strftime('%Y-%m-%d'),
            'price': round(float(order.avg_cost), deci) if order.avg_cost > 0 else 0,
            'qty': abs(order.position_qty),
            'target_price': float(order.target_price) if order.target_price else 0,
            'stop_price': float(order.stop_price) if order.stop_price else 0,
            'win_ratio': 0,
            'comments': '',
        }
        avg_cost = float(order.avg_cost)
        avg_cost_no_fee = float(order.avg_cost_no_fee) if order.avg_cost_no_fee else 0
        position_qty = order.position_qty
    else:
        # 关注中：默认使用 focus 的关注方向
        initial = {
            'intent': focus.intent if focus else 'B',
            'date': timezone.now().strftime('%Y-%m-%d'),
            'price': round(float(focus.plan_price), deci) if focus.plan_price else 0,
            'qty': focus.plan_qty,
            'target_price': float(focus.target_price) if focus.target_price else 0,
            'stop_price': float(focus.stop_price) if focus.stop_price else 0,
            'win_ratio': float(focus.win_ratio) if focus.win_ratio else 0,
            'comments': '',
        }
        avg_cost = 0
        avg_cost_no_fee = 0
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
        'avg_cost_no_fee': avg_cost_no_fee,
        'position_qty': position_qty,
        'can_choose_intent': can_choose_intent,
        'cash': float(config.cash),
        'available': float(config.allowance - config.risk),
        'current_risk': float(order.risk_amount) if order else 0,
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
                    intent='B',
                    target_price=target_price,
                    stop_price=stop_price,
                )
                order.save()
            else:
                order.target_price = target_price
                order.stop_price = stop_price

            # 记录交易前的状态
            profit_before = order.profit if order.pk else Decimal('0')
            risk_before = order.risk_amount if order.pk else Decimal('0')
            position_qty_before = order.position_qty if order.pk else 0

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

            # 本次收益
            deal_profit = _q(order.profit - profit_before)

            # 风险资金（基于交易后持仓重新计算，与trans_calc一致）
            if order.position_qty != 0:
                order.risk_amount = cash_utils.calc_risk_capital(order.avg_cost_no_fee, stop_price, abs(order.position_qty), order.intent)
                # 盈利机会：基于含手续费均价、目标价、止损价、持仓方向计算，保存到order避免重复计算
                order.win_ratio = cash_utils.calc_win_ratio(order.avg_cost, target_price, stop_price, order.intent)
            else:
                order.risk_amount = Decimal('0')
                order.win_ratio = 0
            risk_change = order.risk_amount - risk_before
            # 更新持仓方向
            if order.position_qty > 0:
                order.intent = 'B'
            elif order.position_qty < 0:
                order.intent = 'S'
            order.save()

            # 保存该笔交易后的持仓快照
            deal.profit = order.profit
            deal.win_ratio = order.win_ratio
            deal.risk_amount = order.risk_amount
            deal.position_qty = order.position_qty
            deal.avg_cost = order.avg_cost
            deal.avg_cost_no_fee = order.avg_cost_no_fee
            deal.save(update_fields=['profit', 'win_ratio', 'risk_amount', 'position_qty', 'avg_cost', 'avg_cost_no_fee'])
            if not order.open_date:
                order.open_date = deal_date
            order.save()

            # 更新资金配置
            config.cash -= total_cost
            # stock 更新：多头建仓增加，空头平仓减少（欠股票减少）
            if position_qty_before >= 0:
                config.stock += amount
            else:
                short_qty = abs(position_qty_before)
                if qty <= short_qty:
                    config.stock += amount  # 空头平仓，欠股票减少
                else:
                    # 反手：先平空头，再买多
                    close_amount = price * short_qty
                    remain_amount = price * (qty - short_qty)
                    config.stock += close_amount + remain_amount
            config.total = config.cash + config.stock
            config.risk += risk_change
            if config.risk < 0:
                config.risk = Decimal('0')
            config.profit += deal_profit
            config.save()

            # 写入资金历史
            CashHistory.snapshot(
                event=CashHistory.EVENT_BUY,
                change=-total_cost,
                profit=deal_profit,
                remark=f'买入{stock_name}{qty}股@{price}',
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
            total_income = amount - fee

            # 创建或获取交易订单（卖空建仓时可能没有订单）
            if not order:
                order = TransOrder(
                    focus=focus,
                    code=code,
                    name=stock_name,
                    market=market,
                    cat=stock_cat,
                    intent='S',
                    target_price=target_price,
                    stop_price=stop_price,
                )
                order.save()
            else:
                order.target_price = target_price
                order.stop_price = stop_price

            # 记录交易前的状态
            profit_before = order.profit if order.pk else Decimal('0')
            risk_before = order.risk_amount if order.pk else Decimal('0')
            position_qty_before = order.position_qty if order.pk else 0

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
                target_price=target_price,
                stop_price=stop_price,
                comments=comments,
            )

            # 重新计算订单所有汇总字段
            order.recalculate()

            # 本次收益
            deal_profit = _q(order.profit - profit_before)

            # 风险资金（基于交易后持仓重新计算，与trans_calc一致）
            if order.position_qty != 0:
                order.risk_amount = cash_utils.calc_risk_capital(order.avg_cost_no_fee, stop_price, abs(order.position_qty), order.intent)
                # 盈利机会：基于含手续费均价、目标价、止损价、持仓方向计算，保存到order避免重复计算
                order.win_ratio = cash_utils.calc_win_ratio(order.avg_cost, target_price, stop_price, order.intent)
            else:
                order.risk_amount = Decimal('0')
                order.win_ratio = 0
            risk_change = order.risk_amount - risk_before
            # 更新持仓方向
            if order.position_qty > 0:
                order.intent = 'B'
            elif order.position_qty < 0:
                order.intent = 'S'
            order.save()

            # 保存该笔交易后的持仓快照
            deal.profit = order.profit
            deal.win_ratio = order.win_ratio
            deal.risk_amount = order.risk_amount
            deal.position_qty = order.position_qty
            deal.avg_cost = order.avg_cost
            deal.avg_cost_no_fee = order.avg_cost_no_fee
            deal.save(update_fields=['profit', 'win_ratio', 'risk_amount', 'position_qty', 'avg_cost', 'avg_cost_no_fee'])

            # 更新资金配置
            config.cash += total_income
            # stock 更新：卖空建仓减少（欠股票），多头平仓减少
            if position_qty_before <= 0:
                config.stock -= amount  # 卖空建仓/加仓，欠股票增加
            else:
                if qty <= position_qty_before:
                    config.stock -= amount  # 多头平仓
                else:
                    # 反手：先平多头，再卖空
                    close_amount = price * position_qty_before
                    remain_amount = price * (qty - position_qty_before)
                    config.stock -= close_amount + remain_amount
            config.total = config.cash + config.stock
            config.risk += risk_change
            if config.risk < 0:
                config.risk = Decimal('0')
            config.profit += deal_profit
            config.save()

            # 写入资金历史
            CashHistory.snapshot(
                event=CashHistory.EVENT_SELL,
                change=total_income,
                profit=deal_profit,
                remark=f'卖出{stock_name}{qty}股@{price}',
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
        for h in order.histories.all().order_by('-date', '-id'):
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
            'price': round(float(order.avg_cost), deci) if order.position_qty != 0 else 0,
            'qty': order.position_qty,
            'amount': round(float(abs(order.position_cost_no_fee)), 2),
            'fee': round(float(order.total_fee), 2),
            'profit': round(float(order.profit), 2),
            'risk_amount': round(float(order.risk_amount), 2),
            'target_price': round(float(order.target_price), deci) if order.target_price else '',
            'stop_price': round(float(order.stop_price), deci) if order.stop_price else '',
            'win_ratio': order.win_ratio if order.position_qty != 0 else 0,
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
            'amount': round(float(abs(history.position_qty * history.avg_cost_no_fee)), 2) if history.avg_cost_no_fee else 0,
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
    order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
    if not order:
        return redirect('trans_list')

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
        # 收集所有历史记录中的备注（按近期到远期顺序）
        comments_list = []
        for h in reversed(histories):
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
            'price': round(float(order.avg_cost), deci) if order.position_qty != 0 else 0,
            'qty': order.position_qty,
            'amount': round(float(abs(order.position_cost_no_fee)), 2),
            'fee': round(float(order.total_fee), 2),
            'profit': round(float(order.profit), 2),
            'risk_amount': round(float(order.risk_amount), 2),
            'target_price': round(float(order.target_price), deci) if order.target_price else '',
            'stop_price': round(float(order.stop_price), deci) if order.stop_price else '',
            'win_ratio': order.win_ratio if order.position_qty != 0 else 0,
            'allowed_qty': 0,
            'comments': comments_text,
        }
        latest_history = histories[-1] if histories else None
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
        'chart': json.dumps(chart_init),
        'cash': CashConfig.get_config().cash,
        'available': CashConfig.get_config().allowance - CashConfig.get_config().risk,
    })


# ===================== 交易编辑（仅目标/止损可改） =====================
def trans_edit(request, market, code):
    site = '/trans/edit'
    order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
    if not order:
        return redirect('trans_list')
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
            # 重新计算盈利机会并保存到order
            order.win_ratio = cash_utils.calc_win_ratio(order.avg_cost, order.target_price, order.stop_price, edit_intent) if order.position_qty > 0 else 0
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
            deal.win_ratio = order.win_ratio
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

    # 风险资金（基于持仓重新计算，与trans_calc一致）
    risk_amount = float(cash_utils.calc_risk_capital(order.avg_cost_no_fee, order.stop_price, abs(order.position_qty), order.intent)) if order.position_qty != 0 else 0
    risk_amount = round(risk_amount, 2)

    initial = {
        'cat': cat_display,
        'market': market_display,
        'code': order.code,
        'name': order.name,
        'date': order.updated_at.strftime('%Y-%m-%d') if order.updated_at else '',
        'intent': '持仓中',
        'price': round(float(order.avg_cost), deci) if order.position_qty > 0 else 0,
        'qty': order.position_qty,
        'amount': round(float(abs(order.position_cost_no_fee)), 2),
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
        'position_cost': round(float(abs(order.position_cost_no_fee)), 2),
        'commission_ratio': float(config.commission_ratio),
        'commission_min': float(config.commission_min),
        'stamp_sell_ratio': float(config.stamp_sell_ratio),
    })


@require_http_methods(["POST"])
def trans_calc(request):
    """交易页面计算接口：成交金额、费用、风险资金、允许数量、盈利机会、预计收益"""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '无效的JSON'}, status=400)

    intent = data.get('intent', 'B')
    price = float(data.get('price', 0) or 0)
    qty = int(data.get('qty', 0) or 0)
    target_price = float(data.get('target_price', 0) or 0)
    stop_price = float(data.get('stop_price', 0) or 0)
    position_qty = int(data.get('position_qty', 0) or 0)
    current_risk = float(data.get('current_risk', 0) or 0)
    avg_cost = float(data.get('avg_cost', 0) or 0)
    avg_cost_no_fee = float(data.get('avg_cost_no_fee', 0) or 0)

    config = CashConfig.get_config()

    # 成交金额
    amount = round(price * qty, 2) if price > 0 and qty > 0 else 0

    # 交易费用
    fee_info = cash_utils.calc_fee(amount, intent, config)
    fee = float(fee_info['total'])

    # ===== 1. 计算交易后的持仓状态（方向、数量、均价）=====
    new_qty = 0
    new_avg_no_fee = 0
    new_intent = 'B'

    if intent == 'B':
        if position_qty >= 0:
            # 多头或空仓：加仓/建仓
            new_qty = position_qty + qty
            if new_qty > 0:
                new_avg_no_fee = (avg_cost_no_fee * position_qty + price * qty) / new_qty
            new_intent = 'B'
        else:
            # 空头持仓：买入平仓（可能反手）
            short_qty = abs(position_qty)
            if qty <= short_qty:
                # 部分平仓，仍为空头
                new_qty = position_qty + qty
                new_avg_no_fee = avg_cost_no_fee
                new_intent = 'S'
            else:
                # 平仓后反手做多
                new_qty = qty - short_qty
                new_avg_no_fee = price
                new_intent = 'B'
    else:  # intent == 'S'
        if position_qty <= 0:
            # 空头或空仓：加仓/建仓
            new_qty = position_qty - qty
            total_qty = abs(position_qty) + qty
            if total_qty > 0:
                new_avg_no_fee = (avg_cost_no_fee * abs(position_qty) + price * qty) / total_qty
            new_intent = 'S'
        else:
            # 多头持仓：卖出平仓（可能反手）
            long_qty = position_qty
            if qty <= long_qty:
                # 部分平仓，仍为多头
                new_qty = position_qty - qty
                new_avg_no_fee = avg_cost_no_fee
                new_intent = 'B'
            else:
                # 平仓后反手做空
                new_qty = -(qty - long_qty)
                new_avg_no_fee = price
                new_intent = 'S'

    # ===== 2. 计算已实现收益（平仓部分）=====
    realized_profit = 0
    if qty > 0 and price > 0:
        if intent == 'B' and position_qty < 0:
            # 买入平仓空头
            short_qty = abs(position_qty)
            close_qty = min(qty, short_qty)
            close_fee = fee * (close_qty / qty) if qty > 0 else 0
            realized_profit = (avg_cost_no_fee - price) * close_qty - close_fee
        elif intent == 'S' and position_qty > 0:
            # 卖出平仓多头
            long_qty = position_qty
            close_qty = min(qty, long_qty)
            close_fee = fee * (close_qty / qty) if qty > 0 else 0
            realized_profit = (price - avg_cost_no_fee) * close_qty - close_fee

    # ===== 3. 基于交易后持仓计算盈利机会、风险资金、预计收益 =====
    # 盈利机会
    if new_qty != 0 and target_price > 0 and stop_price > 0:
        win_ratio = cash_utils.calc_win_ratio(new_avg_no_fee, target_price, stop_price, new_intent)
    else:
        win_ratio = 0

    # 风险资金（基于交易后持仓重新计算）
    if new_qty != 0:
        risk_amount = float(cash_utils.calc_risk_capital(new_avg_no_fee, stop_price, abs(new_qty), new_intent))
    else:
        risk_amount = 0
    risk_amount = round(risk_amount, 2)

    # 预计收益 = 已实现收益 + 未实现收益（剩余持仓按目标价，扣除交易费用）
    unrealized_profit = 0
    if new_qty != 0 and target_price > 0:
        if new_intent == 'B':
            sell_amount = target_price * abs(new_qty)
            sell_fee = float(cash_utils.calc_fee(sell_amount, 'S', config)['total'])
            unrealized_profit = (target_price - new_avg_no_fee) * abs(new_qty) - sell_fee
        else:
            buy_amount = target_price * abs(new_qty)
            buy_fee = float(cash_utils.calc_fee(buy_amount, 'B', config)['total'])
            unrealized_profit = (new_avg_no_fee - target_price) * abs(new_qty) - buy_fee

    profit = round(realized_profit + unrealized_profit, 2)

    # 允许数量（考虑反向交易，逻辑不变）
    base_allowed = cash_utils.calc_allowed_qty(price, stop_price, intent) if price > 0 else 0
    if intent == 'B' and position_qty < 0:
        # 买入：空头持仓可平仓 + 可新开仓
        allowed_qty = abs(position_qty) + base_allowed
    elif intent == 'S' and position_qty > 0:
        # 卖出：多头持仓可平仓 + 可新开仓
        allowed_qty = position_qty + base_allowed
    else:
        allowed_qty = base_allowed

    return JsonResponse({
        'amount': amount,
        'fee': round(fee, 2),
        'risk_amount': risk_amount,
        'allowed_qty': allowed_qty,
        'win_ratio': win_ratio,
        'profit': profit,
    })
