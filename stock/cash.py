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
from decimal import Decimal, ROUND_HALF_UP
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from .models.models import CashConfig, CashHistory
from .forms.forms import CashConfigForm


# ===================== 资金总览页面 =====================
def capital_view(request):
    """资金页面：当前状态 + 历史变化图"""
    config = CashConfig.get_config()
    # 最近一条历史记录用于展示
    latest_history = CashHistory.objects.first()
    # 历史记录列表（最近50条）
    history_list = CashHistory.objects.all()[:50]
    return render(request, 'capital.html', {
        'config': config,
        'latest': latest_history,
        'history_list': history_list,
    })


@require_http_methods(["GET"])
def capital_history_api(request):
    """返回资金历史数据（供前端 Highcharts 绘制）"""
    qs = CashHistory.objects.all().order_by('date', 'id')
    total_series = []
    cash_series = []
    stock_series = []
    reasons = []
    for h in qs:
        # 日期转毫秒时间戳
        ts = int(h.date.strftime('%s')) * 1000
        total_series.append([ts, float(h.total)])
        cash_series.append([ts, float(h.cash)])
        stock_series.append([ts, float(h.stock)])
        reasons.append({
            'ts': ts,
            'reason': h.get_reason_display(),
            'amount': float(h.amount),
            'remark': h.remark,
            'total': float(h.total),
            'cash': float(h.cash),
            'stock': float(h.stock),
        })
    return JsonResponse({
        'total': total_series,
        'cash': cash_series,
        'stock': stock_series,
        'reasons': reasons,
    })


@require_http_methods(["POST"])
def capital_adjust_api(request):
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

    if action not in ('deposit', 'withdraw'):
        return JsonResponse({'error': '不支持的操作'}, status=400)
    if amount <= 0:
        return JsonResponse({'error': '金额必须大于0'}, status=400)

    config = CashConfig.get_config()
    if action == 'deposit':
        config.total += amount
        config.cash += amount
        config.available += amount
        change_amount = amount
        reason = CashHistory.REASON_DEPOSIT
    else:
        if amount > config.cash:
            return JsonResponse({'error': '取出金额超过可用现金'}, status=400)
        config.total -= amount
        config.cash -= amount
        config.available -= amount
        change_amount = -amount
        reason = CashHistory.REASON_WITHDRAW

    config.save()
    # 快照写入历史
    CashHistory.snapshot(reason=reason, amount=change_amount, remark=remark)
    return JsonResponse({
        'msg': 'done',
        'total': float(config.total),
        'cash': float(config.cash),
        'stock': float(config.stock),
        'available': float(config.available),
    })


# ===================== 账户设置（保留旧接口） =====================
def capital_setting(request):
    config = CashConfig.get_config()
    if request.method == 'POST':
        form = CashConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            # 手动调整也记录一条历史
            CashHistory.snapshot(
                reason=CashHistory.REASON_ADJUST,
                amount=Decimal('0'),
                remark='手动调整资金配置'
            )
            return redirect('capital_setting')
    else:
        form = CashConfigForm(instance=config)
    return render(request, 'stock/setting.html', {'form': form})


# ===================== 计算工具函数 =====================
def _q(value, places='0.01'):
    """统一四舍五入到两位小数"""
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def calc_allowed_qty(plan_price):
    """
    根据可用资金和计划买入价计算允许购买数量（按手取整）
    :param plan_price: 计划买入价
    :return: int 股数
    """
    config = CashConfig.get_config()
    capital = Decimal(str(config.available))
    price = Decimal(str(plan_price))
    if price <= 0 or capital <= 0:
        return 0
    max_qty = int(capital / price)
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
