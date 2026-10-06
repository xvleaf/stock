"""
交易页面：买入/卖出填报
"""
import json
import datetime
from decimal import Decimal
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from django.db import transaction

from ..models import (
    CashConfig, CashHistory, FocusStock, FocusHistory, TransOrder, TransHistory,
    DividendRecord, ReviewList,
)
from ..forms import CAT_CHOICES, MARKET_CHOICES
from .. import utils
from . import chart
from ..fetch.config import get_config, get_all_config
from ..fetch import quote


def _create_or_update_review(order):
    """交易清仓时创建或更新复盘记录"""
    if order.status != TransOrder.STATUS_CLOSED:
        return
    # 计算综合收益比例
    from .review import calc_weighted_return
    profit_ratio = calc_weighted_return(order)
    # 创建或更新 ReviewList
    ReviewList.objects.update_or_create(
        trans_order=order,
        defaults={
            'review_type': ReviewList.TYPE_TRANS,
            'code': order.code,
            'market': order.market,
            'name': order.name,
            'cat': order.cat,
            'open_date': order.open_date,
            'close_date': order.close_date,
            'profit': order.profit,
            'profit_ratio': profit_ratio,
        }
    )


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
        # 持仓中：默认交易方向与持仓方向一致
        default_intent = order.intent
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
    view_mode = utils.get_cache(request.session, 'view', 'kline')
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
        'current_risk': float(config.risk),
        'allowance': float(config.allowance),
        'commission_ratio': float(get_config('commission_ratio', 0.000085)),
        'commission_min': float(get_config('commission_min', 0)),
        'stamp_sell_ratio': float(get_config('stamp_sell_ratio', 0.0005)),
        'chart': json.dumps(chart_init),
        'stock_name': stock_name,
        'stock_cat': stock_cat,
        'stock_market': stock_market,
        'stock_code': code,
        'cat_display': cat_display,
        'market_display': market_display,
    })


