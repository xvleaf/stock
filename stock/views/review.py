"""
复盘模块：已清仓交易 / 已关闭关注的复盘列表与详情
"""
import json
from decimal import Decimal
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from ..models import ReviewList, TransOrder, FocusStock, TransHistory, FocusHistory
from ..forms import CAT_CHOICES, MARKET_CHOICES
from .. import utils


def _get_cat_display(cat):
    return dict(CAT_CHOICES).get(cat, cat)


def _get_market_display(market):
    return dict(MARKET_CHOICES).get(market, market)


def calc_weighted_return(order):
    """
    综合收益比例 = 总收益 / 加权平均持仓金额
    加权平均持仓金额 = Σ(每阶段持仓金额 × 该阶段天数) / 总持仓天数
    """
    histories = list(order.histories.all().order_by('date', 'id'))
    if not histories or not order.close_date:
        return Decimal('0')

    total_days = 0
    weighted_amount = Decimal('0')

    for i, h in enumerate(histories):
        # 该阶段的持仓金额 = abs(持仓数量) × 持仓均价
        position_qty = abs(h.position_qty) if h.position_qty else 0
        position_amount = Decimal(position_qty) * h.avg_cost if position_qty else Decimal('0')

        # 计算该阶段持续天数
        if i < len(histories) - 1:
            next_h = histories[i + 1]
            days = (next_h.date - h.date).days
        else:
            days = (order.close_date - h.date).days if order.close_date else 0
        days = max(days, 1)

        weighted_amount += position_amount * days
        total_days += days

    if total_days == 0 or weighted_amount == 0:
        return Decimal('0')

    avg_position = weighted_amount / Decimal(total_days)
    if avg_position == 0:
        return Decimal('0')

    return (order.profit / avg_position * Decimal('100')).quantize(Decimal('0.01'))


def _get_date_range(request):
    """获取复盘统计日期范围（起始/结束日期，结束日期仅当天有效，跨天自动重置）。"""
    return utils.get_stat_range('review')


def review_list(request, review_type):
    """复盘列表：已清仓交易 / 已关闭关注"""
    # 验证类型
    if review_type not in ('trans', 'focus'):
        return redirect('review_list', review_type='trans')
    
    # 保存到 session
    utils.set_cache(request.session, 'review-type', review_type)

    # POST：保存分页条件
    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        if 'page' in data:
            utils.set_cache(request.session, 'review-page', int(data['page']))
        if 'per_page' in data:
            utils.set_cache(request.session, 'review-per-page', int(data['per_page']))
        return JsonResponse({'status': 'ok'})

    start_date, end_date, start_str, end_str = _get_date_range(request)

    # 查询 ReviewList
    qs = ReviewList.objects.filter(
        review_type=review_type,
        close_date__gte=start_date,
        close_date__lte=end_date
    ).order_by('-close_date', '-id')

    per_page = int(utils.get_cache(request.session, 'review-per-page', str(utils._get_default_page_size())))
    pg = utils.paginate_queryset(request, qs, 'review-page', per_page=per_page)
    items = list(pg['items'])

    # 计算持仓天数（纯天数）
    for item in items:
        if item.open_date and item.close_date:
            item.hold_days = (item.close_date - item.open_date).days
        else:
            item.hold_days = None

    return render(request, 'review-list.html', {
        'review_type': review_type,
        'list': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'start_date': start_str,
        'end_date': end_str,
    })


def _get_prev_next_review(request, review_type, current_code, current_market, review_id=None):
    """获取当前复盘列表中的上一只和下一只股票"""
    start_date, end_date, _, _ = _get_date_range(request)
    qs = ReviewList.objects.filter(
        review_type=review_type,
        close_date__gte=start_date,
        close_date__lte=end_date
    ).order_by('-close_date', '-id')

    # 使用 review_id 查找当前股票的索引，避免相同 code 的股票索引错乱
    ids = [r.id for r in qs]
    if review_id:
        try:
            idx = ids.index(int(review_id))
        except ValueError:
            return None, None
    else:
        # 没有 review_id 时，回退到使用 (code, market) 查找第一个匹配项
        codes = [(r.code, r.market) for r in qs]
        try:
            idx = codes.index((current_code, current_market))
        except ValueError:
            return None, None

    prev_item = qs[idx - 1] if idx > 0 else None
    next_item = qs[idx + 1] if idx < len(ids) - 1 else None
    return prev_item, next_item


