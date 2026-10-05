import threading
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from ..fetch import tushare
from ..models import StockList
from ..utils import _update_stock_sector


@require_http_methods(["GET"])
def stock_name_api(request):
    code = request.GET.get('code', '').strip()
    market = request.GET.get('market', '').strip().upper()
    cat = request.GET.get('cat', 'stock').strip().lower()
    if not code or not market:
        # 前台仅要求返回 name，code 与 market 非必须
        return JsonResponse({'code': code, 'market': market, 'name': ''})

    # 指数类型：直接查询tushare，不存入StockList
    if cat == 'index':
        try:
            df = tushare.get_index_by_code(f'{code}.{market}')
            if df is not None and not df.empty:
                index_name = df.iloc[0].get('name', '')
                return JsonResponse({'code': code, 'market': market, 'name': index_name, 'cat': 'index'})
        except Exception as e:
            print(f"指数查询失败 {code}.{market}: {e}")
        return JsonResponse({'code': code, 'market': market, 'name': '', 'cat': ''})

    # 股票类型：数据库查询
    try:
        stock = StockList.objects.filter(code=code, market=market).first()
        if stock:
            return JsonResponse({'code': code, 'market': market, 'name': stock.name, 'cat': stock.cat})
    except Exception:
        pass

    # 数据库中不存在，单只查询tushare并增量存入
    try:
        EXCHANGE_MAP = {'SSE': 'SH', 'SZSE': 'SZ', 'BSE': 'BJ'}
        df = tushare.get_stock_by_code(f'{code}.{market}')
        if df is not None and not df.empty:
            row = df.iloc[0]
            stock_name = row.get('name', '')
            industry = row.get('industry', '') or ''
            # 增量存入StockList（不影响已有数据）
            StockList.objects.get_or_create(
                code=code, market=market,
                defaults={'name': stock_name, 'cat': 'stock', 'industry': industry}
            )
            # 异步增量更新板块关联
            t = threading.Thread(target=_update_stock_sector, args=([(code, market)],), daemon=True)
            t.start()
            return JsonResponse({'code': code, 'market': market, 'name': stock_name, 'cat': 'stock'})
    except Exception as e:
        print(f"单只股票查询失败 {code}.{market}: {e}")

    return JsonResponse({'code': code, 'market': market, 'name': '', 'cat': ''})