def _handle_trans_post(request, market, code, order, focus, stock_name, stock_cat):
    """处理买入/卖出提交（买卖统一流程，仅方向与资金符号不同）。"""
    deci = utils.price_places(stock_cat)
    try:
        params = request.POST
        intent = params.get('intent', 'B')
        date_str = params.get('date', '')
        price = Decimal(str(params.get('price', 0)))
        qty = int(params.get('qty', 0))
        target_price = Decimal(str(params.get('target_price', 0) or 0))
        stop_price = Decimal(str(params.get('stop_price', 0) or 0))
        comments = params.get('comments', '')
        dividend_tax = Decimal(str(params.get('dividend_tax', 0) or 0))
    except (ValueError, TypeError):
        return JsonResponse({'status': 'error', 'error': '参数格式错误'})

    try:
        deal_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        deal_date = timezone.now().date()

    if qty <= 0 or price <= 0:
        return JsonResponse({'status': 'error', 'error': '价格和数量必须大于0'})

    is_buy = (intent == 'B')
    config = CashConfig.get_config()
    amount = utils.round_decimal(price * qty)
    # 优先使用前端传入费用（可手动改），未传则自动计算
    fee_str = params.get('fee', '').strip()
    if fee_str:
        fee = utils.round_decimal(fee_str)
    else:
        fee = utils.calc_fee(amount, intent, market, config)['total']

    with transaction.atomic():
        if is_buy:
            total_cost = amount + fee
            if total_cost > config.cash:
                return JsonResponse({'status': 'error', 'error': f'现金不足，需要 {total_cost}，当前 {config.cash}'})

        # 创建或获取订单
        if not order:
            order = TransOrder(
                focus=focus, code=code, name=stock_name, market=market, cat=stock_cat,
                intent=intent, target_price=target_price, stop_price=stop_price)
            order.save()
        else:
            order.target_price = target_price
            order.stop_price = stop_price

        # 交易前状态
        profit_before = order.profit if order.pk else Decimal('0')
        risk_before = order.risk_amount if order.pk else Decimal('0')
        position_qty_before = order.position_qty if order.pk else 0

        # 创建成交（不触发自动重算），随后统一重算一次
        deal_action = TransHistory.ACTION_BUY if is_buy else TransHistory.ACTION_SELL
        # 卖出平多头（含反手做空）时，红利税随本笔成交首次入库，recalculate 才能计入
        deal_dividend_tax = (dividend_tax
                             if (not is_buy and position_qty_before > 0
                                 and qty >= position_qty_before and dividend_tax > 0)
                             else Decimal('0'))
        deal = utils.create_deal(
            TransHistory, order=order, action=deal_action, intent=intent, date=deal_date,
            price=price, qty=qty, amount=amount, fee=fee,
            dividend_tax=deal_dividend_tax,
            target_price=target_price, stop_price=stop_price, comments=comments)
        order.recalculate()

        deal_profit = utils.round_decimal(order.profit - profit_before)

        # 风险资金 / 盈利机会（基于交易后持仓）
        if order.position_qty != 0:
            order.risk_amount = utils.calc_risk_capital(
                order.avg_cost_no_fee, stop_price, abs(order.position_qty), order.intent)
            order.win_ratio = utils.calc_win_ratio(
                order.avg_cost, target_price, stop_price, order.intent)
        else:
            order.risk_amount = Decimal('0')
            order.win_ratio = 0
        risk_change = order.risk_amount - risk_before
        if order.position_qty > 0:
            order.intent = 'B'
        elif order.position_qty < 0:
            order.intent = 'S'

        # 红利税已固化在本笔成交(dividend_tax)并由 recalculate 计入损益；
        # is_tax_case 仅用于现金到手金额与备注，不再手动冲减 order.profit
        is_tax_case = (not is_buy and position_qty_before > 0
                        and order.position_qty <= 0 and dividend_tax > 0)
        order.save()

        # 该笔交易后持仓快照（_skip_recalc 仍生效，不会触发重算）
        deal.profit = order.profit
        deal.win_ratio = order.win_ratio
        deal.risk_amount = order.risk_amount
        deal.position_qty = order.position_qty
        deal.avg_cost = order.avg_cost
        deal.avg_cost_no_fee = order.avg_cost_no_fee
        snap_fields = ['profit', 'win_ratio', 'risk_amount', 'position_qty',
                       'avg_cost', 'avg_cost_no_fee']
        deal.save(update_fields=snap_fields)

        if is_buy:
            if not order.open_date:
                order.open_date = deal_date
            order.save(update_fields=['open_date'])

        # 资金配置（stock 直接按当前持仓设置，避免反手交易增量误差）
        if is_buy:
            cash_change = -(amount + fee)
            config.cash -= amount + fee
            config.profit += deal_profit
            hist_current = deal_profit
        else:
            # 现金到手=成交额-费用-红利税(代扣)；deal_profit 已由 recalculate 含红利税
            total_income = amount - fee - (dividend_tax if is_tax_case else Decimal('0'))
            cash_change = total_income
            config.cash += total_income
            hist_current = deal_profit
            config.profit += hist_current
        config.stock = order.position_cost_no_fee
        config.total = config.cash + config.stock
        config.risk += risk_change
        if config.risk < 0:
            config.risk = Decimal('0')
        config.save()

        # 资金历史
        if is_buy:
            CashHistory.snapshot(
                event=CashHistory.EVENT_BUY, change=cash_change,
                current_profit=hist_current,
                remark=f'买入{stock_name}{qty}股@{float(price):.{deci}f}元',
                order=order, date=deal_date)
        else:
            CashHistory.snapshot(
                event=CashHistory.EVENT_SELL, change=cash_change,
                current_profit=hist_current,
                remark=f'卖出{stock_name}{qty}股@{float(price):.{deci}f}元'
                       + (f'，扣红利税{dividend_tax}元' if is_tax_case else ''),
                order=order, date=deal_date)

        # 买入：关闭对应关注
        if is_buy and focus and focus.status == FocusStock.STATUS_WATCHING:
            focus.status = FocusStock.STATUS_CLOSED
            focus.close_reason = FocusStock.CLOSE_REASON_BOUGHT
            focus.close_date = deal_date
            focus.save()
            focus.save_history(
                action=FocusHistory.ACTION_DEAL,
                comments=f'买入{stock_name}{qty}股@{float(price):.{deci}f}元')

    if order and order.pk:
        order.refresh_from_db()
        _create_or_update_review(order)

    return JsonResponse({'status': 'success', 'redirect': f'/trans/view/{market}/{code}'})