def _build_history_list(order, focus):
    """
    构建历史明细列表：先交易历史（新→旧），再关注历史（新→旧）
    返回可序列化的字典列表
    """
    history_list = []

    # 交易历史
    if order:
        trans_histories = list(order.histories.all().order_by('-id'))
        for h in trans_histories:
            action_text = h.get_action_display()
            if h.action == TransHistory.ACTION_BUY or h.action == TransHistory.ACTION_SELL:
                action_text = f'{h.get_intent_display()}{h.qty}股@{h.price}元'
            history_list.append({
                'type': 'trans',
                'date': h.date.strftime('%Y-%m-%d') if h.date else '',
                'action': action_text,
                'intent': h.get_intent_display(),
                'price': str(h.price),
                'qty': h.qty,
                'amount': str(h.amount),
                'fee': str(h.fee),
                'target_price': str(h.target_price),
                'stop_price': str(h.stop_price),
                'profit': str(h.profit),
                'win_ratio': h.win_ratio,
                'risk_amount': str(h.risk_amount),
                'position_qty': h.position_qty,
                'avg_cost': str(h.avg_cost),
                'comments': h.comments or '',
            })

    # 关注历史
    if focus:
        focus_histories = list(focus.histories.all().order_by('-id'))
        for h in focus_histories:
            action_text = h.get_action_display()
            if h.action == FocusHistory.ACTION_EDIT:
                changes = []
                if h.plan_price is not None:
                    changes.append('计划报价')
                if h.target_price is not None:
                    changes.append('目标价格')
                if h.stop_price is not None:
                    changes.append('止损价格')
                if changes:
                    if len(changes) == 1:
                        action_text = '调整' + changes[0]
                    else:
                        action_text = '调整' + '、'.join(changes[:-1]) + '和' + changes[-1]
            history_list.append({
                'type': 'focus',
                'date': h.edit_date.strftime('%Y-%m-%d') if h.edit_date else '',
                'action': action_text,
                'intent': h.get_intent_display() if h.intent else '',
                'plan_price': str(h.plan_price) if h.plan_price is not None else '',
                'plan_qty': h.plan_qty if h.plan_qty is not None else '',
                'target_price': str(h.target_price) if h.target_price is not None else '',
                'stop_price': str(h.stop_price) if h.stop_price is not None else '',
                'win_ratio': str(h.win_ratio) if h.win_ratio is not None else '',
                'comments': h.comments or '',
            })

    return json.dumps(history_list, ensure_ascii=False), len(history_list)


def review_trans_view(request, market, code):
    """交易复盘详情"""
    review_id = request.GET.get('id')
    if review_id:
        # 根据 review_id 查找对应的记录
        review = ReviewList.objects.filter(id=review_id, review_type=ReviewList.TYPE_TRANS).first()
        if review and review.trans_order:
            order = review.trans_order
        else:
            order = TransOrder.objects.filter(
                code=code, market=market, status=TransOrder.STATUS_CLOSED
            ).order_by('-close_date', '-id').first()
    else:
        # 没有 review_id，取最新的一条
        order = TransOrder.objects.filter(
            code=code, market=market, status=TransOrder.STATUS_CLOSED
        ).order_by('-close_date', '-id').first()
    if not order:
        return redirect('review_list', review_type='trans')

    # 刷新页面时彻底清除 pilot 和 navi 缓存，始终进入汇总模式
    utils.set_cache(request.session, '/review/trans/view-pilot', -1, 600)
    utils.delete_cache(request.session, '/review/trans/view-navi-data')
    utils.delete_cache(request.session, 'kline-deadline')

    focus = order.focus if order.focus_id else None
    review = ReviewList.objects.filter(trans_order=order).first()

    # 构建正确的 navi_data（根据当前 review_id 计算索引）
    from .chart import set_navi_data
    set_navi_data(request.session, '/review/trans/view', code, market, None, 'init', review.id if review else None)

    prev_item, next_item = _get_prev_next_review(request, 'trans', code, market, review_id)
    history_list, history_count = _build_history_list(order, focus)

    # 计算综合收益比例
    profit_ratio = calc_weighted_return(order)

    # 使用 get_trans_data_dict 获取与 trans view 一致的初始值
    from .trans import get_trans_data_dict
    initial = get_trans_data_dict(order)

    # 初始 pilot 状态：汇总模式，up 在历史记录>1时可用，down 禁用
    pilot_prev = history_count > 1
    pilot_next = False

    init_chart = json.dumps({
        'site': '/review/trans/view',
        'code': order.code,
        'market': order.market,
        'name': order.name,
        'cat': order.cat,
        'view': 'kline',
        'navi': {
            'showNavi': True,
            'showPilot': True,
            'backList': '/review/trans/list',
            'pilotPrev': pilot_prev,
            'pilotNext': pilot_next,
        },
        'mark': {
            'showMark': False,
        },
    })

    return render(request, 'review-view.html', {
        'review_type': 'trans',
        'order': order,
        'focus': focus,
        'review': review,
        'profit_ratio': profit_ratio,
        'initial': initial,
        'history_list': history_list,
        'history_count': history_count,
        'is_summary': True,
        'pilot_total': history_count,
        'prev_item': prev_item,
        'next_item': next_item,
        'site': '/review/trans/view',
        'init_chart': init_chart,
        'cat_display': _get_cat_display(order.cat),
        'market_display': _get_market_display(order.market),
    })


