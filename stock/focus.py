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
from .forms.forms import FocusStockForm
from . import cash, func, chart
from .models.models import CashConfig, StockList, FocusStock
from django.db import connection, transaction


# ===================== 关注清单 =====================
def focus_list(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        if data.get('action') == 'sort':
            ordered_codes = data.get('codes', [])
            for i, c in enumerate(ordered_codes):
                # 排序从 1 开始
                FocusStock.objects.filter(code=c[0], market=c[1]).update(sort_order=i+1)
            return JsonResponse({'msg': 'done'})

        result = []
        focus_qs = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING)
        for fs in focus_qs:
            deci = 2 if fs.cat == 'stock' else 3
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
    for fs in focus_qs:
        deci = 2 if fs.cat == 'stock' else 3
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
    return render(request, 'focus-list.html', {
        'list': items,
        'interval': trend.QUOTE_REQUEST_INTERVAL
    })


def focus_plus(request):
    code, name, market, cat = None, None, None, 'stock'

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
                focus = form.save(commit=False)
                focus.code = code
                focus.market = market
                focus.win_ratio = _calc_win_ratio(focus.plan_price, focus.target_price, focus.stop_price)
                focus.allowed_qty = cash.calc_allowed_qty(focus.plan_price)
                max_sort = FocusStock.objects.filter(status=FocusStock.STATUS_WATCHING).count()
                focus.sort_order = max_sort
                focus.save()
                focus.save_history(action='create')
                return redirect('focus_view', market=focus.market, code=focus.code)
    else:
        initial = {}
        form = FocusStockForm(initial=initial)
    
    chart_init = {
        'site': 'focus/plus',
        'code': code,
        'market': market,
        'name': name,
        'cat': cat
    }

    page_config = chart.get_page_config(request.session, 'focus/plus1', cat)
    chart_init.update(page_config)

    return render(request, 'focus-plus.html', {
        'form': form, 
        'available': CashConfig.get_config().available,  
        # 需转换为 JSON 字符串
        'chart': json.dumps(chart_init)   
    })


def focus_view(request, market, code):
    print(code)


@require_http_methods(["GET"])
def stock_name_api(request):
    code = request.GET.get('code', '').strip()
    market = request.GET.get('market', '').strip().upper()
    if not code or not market:
        # 前台仅要求返回 name，code 与 market 非必须
        return JsonResponse({'code': code, 'market': market, 'name': ''})
    
    # 数据库查询
    try:
        stock = StockList.objects.filter(code=code, market=market).first()
        if stock:
            return JsonResponse({'code': code, 'market': market, 'name': stock.name})
    except Exception:
        pass

    # 数据库中不存在，尝试更新股票列表
    _update_stock_list()

    # 再次从数据库查询
    try:
        stock = StockList.objects.filter(code=code, market=market).first()
        if stock:
            return JsonResponse({'code': code, 'market': market, 'name': stock.name})
        else:
            return JsonResponse({'code': code, 'market': market, 'name': ''})
    except Exception:
        return JsonResponse({'code': code, 'market': market, 'name': ''})
        

def _calc_win_ratio(buy_price, target_price, stop_price):
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


def _update_stock_list():
    """
    从 tushare 获取最新股票基础信息，更新到本地 StockList 表
    映射规则：
        symbol -> code
        name   -> name
        exchange -> market (SSE->SH, SZSE->SZ, BSE->BJ)
        industry -> industry
    """
    # 交易所映射字典
    EXCHANGE_MAP = {
        'SSE': 'SH',    # 上海证券交易所
        'SZSE': 'SZ',   # 深圳证券交易所
        'BSE': 'BJ',    # 北京证券交易所
    }

    try:
        # 获取原始数据
        df = tushare.get_stock_basic()
        if df is None or df.empty:
            return

        # 重命名列以匹配模型字段
        df.rename(columns={'symbol': 'code'}, inplace=True)
        # 映射交易所代码
        df['market'] = df['exchange'].map(EXCHANGE_MAP)
        # 删除未匹配的行
        df = df.dropna(subset=['market'])

        # 若 industry 为 NaN，填充为空字符串
        df['industry'] = df['industry'].fillna('')
        
        # 事务保护：清空+批量插入，中途异常自动回滚
        with transaction.atomic():
            # 先清空旧数据
            StockList.objects.all().delete()
            # SQLite 重置自增 ID
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM sqlite_sequence WHERE name='models_stock_list';")

            # 批量插入（每批 1000 条，避免一次性插入过多）
            batch_size = 1000
            instances = []
            for _, row in df.iterrows():
                instances.append(StockList(
                    code=row['code'],
                    name=row['name'],
                    market=row['market'],
                    industry=row['industry']
                ))
                if len(instances) >= batch_size:
                    StockList.objects.bulk_create(instances)
                    instances.clear()
            if instances:
                StockList.objects.bulk_create(instances)

    except Exception as e:
        print(f"更新股票列表失败: {e}")
        

# 备用
def _market_of(code):
    """
    仅简单判断，对于指数需要手动选择
    """
    code = str(code)
    if code.startswith(('60', '68', '11', '12', '5')):
        return 'SH'
    if code.startswith(('00', '30', '15', '16')):
        return 'SZ'
    if code.startswith(('8', '4')):
        return 'BJ'
    return 'SH'