# ===================== 交易清单 =====================
def trans_list(request):
    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err

        if 'page' in data or 'per_page' in data:
            if 'page' in data:
                utils.set_cache(request.session, 'trans-list-page', int(data['page']))
            if 'per_page' in data:
                utils.set_page_size(request.session, data['per_page'])
            return JsonResponse({'status': 'success'})

        # 股价刷新：只查询当前页的股票
        if 'codes' in data:
            result = utils.refresh_prices(
                data['codes'], TransOrder, 'status', TransOrder.STATUS_OPEN)
            return JsonResponse(result, safe=False, json_dumps_params={'ensure_ascii': False})

    items = []
    qs = TransOrder.objects.filter(status=TransOrder.STATUS_OPEN).order_by('-created_at')
    pg = utils.paginate_queryset(request, qs, 'trans-list-page')

    for o in pg['items']:
        deci = utils.price_places(o.cat)
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
    utils.set_view_back(request.session, '/trans/list')
    return render(request, 'trans-list.html', {
        'list': items,
        'interval': quote.get_quote_interval_ms(),
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

    deci = utils.price_places(order.cat)
    cat_display = dict(CAT_CHOICES).get(order.cat, order.cat)
    market_display = dict(MARKET_CHOICES).get(order.market, order.market)

    if history is None:
        # 当前持仓汇总
        # 收集所有历史记录中的备注（按数据库id倒序，即近期到远期）
        comments_list = []
        for h in order.histories.all().order_by('-id'):
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
    order = TransOrder.objects.filter(
        code=code, market=market, status=TransOrder.STATUS_OPEN).first()
    if not order:
        return redirect('trans_list')

    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        # pilot 切换历史记录
        if 'pilot' in data:
            utils.set_cache(request.session, f'{site}-pilot', int(data['pilot']))
            return JsonResponse({'status': 'success'})

    histories = list(order.histories.all().order_by('id'))
    # 进入页面强制重置为汇总模式（pilot_idx=-1）
    utils.set_cache(request.session, f'{site}-pilot', -1)
    utils.delete_cache(request.session, f'{site}-navi-data')

    chart.set_navi_data(request.session, site, code, market, 'trans', 'init')

    # 汇总数据复用公共字典；模板的 cat/market 字段显示中文
    initial = get_trans_data_dict(order)
    initial['cat'] = initial['cat_display']
    initial['market'] = initial['market_display']

    deci = utils.price_places(order.cat)
    chart_init = utils.build_chart_init(
        site, code, market, order.name, order.cat, back_url='/trans/list')

    # 汇总模式且仅一条历史：指示器显示该笔建仓信息
    pilot_date = pilot_action = pilot_qty = pilot_price = pilot_dividend_amount = ''
    if len(histories) == 1:
        h0 = histories[0]
        pilot_date = h0.date.strftime('%Y-%m-%d') if h0.date else ''
        pilot_action = h0.get_action_display()
        pilot_qty = h0.qty
        pilot_price = f"{float(h0.price):.{deci}f}" if h0.price else ''
        pilot_dividend_amount = (float(h0.dividend_amount)
                                  if h0.action == TransHistory.ACTION_DIVIDEND else '')

    cfg = CashConfig.get_config()
    return render(request, 'trans-view.html', {
        'order': order,
        'initial': initial,
        'is_summary': True,
        'pilot_idx': -1,
        'pilot_total': len(histories),
        'pilot_date': pilot_date,
        'pilot_action': pilot_action,
        'pilot_qty': pilot_qty,
        'pilot_price': pilot_price,
        'pilot_dividend_amount': pilot_dividend_amount,
        'chart': json.dumps(chart_init),
        'cash': cfg.cash,
        'available': cfg.allowance - cfg.risk,
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
            order.risk_amount = utils.calc_risk_capital(order.avg_cost_no_fee, order.stop_price, order.position_qty, edit_intent)
            # 重新计算盈利机会并保存到order
            order.win_ratio = utils.calc_win_ratio(order.avg_cost, order.target_price, order.stop_price, edit_intent) if order.position_qty > 0 else 0
            order.save()
            # 更新 config.risk
            config.risk = config.risk - old_risk + order.risk_amount
            if config.risk < 0:
                config.risk = Decimal('0')
            config.save()
            # 记录编辑历史（不触发自动重算）
            edit_date = (datetime.datetime.strptime(update_date, '%Y-%m-%d').date()
                         if update_date else timezone.now().date())
            deal = utils.create_deal(
                TransHistory, order=order, action=TransHistory.ACTION_EDIT,
                intent=edit_intent, date=edit_date,
                target_price=order.target_price, stop_price=order.stop_price,
                comments=comments or '修改目标/止损')
            # 保存该笔编辑后的持仓快照
            deal.profit = order.profit
            deal.win_ratio = order.win_ratio
            deal.risk_amount = order.risk_amount
            deal.position_qty = order.position_qty
            deal.avg_cost = order.avg_cost
            deal.save(update_fields=['profit', 'win_ratio', 'risk_amount',
                                     'position_qty', 'avg_cost'])
            # 写入资金历史（调整计划，无金额变动）
            CashHistory.snapshot(
                event=CashHistory.EVENT_ADJUST,
                change=Decimal('0'),
                current_profit=Decimal('0'),
                remark=f'调整{order.name}目标/止损',
                order=order,
                date=deal.date,
            )
        return redirect('trans_view', market=market, code=code)

    deci = utils.price_places(order.cat)
    cat_display = dict(CAT_CHOICES).get(order.cat, order.cat)
    market_display = dict(MARKET_CHOICES).get(order.market, order.market)

    # 预期收益 = 卖出收入 - 卖出费用 - 持仓成本(含买入手续费)
    expected_profit = 0
    if order.position_qty > 0 and order.target_price:
        cfg = get_all_config()
        sell_amount = float(order.target_price) * order.position_qty
        commission = max(sell_amount * float(cfg.get('commission_ratio', 0.000085)), float(cfg.get('commission_min', 0)))
        stamp = sell_amount * float(cfg.get('stamp_sell_ratio', 0.0005))
        sell_fee = commission + stamp
        expected_profit = round(sell_amount - sell_fee - float(order.position_cost), 2)

    # 风险资金（基于持仓重新计算，与trans_calc一致）
    risk_amount = float(utils.calc_risk_capital(order.avg_cost_no_fee, order.stop_price, abs(order.position_qty), order.intent)) if order.position_qty != 0 else 0
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
        'win_ratio': order.win_ratio if order.position_qty > 0 else 0,
        'allowed_qty': 0,
        'comments': '',
    }

    chart_init = utils.build_chart_init(
        site, code, market, order.name, order.cat, back_url='/trans/list')

    return render(request, 'trans-edit.html', {
        'order': order,
        'initial': initial,
        'chart': json.dumps(chart_init),
        'cash': config.cash,
        'available': config.allowance - config.risk,
        'current_risk': float(config.risk),
        'allowance': float(config.allowance),
        'avg_cost': round(float(order.avg_cost), 3) if order.position_qty > 0 else 0,
        'avg_cost_no_fee': round(float(order.avg_cost_no_fee), 3) if order.position_qty > 0 else 0,
        'position_qty': order.position_qty,
        'position_cost': round(float(abs(order.position_cost_no_fee)), 2),
        'commission_ratio': float(get_config('commission_ratio', 0.000085)),
        'commission_min': float(get_config('commission_min', 0)),
        'stamp_sell_ratio': float(get_config('stamp_sell_ratio', 0.0005)),
    })


@require_http_methods(["POST"])
def trans_calc(request):
    """交易页面计算接口：成交金额、费用、风险资金、允许数量、盈利机会、预计收益"""
    data, err = utils.parse_json_body(request)
    if err is not None:
        return err

    intent = data.get('intent', 'B')
    market = data.get('market', 'SH')
    price = float(data.get('price', 0) or 0)
    qty = int(data.get('qty', 0) or 0)
    target_price = float(data.get('target_price', 0) or 0)
    stop_price = float(data.get('stop_price', 0) or 0)
    position_qty = int(data.get('position_qty', 0) or 0)
    avg_cost_no_fee = float(data.get('avg_cost_no_fee', 0) or 0)
    # 可选参数：前端手动指定费用/分红税时传入（含 0），未传则用默认
    fee_param = data.get('fee')
    dividend_tax_param = data.get('dividend_tax')

    config = CashConfig.get_config()

    # 成交金额
    amount = round(price * qty, 2) if price > 0 and qty > 0 else 0

    # 交易费用：前端传入（含 0）则用用户手动费用，否则自动计算
    fee_info = utils.calc_fee(amount, intent, market, config)
    if fee_param is not None:
        fee = float(fee_param)
    else:
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
    # 本次交易费用全额计入本次平仓收益，不做数量比例分摊，不分摊到后续交易
    realized_profit = 0
    if qty > 0 and price > 0:
        if intent == 'B' and position_qty < 0:
            # 买入平仓空头（可能反手做多）
            close_qty = min(qty, abs(position_qty))
            realized_profit = (avg_cost_no_fee - price) * close_qty - fee
        elif intent == 'S' and position_qty > 0:
            # 卖出平仓多头（可能反手做空）
            close_qty = min(qty, position_qty)
            realized_profit = (price - avg_cost_no_fee) * close_qty - fee

    # ===== 3. 基于交易后持仓计算盈利机会、风险资金、预计收益 =====
    # 盈利机会
    if new_qty != 0 and target_price > 0 and stop_price > 0:
        win_ratio = utils.calc_win_ratio(new_avg_no_fee, target_price, stop_price, new_intent)
    else:
        win_ratio = 0

    # 风险资金（基于交易后持仓重新计算）
    if new_qty != 0:
        risk_amount = float(utils.calc_risk_capital(new_avg_no_fee, stop_price, abs(new_qty), new_intent))
    else:
        risk_amount = 0
    risk_amount = round(risk_amount, 2)

    # 预计收益 = 已实现收益 + 未实现收益（剩余持仓按目标价，扣除交易费用）
    unrealized_profit = 0
    if new_qty != 0 and target_price > 0:
        if new_intent == 'B':
            sell_amount = target_price * abs(new_qty)
            sell_fee = float(utils.calc_fee(sell_amount, 'S', market, config)['total'])
            unrealized_profit = (target_price - new_avg_no_fee) * abs(new_qty) - sell_fee
        else:
            buy_amount = target_price * abs(new_qty)
            buy_fee = float(utils.calc_fee(buy_amount, 'B', market, config)['total'])
            unrealized_profit = (new_avg_no_fee - target_price) * abs(new_qty) - buy_fee

    # 分红税：前端确认（含手动修改）后传入，从预计收益中扣除
    if dividend_tax_param is not None:
        dividend_tax = float(dividend_tax_param)
    else:
        dividend_tax = 0

    # 本次交易费用：有平仓时已全额计入已实现收益；无平仓时全额从预计收益扣除
    has_close = (qty > 0 and price > 0 and intent == 'B' and position_qty < 0) or \
                (qty > 0 and price > 0 and intent == 'S' and position_qty > 0)
    if has_close:
        profit = round(realized_profit + unrealized_profit - dividend_tax, 2)
    else:
        profit = round(realized_profit + unrealized_profit - dividend_tax - fee, 2)

    # 允许数量（考虑反向交易，逻辑不变）
    base_allowed = utils.calc_allowed_qty(price, stop_price, intent) if price > 0 else 0
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
        'dividend_tax': round(dividend_tax, 2),
        'profit': profit,
    })


# ===================== 分红登记 =====================
@require_http_methods(["POST"])
def trans_dividend(request, market, code):
    """
    分红登记：支持同时登记现金分红和送股
    POST JSON: {cash_amount, bonus_qty, date, remark}
    cash_amount > 0 时进行现金分红，bonus_qty > 0 时进行送股，两者可同时
    折减成本方案：现金分红将股票市值转为现金，不算收益；目标价/止损价同步除权调整
    """
    order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
    if not order:
        return JsonResponse({'error': '未找到持仓记录'}, status=404)
    data, err = utils.parse_json_body(request)
    if err is not None:
        return err

    date_str = data.get('date', '')
    try:
        div_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
    except (ValueError, TypeError):
        return JsonResponse({'error': '日期格式应为 YYYY-MM-DD'}, status=400)
    remark = data.get('remark', '')

    # 接收前端传入的总分红金额和总送股数量
    cash_amount = Decimal(str(data.get('cash_amount', 0) or 0))
    bonus_qty = int(data.get('bonus_qty', 0) or 0)

    if cash_amount <= 0 and bonus_qty <= 0:
        return JsonResponse({'error': '分红金额和送股数量不能同时为0'}, status=400)

    position_qty = abs(order.position_qty)
    if position_qty <= 0:
        return JsonResponse({'error': '当前无持仓'}, status=400)

    # 后台自行计算每股分红和送股比例
    per_share = utils.round_decimal(cash_amount / position_qty) if cash_amount > 0 else Decimal('0')
    bonus_ratio = utils.round_decimal(Decimal(bonus_qty) / Decimal(position_qty)) if bonus_qty > 0 else Decimal('0')
    qty_change = bonus_qty

    with transaction.atomic():
        config = CashConfig.get_config()

        # 1. 现金分红：股票市值转为现金，不算收益
        if cash_amount > 0:
            config.cash = utils.round_decimal(config.cash + cash_amount)
            config.stock = utils.round_decimal(config.stock - cash_amount)  # 折减成本市值
            config.total = utils.round_decimal(config.cash + config.stock)
            # 不修改 config.profit 和 order.profit（分红不算收益）

        # 2. 送股：数量增加，config.stock 不变
        if qty_change > 0:
            if order.intent == TransOrder.INTENT_BUY:
                order.buy_qty += qty_change
            else:
                order.sell_qty += qty_change

        # 3. 调整目标价和止损价（先现金分红下调，再送股同比例下调）
        if per_share > 0:
            if order.target_price > 0:
                order.target_price = utils.round_decimal(order.target_price - per_share)
            if order.stop_price > 0:
                order.stop_price = utils.round_decimal(order.stop_price - per_share)
        if bonus_ratio > 0:
            if order.target_price > 0:
                order.target_price = utils.round_decimal(order.target_price / (1 + bonus_ratio))
            if order.stop_price > 0:
                order.stop_price = utils.round_decimal(order.stop_price / (1 + bonus_ratio))

        # 保存 order 和 config
        order.save()
        config.save()

        # 4. 写入分红记录（先创建，供 recalculate 查询累计现金分红）
        DividendRecord.objects.create(
            order=order, code=code, name=order.name, market=market,
            date=div_date,
            dividend_type=DividendRecord.DIVIDEND_CASH if cash_amount > 0 else DividendRecord.DIVIDEND_BONUS,
            per_share=per_share, bonus_ratio=bonus_ratio,
            amount=cash_amount, qty_change=qty_change,
            remark=remark,
        )

        # 5. 写入交易历史（现金分红和送股都需要，用于历史切换和撤销恢复）
        # 备注：现金分红与送股同时登记时完整显示两者
        if remark:
            deal_comments = remark
        else:
            _parts = []
            if cash_amount > 0:
                _parts.append(f'分红{cash_amount}元')
            if qty_change > 0:
                _parts.append(f'送股{qty_change}股')
            deal_comments = '，'.join(_parts)
        deal = utils.create_deal(
            TransHistory, order=order, action=TransHistory.ACTION_DIVIDEND,
            intent=order.intent, date=div_date,
            price=Decimal('0'), qty=qty_change, amount=Decimal('0'), fee=Decimal('0'),
            dividend_amount=cash_amount,
            target_price=order.target_price, stop_price=order.stop_price,
            comments=deal_comments,
        )

        # 6. 统一 recalculate（重新计算均价、盈利机会、风险资金；position_cost 扣除累计现金分红）
        order.recalculate()

        # 7. 更新交易历史的快照字段（recalculate 后的值）
        deal.profit = order.profit
        deal.win_ratio = order.win_ratio
        deal.risk_amount = order.risk_amount
        deal.position_qty = order.position_qty
        deal.avg_cost = order.avg_cost
        deal.avg_cost_no_fee = order.avg_cost_no_fee
        deal.save(update_fields=['profit', 'win_ratio', 'risk_amount', 'position_qty', 'avg_cost', 'avg_cost_no_fee'])

        # 8. 写入资金历史（change 为现金分红金额，送股时为0；current_profit 为0，分红不算收益）
        # 【修改】资金历史备注：同时分红+送股时完整显示两者
        if remark:
            full_remark = remark
        else:
            _parts = []
            if cash_amount > 0:
                _parts.append(f'分红{cash_amount}元')
            if qty_change > 0:
                _parts.append(f'送股{qty_change}股')
            full_remark = f'{order.name}{"，".join(_parts)}'
        CashHistory.snapshot(
            event=CashHistory.EVENT_DIVIDEND,
            change=cash_amount,
            current_profit=Decimal('0'),  # 分红不算收益
            remark=full_remark,
            order=order,
            date=div_date,
        )

    return JsonResponse({'status': 'success', 'cash_amount': str(cash_amount), 'qty_change': qty_change})


@require_http_methods(['POST'])
def calc_dividend_tax(request, market, code):
    """
    计算卖出清仓时的红利税明细（按买入批次计算）
    POST JSON: {date: 'YYYY-MM-DD'}
    返回每个批次的明细及合计税额
    """
    order = TransOrder.objects.filter(code=code, market=market, status=TransOrder.STATUS_OPEN).first()
    if not order:
        return JsonResponse({'error': '未找到持仓记录'}, status=404)
    data, err = utils.parse_json_body(request)
    if err is not None:
        return err

    date_str = data.get('date', '')
    try:
        deal_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else timezone.now().date()
    except (ValueError, TypeError):
        return JsonResponse({'error': '日期格式应为 YYYY-MM-DD'}, status=400)

    cfg = get_all_config()
    tax_long = Decimal(str(cfg.get('dividend_tax_long', 0) or 0))
    tax_mid = Decimal(str(cfg.get('dividend_tax_mid', 0.1) or 0))
    tax_short = Decimal(str(cfg.get('dividend_tax_short', 0.2) or 0))

    # 1. 遍历历史记录，维护FIFO批次队列，在每笔现金分红日快照
    histories = order.histories.all().order_by('date', 'id')
    batches = []  # [{'buy_date': date, 'qty': int}]
    dividend_snapshots = []  # [{'div_date': date, 'per_share': Decimal, 'batches': [{'buy_date': date, 'qty': int}]}]
    cash_dividends = list(DividendRecord.objects.filter(
        order=order, dividend_type=DividendRecord.DIVIDEND_CASH
    ).order_by('date', 'id'))
    div_idx = 0

    for h in histories:
        if h.action == TransHistory.ACTION_EDIT:
            continue
        if h.action == TransHistory.ACTION_BUY:
            batches.append({'buy_date': h.date, 'qty': h.qty})
        elif h.action == TransHistory.ACTION_SELL:
            # FIFO扣减
            remain = h.qty
            while remain > 0 and batches:
                if batches[0]['qty'] <= remain:
                    remain -= batches[0]['qty']
                    batches.pop(0)
                else:
                    batches[0]['qty'] -= remain
                    remain = 0
        elif h.action == TransHistory.ACTION_DIVIDEND:
            # 送股：按比例增加所有批次数量
            if h.qty > 0:
                total = sum(b['qty'] for b in batches)
                if total > 0:
                    ratio = Decimal(h.qty) / Decimal(total)
                    for b in batches:
                        b['qty'] = int(b['qty'] * (1 + ratio))
            # 现金分红：快照批次分布（通过日期匹配DividendRecord）。
            # 用 h.dividend_amount>0 判断是否含现金分红（兼容现金+送股同时登记，
            # 此时 h.qty>0 仍应生成现金快照；原 h.qty==0 判断会丢失该快照）
            if h.dividend_amount > 0 and div_idx < len(cash_dividends):
                div = cash_dividends[div_idx]
                dividend_snapshots.append({
                    'div_date': div.date,
                    'per_share': div.per_share,
                    'batches': [{'buy_date': b['buy_date'], 'qty': b['qty']} for b in batches],
                })
                div_idx += 1

    # 2. 按批次计算税额
    details = []
    total_tax = Decimal('0')
    for snap in dividend_snapshots:
        div_date = snap['div_date']
        per_share = snap['per_share']
        for b in snap['batches']:
            if b['qty'] <= 0:
                continue
            hold_days = (deal_date - b['buy_date']).days
            if hold_days > 365:
                tax_rate = tax_long
                rate_label = '0%'
            elif hold_days >= 30:
                tax_rate = tax_mid
                rate_label = '10%'
            else:
                tax_rate = tax_short
                rate_label = '20%'
            div_amount = utils.round_decimal(per_share * b['qty'])
            tax = utils.round_decimal(div_amount * tax_rate)
            total_tax += tax
            details.append({
                'div_date': div_date.strftime('%Y-%m-%d'),
                'buy_date': b['buy_date'].strftime('%Y-%m-%d'),
                'hold_days': hold_days,
                'qty': b['qty'],
                'per_share': str(per_share),
                'div_amount': str(div_amount),
                'tax_rate': rate_label,
                'tax': str(tax),
            })

    return JsonResponse({
        'has_dividend': len(details) > 0,
        'total_tax': str(total_tax),
        'details': details,
    })


@require_http_methods(["POST"])
def save_history_comment(request):
    """保存交易历史记录的备注"""
    return utils.save_history_comment(request, TransHistory)