def review_focus_view(request, market, code):
    """关注复盘详情"""
    review_id = request.GET.get('id')
    if review_id:
        # 根据 review_id 查找对应的记录
        review = ReviewList.objects.filter(id=review_id, review_type=ReviewList.TYPE_FOCUS).first()
        if review and review.focus_stock:
            focus = review.focus_stock
        else:
            focus = FocusStock.objects.filter(
                code=code, market=market, status=FocusStock.STATUS_CLOSED
            ).order_by('-close_date', '-id').first()
    else:
        # 没有 review_id，取最新的一条
        focus = FocusStock.objects.filter(
            code=code, market=market, status=FocusStock.STATUS_CLOSED
        ).order_by('-close_date', '-id').first()
    if not focus:
        return redirect('review_list', review_type='focus')

    # 刷新页面时彻底清除 pilot 和 navi 缓存，始终进入汇总模式
    utils.set_cache(request.session, '/review/focus/view-pilot', -1, 600)
    utils.delete_cache(request.session, '/review/focus/view-navi-data')
    utils.delete_cache(request.session, 'kline-deadline')

    # 查找关联的已清仓交易
    order = TransOrder.objects.filter(focus=focus, status=TransOrder.STATUS_CLOSED).first()
    review = ReviewList.objects.filter(focus_stock=focus).first()

    # 构建正确的 navi_data（根据当前 review_id 计算索引）
    from .chart import set_navi_data
    set_navi_data(request.session, '/review/focus/view', code, market, None, 'init', review.id if review else None)

    prev_item, next_item = _get_prev_next_review(request, 'focus', code, market, review_id)
    history_list, history_count = _build_history_list(order, focus)

    # 使用 get_focus_data_dict 获取与 focus view 一致的初始值
    from .focus import get_focus_data_dict
    initial = get_focus_data_dict(focus)

    # 初始 pilot 状态：汇总模式，up 在历史记录>1时可用，down 禁用
    pilot_prev = history_count > 1
    pilot_next = False

    init_chart = json.dumps({
        'site': '/review/focus/view',
        'code': focus.code,
        'market': focus.market,
        'name': focus.name,
        'cat': focus.cat,
        'view': 'kline',
        'navi': {
            'showNavi': True,
            'showPilot': True,
            'backList': '/review/focus/list',
            'pilotPrev': pilot_prev,
            'pilotNext': pilot_next,
        },
        'mark': {
            'showMark': False,
        },
    })

    return render(request, 'review-view.html', {
        'review_type': 'focus',
        'order': order,
        'focus': focus,
        'review': review,
        'initial': initial,
        'history_list': history_list,
        'history_count': history_count,
        'is_summary': True,
        'pilot_total': history_count,
        'prev_item': prev_item,
        'next_item': next_item,
        'site': '/review/focus/view',
        'init_chart': init_chart,
        'cat_display': _get_cat_display(focus.cat),
        'market_display': _get_market_display(focus.market),
    })


@require_POST
def review_save(request):
    """保存评级和备注"""
    data, err = utils.parse_json_body(request)
    if err is not None:
        return err

    review_id = data.get('review_id')
    rating = data.get('rating')
    comments = data.get('comments', '')

    try:
        review = ReviewList.objects.get(id=review_id)
        if rating:
            review.rating = int(rating)
        review.comments = comments
        review.save()
        return JsonResponse({'status': 'ok'})
    except ReviewList.DoesNotExist:
        return JsonResponse({'status': 'error', 'msg': '复盘记录不存在'}, status=404)


@require_POST
def save_history_comment(request):
    """保存历史记录备注（按 history_type 区分交易/关注历史）"""
    data, _ = utils.parse_json_body(request)
    data = data or {}
    history_model = TransHistory if data.get('history_type', 'trans') == 'trans' else FocusHistory
    return utils.save_history_comment(request, history_model)
