# -*- coding: utf-8 -*-
"""
交易计算工具 + 资金页面
- 允许购买数量
- 交易费用（佣金/印花税）
- 风险资金、盈亏比
- 小数位处理
- 资金总览页面（当前状态 + 历史变化图）
"""
import json
import datetime
from decimal import Decimal, ROUND_HALF_UP
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from .models.models import CashConfig, CashHistory
from .forms.forms import CashConfigForm
from . import func


# ===================== 资金总览页面 =====================
def cash_view(request):
    """资金页面：当前状态 + 历史变化图"""
    initialized = CashConfig.has_config()
    config = CashConfig.get_config()
    # 最近一条历史记录用于展示
    latest_history = CashHistory.objects.first()
    # 可撤回的记录ID：仅当最新一条为存入/取出时
    revocable_id = latest_history.id if latest_history and latest_history.event in (CashHistory.EVENT_DEPOSIT, CashHistory.EVENT_WITHDRAW) else None
    # 分页 / 每页数量 / 日期范围（POST 提交时更新 session）
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            data = request.POST
        if 'page' in data:
            func.set_cache(request.session, 'cash-history-page', int(data['page']))
        if 'per_page' in data:
            func.set_cache(request.session, 'cash-per-page', int(data['per_page']))
        if 'start_date' in data:
            func.set_cache(request.session, 'cash-start-date', str(data['start_date']))
        # 结束日期存入 session，同时记录设置日期（仅当天有效，跨天自动失效）
        if 'end_date' in data and data['end_date']:
            func.set_cache(request.session, 'cash-end-date', str(data['end_date']))
            func.set_cache(request.session, 'cash-end-date-set-day', datetime.date.today().strftime('%Y-%m-%d'))
        return JsonResponse({'status': 'ok'})
    # 日期范围：起始日期持久化；结束日期当天有效，跨天自动恢复为当天
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    # 默认起始日期：去年今天 + 1天（Python日期运算自动处理大小月/闰年进位）
    try:
        _last_year_today = today.replace(year=today.year - 1)
    except ValueError:
        _last_year_today = today.replace(year=today.year - 1, day=28)
    default_start = (_last_year_today + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    start_str = str(func.get_cache(request.session, 'cash-start-date', default_start))
    # 结束日期：检查设置日期是否为今天，是则用存储值，否则清除并用当天
    end_set_day = str(func.get_cache(request.session, 'cash-end-date-set-day', ''))
    if end_set_day == today_str:
        end_str = str(func.get_cache(request.session, 'cash-end-date', today_str))
    else:
        # 跨天了，清除结束日期相关 session
        if 'cash-end-date' in request.session:
            del request.session['cash-end-date']
        if 'cash-end-date-set-day' in request.session:
            del request.session['cash-end-date-set-day']
        end_str = today_str
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
    history_qs = CashHistory.objects.filter(date__gte=start_date, date__lte=end_date).order_by('-date', '-id')
    cash_per_page = int(func.get_cache(request.session, 'cash-per-page', str(func.DEFAULT_PAGE_SIZE)))
    pg = func.paginate_queryset(request, history_qs, 'cash-history-page', per_page=cash_per_page)
    # 计算每条记录的本次收益 = 当前profit - 前一条profit（按正序计算，第一条为None）
    items = list(pg['items'])
    items_asc = sorted(items, key=lambda h: (h.date, h.id))
    prev_profit = None
    for h in items_asc:
        if prev_profit is None:
            h.current_profit = None
        else:
            h.current_profit = h.profit - prev_profit
        prev_profit = h.profit
    return render(request, 'cash-view.html', {
        'config': config,
        'initialized': initialized,
        'latest': latest_history,
        'revocable_id': revocable_id,
        'history_list': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'start_date': start_str,
        'end_date': end_str,
    })


@require_http_methods(["GET"])
def cash_history_api(request):
    """返回资金历史数据（供前端 Highcharts 绘制），支持 start/end 日期范围过滤"""
    start_str = request.GET.get('start', '')
    end_str = request.GET.get('end', '')
    qs = CashHistory.objects.all().order_by('date', 'id')
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
        profit_series.append([date_str, float(h.profit)])
        reasons.append({
            'date': date_str,
            'event': h.get_event_display(),
            'amount': float(h.amount),
            'remark': h.remark,
            'total': float(h.total),
            'cash': float(h.cash),
            'stock': float(h.stock),
            'profit': float(h.profit),
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
    # 快照写入历史
    CashHistory.snapshot(event=event, amount=change_amount, remark=remark, date=adjust_date)
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
    撤回最近一笔存入/取出记录（仅当该记录是最新一条且为存入/取出时允许）
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
    if latest.event not in (CashHistory.EVENT_DEPOSIT, CashHistory.EVENT_WITHDRAW):
        return JsonResponse({'error': '仅可撤回存入/取出记录'}, status=400)

    config = CashConfig.get_config()
    amount = abs(latest.amount)
    if latest.event == CashHistory.EVENT_DEPOSIT:
        # 撤回存入：现金减少
        config.cash -= amount
    else:
        # 撤回取出：现金增加
        config.cash += amount
    config.total = config.cash + config.stock
    config.save()
    latest.delete()
    return JsonResponse({'msg': 'done'})


# ===================== 初始化资金 =====================
@require_http_methods(["POST"])
def cash_init(request):
    """
    首次使用时初始化资金配置 + 写入初始存入记录
    POST JSON: {date, cash, stock, allowance, commission_ratio, commission_min, stamp_buy_ratio, stamp_sell_ratio}
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
        commission_ratio_val = Decimal(str(params.get('commission_ratio', 0)))
        commission_min_val = Decimal(str(params.get('commission_min', 0)))
        stamp_buy_val = Decimal(str(params.get('stamp_buy_ratio', 0)))
        stamp_sell_val = Decimal(str(params.get('stamp_sell_ratio', 0)))
    except Exception:
        return JsonResponse({'error': '金额格式错误'}, status=400)
    if cash_val < 0 or stock_val < 0 or allowance_val < 0:
        return JsonResponse({'error': '金额不能为负'}, status=400)

    total_val = cash_val + stock_val
    config = CashConfig(pk=1)
    config.total = total_val.quantize(Decimal('0.01'))
    config.cash = cash_val.quantize(Decimal('0.01'))
    config.stock = stock_val.quantize(Decimal('0.01'))
    config.allowance = allowance_val.quantize(Decimal('0.01'))
    config.risk = Decimal('0')
    config.profit = Decimal('0')
    config.commission_ratio = commission_ratio_val
    config.commission_min = commission_min_val
    config.stamp_buy_ratio = stamp_buy_val
    config.stamp_sell_ratio = stamp_sell_val
    config.save()
    # 写入初始存入记录
    CashHistory.snapshot(
        event=CashHistory.EVENT_DEPOSIT,
        amount=total_val,
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


# ===================== 账户设置（保留旧接口） =====================
def cash_setting(request):
    config = CashConfig.get_config()
    if request.method == 'POST':
        form = CashConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            # 总资产始终等于现金+股票
            config.total = config.cash + config.stock
            config.save()
            return redirect('cash_setting')
    else:
        form = CashConfigForm(instance=config)
    return render(request, 'stock/setting.html', {'form': form})


# ===================== 计算工具函数 =====================
def _q(value, places='0.01'):
    """统一四舍五入到两位小数"""
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def calc_allowed_qty(plan_price, stop_price=0):
    """
    计算允许购买数量（按手取整），取现金限制和风险额度限制的较小值
    :param plan_price: 计划买入价
    :param stop_price: 止损价
    :return: int 股数
    """
    config = CashConfig.get_config()
    price = Decimal(str(plan_price))
    # 现金限制
    if price <= 0 or config.cash <= 0:
        by_cash = 0
    else:
        by_cash = int(config.cash / price)
    # 风险额度限制
    remaining = config.allowance - config.risk
    risk_per_share = price - Decimal(str(stop_price or 0))
    if remaining <= 0 or risk_per_share <= 0:
        by_risk = 0
    else:
        by_risk = int(remaining / risk_per_share)
    max_qty = min(by_cash, by_risk)
    # 向下取整（1手100股）
    return (max_qty // 100) * 100


def calc_commission(amount, commission_rate, min_commission):
    """
    计算佣金（不足最低佣金按最低收取）
    :param amount: 成交金额 Decimal
    :param commission_rate: 佣金费率
    :param min_commission: 最低佣金
    :return: Decimal
    """
    amount = Decimal(str(amount))
    rate = Decimal(str(commission_rate))
    minimum = Decimal(str(min_commission))
    commission = amount * rate
    return _q(commission if commission >= minimum else minimum)


def calc_stamp_tax(amount, stamp_tax_rate):
    """
    计算印花税（仅卖出收取）
    :param amount: 成交金额 Decimal
    :param stamp_tax_rate: 印花税率
    :return: Decimal
    """
    return _q(Decimal(str(amount)) * Decimal(str(stamp_tax_rate)))


def calc_fee(amount, intent, config):
    """
    计算交易费用
    :param amount: 成交金额
    :param intent: 'B'买入 / 'S'卖出
    :param config: CashConfig 实例
    :return: dict {commission, stamp_tax, total}
    """
    amount = Decimal(str(amount))
    commission = calc_commission(amount, config.commission_ratio, config.commission_min)
    stamp_tax = Decimal('0')
    if intent == 'S':
        stamp_tax = calc_stamp_tax(amount, config.stamp_sell_ratio)
    total = _q(commission + stamp_tax)
    return {
        'commission': _q(commission),
        'stamp_tax': stamp_tax,
        'total': total,
    }


def calc_risk_capital(buy_price, stop_price, qty):
    """
    风险资金 = (买入价 - 止损价) × 数量
    买入价低于止损价时返回0
    """
    buy = Decimal(str(buy_price))
    stop = Decimal(str(stop_price))
    qty = int(qty)
    if buy <= stop or qty <= 0:
        return Decimal('0')
    return _q((buy - stop) * qty)


def calc_risk_reward_ratio(buy_price, target_price, stop_price):
    """
    盈亏比 = (目标价 - 买入价) / (买入价 - 止损价)
    :return: Decimal，无效时返回0
    """
    buy = Decimal(str(buy_price))
    target = Decimal(str(target_price))
    stop = Decimal(str(stop_price))
    if buy <= 0 or buy <= stop or target <= buy:
        return Decimal('0')
    return _q((target - buy) / (buy - stop))


def calc_estimated_profit(sell_price, qty, avg_cost, fee):
    """
    卖出预计盈亏 = (卖出价 - 持仓均价) × 数量 - 费用
    """
    sell = Decimal(str(sell_price))
    cost = Decimal(str(avg_cost))
    qty = int(qty)
    fee = Decimal(str(fee))
    return _q((sell - cost) * qty - fee)


def calc_amount(price, qty):
    """成交金额 = 价格 × 数量"""
    return _q(Decimal(str(price)) * int(qty))


def get_price_decimal(code):
    """
    根据股票代码判断价格小数位
    A股股票 2位，可转债/基金3位
    """
    code = str(code).upper()
    # 沪市转债 11xxxx，深市转债 12xxxx
    if code.startswith('11') or code.startswith('12'):
        return 3
    return 2


def calc_win_ratio(buy_price, target_price, stop_price):
    """计算成功几率（0-99整数）"""
    try:
        buy = float(buy_price or 0)
        target = float(target_price or 0)
        stop = float(stop_price or 0)
    except (TypeError, ValueError):
        return 0
    if buy <= 0:
        return 0
    if stop >= buy:
        return 99
    if target <= buy:
        return 0
    prob = round((target - buy) / (target - stop) * 99)
    return max(0, min(99, prob))
