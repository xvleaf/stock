# -*- coding: utf-8 -*-
"""
资金页面
- 资金总览页面（当前状态 + 历史变化图）
交易计算类公共函数已统一移至 stock/utils.py
"""
import json
import datetime
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods
from django.db import transaction
from ..models import CashConfig, CashHistory, TransOrder, TransHistory, FocusStock, DividendRecord, ReviewList
from .. import utils


# ===================== 资金总览页面 =====================
def cash_view(request):
    """资金页面：当前状态 + 历史变化图"""
    initialized = CashConfig.has_config()
    config = CashConfig.get_config()
    # 最近一条历史记录用于展示
    latest_history = CashHistory.objects.first()
    # 可撤回的记录ID：最新一条为存入/取出/买入/卖出/调整计划/分红时
    revocable_id = latest_history.id if latest_history and latest_history.event in (
        CashHistory.EVENT_DEPOSIT, CashHistory.EVENT_WITHDRAW,
        CashHistory.EVENT_BUY, CashHistory.EVENT_SELL,
        CashHistory.EVENT_ADJUST, CashHistory.EVENT_DIVIDEND
    ) else None
    # 分页 / 每页数量（POST 提交时更新 session）
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            data = request.POST
        if 'page' in data:
            utils.set_cache(request.session, 'cash-history-page', int(data['page']))
        if 'per_page' in data:
            utils.set_cache(request.session, 'cash-per-page', int(data['per_page']))
        return JsonResponse({'status': 'ok'})
    # 日期范围：从 WebSetting 获取，结束日期仅当天有效，跨天自动恢复为当天
    from ..fetch.config import get_config, set_config
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    # 默认起始日期：去年今天 + 1天（Python日期运算自动处理大小月/闰年进位）
    try:
        _last_year_today = today.replace(year=today.year - 1)
    except ValueError:
        _last_year_today = today.replace(year=today.year - 1, day=28)
    default_start = (_last_year_today + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    # 起始日期：从 WebSetting 获取，空则使用默认值
    start_str = str(get_config('cash_stat_start', '') or default_start)
    # 结束日期：检查设置日期是否为今天，是则用存储值，否则自动更新为今天
    end_set_day = str(get_config('cash_stat_end_set_day', ''))
    if end_set_day == today_str:
        end_str = str(get_config('cash_stat_end', '') or today_str)
    else:
        # 跨天了，自动更新结束日期为今天
        end_str = today_str
        set_config('cash_stat_end', today_str)
        set_config('cash_stat_end_set_day', today_str)
    try:
        start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        start_date = _last_year_today + datetime.timedelta(days=1)
        start_str = start_date.strftime('%Y-%m-%d')
    try:
        end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        end_date = today
        end_str = end_date.strftime('%Y-%m-%d')
    # 历史记录按日期范围过滤 + 分页（每页条数独立存储，不影响其他页面）
    # 资金变化记录仅按 id 排序（不按日期），保证与创建顺序一致
    history_qs = CashHistory.objects.filter(date__gte=start_date, date__lte=end_date).order_by('-id')
    cash_per_page = int(utils.get_cache(request.session, 'cash-per-page', str(utils._get_default_page_size())))
    pg = utils.paginate_queryset(request, history_qs, 'cash-history-page', per_page=cash_per_page)
    items = list(pg['items'])
    return render(request, 'cash-view.html', {
        'config': config,
        'initialized': initialized,
        'latest': latest_history,
        'revocable_id': revocable_id,
        'history_list': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'total_count': pg['total_count'],
        'start_date': start_str,
        'end_date': end_str,
    })


@require_http_methods(["GET"])
def cash_history_api(request):
    """返回资金历史数据（供前端 Highcharts 绘制），日期范围从 WebSetting 获取"""
    from ..fetch.config import get_config, set_config
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    # 默认起始日期：去年今天 + 1天
    try:
        _last_year_today = today.replace(year=today.year - 1)
    except ValueError:
        _last_year_today = today.replace(year=today.year - 1, day=28)
    default_start = (_last_year_today + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    # 起始日期：从 WebSetting 获取，空则使用默认值
    start_str = str(get_config('cash_stat_start', '') or default_start)
    # 结束日期：检查设置日期是否为今天，是则用存储值，否则自动更新为今天
    end_set_day = str(get_config('cash_stat_end_set_day', ''))
    if end_set_day == today_str:
        end_str = str(get_config('cash_stat_end', '') or today_str)
    else:
        end_str = today_str
        set_config('cash_stat_end', today_str)
        set_config('cash_stat_end_set_day', today_str)
    # 【资金历史图数据也仅按 id 排序（id 递增即创建顺序）
    qs = CashHistory.objects.all().order_by('id')
    if start_str:
        try:
            qs = qs.filter(date__gte=datetime.datetime.strptime(start_str, '%Y-%m-%d').date())
        except (ValueError, TypeError):
            pass
    if end_str:
        try:
            qs = qs.filter(date__lte=datetime.datetime.strptime(end_str, '%Y-%m-%d').date())
        except (ValueError, TypeError):
            pass
    total_series = []
    cash_series = []
    stock_series = []
    profit_series = []
    reasons = []
    for h in qs:
        date_str = h.date.strftime('%Y-%m-%d')
        total_series.append([date_str, float(h.total)])
        cash_series.append([date_str, float(h.cash)])
        stock_series.append([date_str, float(h.stock)])
        profit_series.append([date_str, float(h.total_profit)])
        reasons.append({
            'date': date_str,
            'event': h.get_event_display(),
            'change': float(h.change),
            'remark': h.remark,
            'total': float(h.total),
            'cash': float(h.cash),
            'stock': float(h.stock),
            'risk': float(h.risk),
            'current_profit': float(h.current_profit),
            'total_profit': float(h.total_profit),
        })
    return JsonResponse({
        'total': total_series,
        'cash': cash_series,
        'stock': stock_series,
        'profit': profit_series,
        'reasons': reasons,
    })


@require_http_methods(["POST"])
def cash_adjust_api(request):
    """
    手动调整资金（存入/取出），并写入历史记录
    POST JSON: {action: 'deposit'|'withdraw', amount: 10000, remark: ''}
    """
    try:
        params = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': '无效JSON'}, status=400)

    action = params.get('action')
    amount = Decimal(str(params.get('amount', 0)))
    remark = params.get('remark', '')
    date_str = params.get('date', '')
    adjust_date = None
    if date_str:
        try:
            adjust_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            pass

    if action not in ('deposit', 'withdraw'):
        return JsonResponse({'error': '不支持的操作'}, status=400)
    if amount <= 0:
        return JsonResponse({'error': '金额必须大于0'}, status=400)

    config = CashConfig.get_config()
    with transaction.atomic():
        if action == 'deposit':
            config.cash += amount
            change_amount = amount
            event = CashHistory.EVENT_DEPOSIT
        else:
            if amount > config.cash:
                return JsonResponse({'error': '取出金额超过可用现金'}, status=400)
            config.cash -= amount
            change_amount = -amount
            event = CashHistory.EVENT_WITHDRAW
        # 总资产始终等于现金+股票
        config.total = config.cash + config.stock
        config.save()
        # 快照写入历史（存入/取出无收益）
        CashHistory.snapshot(event=event, change=change_amount, current_profit=0, remark=remark, date=adjust_date)
    return JsonResponse({
        'msg': 'done',
        'total': float(config.total),
        'cash': float(config.cash),
        'stock': float(config.stock),
        'allowance': float(config.allowance),
        'risk': float(config.risk),
        'profit': float(config.profit),
    })


# ===================== 撤回最近一笔存入/取出 =====================
@require_http_methods(["POST"])
def cash_revoke(request):
    """
    撤回最近一笔记录（存入/取出/买入/卖出）
    POST JSON: {history_id: 123}
    """
    try:
        params = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '无效JSON'}, status=400)
    history_id = params.get('history_id')
    if not history_id:
        return JsonResponse({'error': '缺少记录ID'}, status=400)

    # 最新一条记录（按id倒序，因为snapshot时id递增）
    latest = CashHistory.objects.order_by('-id').first()
    if not latest or latest.id != int(history_id):
        return JsonResponse({'error': '仅可撤回最新一笔记录'}, status=400)
    if latest.event not in (CashHistory.EVENT_DEPOSIT, CashHistory.EVENT_WITHDRAW,
                            CashHistory.EVENT_BUY, CashHistory.EVENT_SELL,
                            CashHistory.EVENT_ADJUST, CashHistory.EVENT_DIVIDEND):
        return JsonResponse({'error': '该记录不可撤回'}, status=400)

    config = CashConfig.get_config()

    with transaction.atomic():
        if latest.event in (CashHistory.EVENT_DEPOSIT, CashHistory.EVENT_WITHDRAW):
            # 撤回存入/取出
            amount = abs(latest.change)
            if latest.event == CashHistory.EVENT_DEPOSIT:
                config.cash -= amount
            else:
                config.cash += amount
            config.total = config.cash + config.stock
            config.save()
            latest.delete()
        elif latest.event == CashHistory.EVENT_ADJUST:
            # 撤回调整计划（修改目标/止损）
            order = latest.order
            if not order:
                return JsonResponse({'error': '关联交易订单不存在'}, status=400)
            # 获取最新的 edit 类型 TransHistory
            deal = order.histories.filter(action=TransHistory.ACTION_EDIT).order_by('-id').first()
            if not deal:
                return JsonResponse({'error': '调整记录不存在'}, status=400)
            risk_before = order.risk_amount
            deal.delete()
            # 从剩余最新一笔 history 恢复快照（target/stop/risk/win/profit）
            last_deal = order.histories.order_by('-id').first()
            if last_deal:
                order.target_price = last_deal.target_price
                order.stop_price = last_deal.stop_price
                order.risk_amount = last_deal.risk_amount
                order.win_ratio = last_deal.win_ratio
                order.profit = last_deal.profit
            order.save()
            risk_after = order.risk_amount
            config.risk -= (risk_before - risk_after)
            if config.risk < 0:
                config.risk = Decimal('0')
            config.save()
            latest.delete()
        elif latest.event == CashHistory.EVENT_DIVIDEND:
            # 撤回分红（支持同时包含现金分红和送股）
            order = latest.order
            if not order:
                return JsonResponse({'error': '关联交易订单不存在'}, status=400)
            # 查找对应的分红记录
            dividend = DividendRecord.objects.filter(order=order).order_by('-id').first()
            if not dividend:
                return JsonResponse({'error': '分红记录不存在'}, status=400)

            # 1. 现金分红撤销：恢复资金（分红不算收益，不修改 profit）
            if dividend.amount > 0:
                amount = dividend.amount
                config.cash -= amount
                config.stock += amount  # 恢复折减的成本市值
                config.total = config.cash + config.stock

            # 2. 先删除分红记录（确保 recalculate 时累计现金分红不包含这笔分红）
            dividend.delete()

            # 3. 删除分红对应的 TransHistory 记录（现金分红和送股都有记录）
            deal = order.histories.filter(action=TransHistory.ACTION_DIVIDEND).order_by('-id').first()
            if deal:
                deal.delete()

            # 4. 重新计算持仓（position_cost/avg_cost/sold_cost/buy_qty/sell_qty 等全部重算）
            order.recalculate()

            # 5. 从剩余最新一笔 history 恢复快照（目标价/止损价/风险资金/盈利机会等）
            last_deal = order.histories.order_by('-id').first()
            if last_deal:
                order.target_price = last_deal.target_price
                order.stop_price = last_deal.stop_price
                order.risk_amount = last_deal.risk_amount
                order.win_ratio = last_deal.win_ratio
                order.profit = last_deal.profit

            # 6. 更新 config.stock（根据当前持仓成本）
            config.stock = order.position_cost_no_fee
            config.total = config.cash + config.stock

            order.save()
            config.save()
            latest.delete()
        else:
            # 撤回买入/卖出交易
            order = latest.order
            if not order:
                return JsonResponse({'error': '关联交易订单不存在'}, status=400)

            # 获取要删除的 TransHistory（该 order 最新一笔非 edit 记录）
            deal = order.histories.exclude(action=TransHistory.ACTION_EDIT).order_by('-id').first()
            if not deal:
                return JsonResponse({'error': '交易记录不存在'}, status=400)

            # 记录删除前的状态（必须在删除前判断）
            order.refresh_from_db()
            was_closed = (order.status == TransOrder.STATUS_CLOSED)
            risk_before = order.risk_amount

            # 删除该笔交易记录
            deal.delete()

            remaining = order.histories.exclude(action=TransHistory.ACTION_EDIT).count()
            if remaining == 0:
                # 首次交易被撤回：恢复 focus 状态，删除 order（同时删除所有 edit 记录和 ReviewList）
                focus = order.focus
                if focus and focus.status == FocusStock.STATUS_CLOSED and focus.close_reason == FocusStock.CLOSE_REASON_BOUGHT:
                    focus.status = FocusStock.STATUS_WATCHING
                    focus.close_reason = ''
                    focus.close_date = None
                    focus.save()
                # ReviewList 会因为 on_delete=CASCADE 自动删除
                order.delete()
                config.stock = Decimal('0')
                risk_after = Decimal('0')
            else:
                # 重新计算 order
                order.recalculate()
                # 从剩余最新一笔 history 恢复快照（target/stop/risk/win/profit）
                last_deal = order.histories.order_by('-id').first()
                if last_deal:
                    order.target_price = last_deal.target_price
                    order.stop_price = last_deal.stop_price
                    order.risk_amount = last_deal.risk_amount
                    order.win_ratio = last_deal.win_ratio
                    order.profit = last_deal.profit
                else:
                    order.risk_amount = Decimal('0')
                    order.win_ratio = 0
                order.save()
                config.stock = order.position_cost_no_fee
                risk_after = order.risk_amount
                # 撤销前已清仓 → 撤销后恢复持仓，删除对应的 ReviewList
                if was_closed:
                    ReviewList.objects.filter(trans_order=order).delete()

            # 恢复 CashConfig
            if latest.event == CashHistory.EVENT_BUY:
                config.cash += abs(latest.change)
            else:
                config.cash -= latest.change
            config.total = config.cash + config.stock
            risk_change = risk_before - risk_after
            config.risk -= risk_change
            if config.risk < 0:
                config.risk = Decimal('0')
            config.profit -= latest.current_profit
            config.save()

            # 删除资金历史记录
            latest.delete()

    return JsonResponse({'msg': 'done'})


# ===================== 初始化资金 =====================
@require_http_methods(["POST"])
def cash_init(request):
    """
    首次使用时初始化资金配置 + 写入初始存入记录
    POST JSON: {date, cash, stock, allowance}
    """
    if CashConfig.has_config():
        return JsonResponse({'error': '已初始化，请勿重复提交'}, status=400)
    try:
        params = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '无效JSON'}, status=400)
    date_str = params.get('date', '')
    try:
        init_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return JsonResponse({'error': '日期格式应为 YYYY-MM-DD'}, status=400)
    try:
        cash_val = Decimal(str(params.get('cash', 0)))
        stock_val = Decimal(str(params.get('stock', 0)))
        allowance_val = Decimal(str(params.get('allowance', 0)))
    except Exception:
        return JsonResponse({'error': '金额格式错误'}, status=400)
    if cash_val < 0 or stock_val < 0 or allowance_val < 0:
        return JsonResponse({'error': '金额不能为负'}, status=400)

    total_val = cash_val + stock_val
    with transaction.atomic():
        config = CashConfig(pk=1)
        config.total = total_val.quantize(Decimal('0.01'))
        config.cash = cash_val.quantize(Decimal('0.01'))
        config.stock = stock_val.quantize(Decimal('0.01'))
        config.allowance = allowance_val.quantize(Decimal('0.01'))
        config.risk = Decimal('0')
        config.profit = Decimal('0')
        config.save()
        # 写入初始存入记录（初始化无收益）
        CashHistory.snapshot(
            event=CashHistory.EVENT_DEPOSIT,
            change=total_val,
            current_profit=0,
            remark='初始资金',
            date=init_date,
        )
    return JsonResponse({'msg': 'done'})


# ===================== 变更风险额度 =====================
@require_http_methods(["POST"])
def cash_quota(request):
    """
    手动修改风险额度（allowance）
    POST JSON: {amount: 100000}
    """
    try:
        params = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': '无效JSON'}, status=400)
    try:
        amount = Decimal(str(params.get('amount', 0)))
    except Exception:
        return JsonResponse({'error': '金额格式错误'}, status=400)
    if amount < 0:
        return JsonResponse({'error': '风险额度不能为负'}, status=400)
    config = CashConfig.get_config()
    config.allowance = amount.quantize(Decimal('0.01'))
    config.save()
    return JsonResponse({'msg': 'done', 'allowance': float(config.allowance)})
