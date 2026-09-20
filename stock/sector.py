import json
import decimal
import datetime
import threading
from .fetch import kline, trend
from .fetch import tushare
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_http_methods
from .models.models import SectorList, StockSector
from django.db import connection, transaction
from django.core.cache import cache
import pytz
from . import func, chart


def sector_list(request):
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            from django.http import JsonResponse
            return JsonResponse({'status': 'error', 'message': '无效JSON'}, status=400)
        if 'page' in data:
            func.set_cache(request.session, 'sector-list-page', int(data['page']))
        if 'per_page' in data:
            func.set_page_size(request.session, data['per_page'])
        if 'mark_filter' in data:
            func.set_cache(request.session, 'sector-list-mark-filter', data['mark_filter'])
            func.set_cache(request.session, 'sector-list-page', 1)  # 切换标记筛选时重置到第1页
        from django.http import JsonResponse
        return JsonResponse({'status': 'success'})

    items = []
    sector_qs = SectorList.objects.all().order_by('code')

    if not sector_qs:
        _update_sector_list()
        sector_qs = SectorList.objects.all().order_by('code')

    # 标记筛选（后端过滤，与筛选清单一致）
    mark_filter = func.get_cache(request.session, 'sector-list-mark-filter', 'all')
    if mark_filter not in ('all', '1', '2'):
        mark_filter = 'all'
    if mark_filter in ('1', '2'):
        sector_qs = sector_qs.filter(mark=mark_filter)

    # 统一分页
    pg = func.paginate_queryset(request, sector_qs, 'sector-list-page')

    # 全局连续序号（跨页连续，如第2页从11开始）
    base_no = (pg['current_page'] - 1) * pg['per_page']
    for idx, fs in enumerate(pg['items']):
        items.append({
            'no': base_no + idx + 1,
            'id': fs.id,
            'code': fs.code,
            'name': fs.name,
            'market': fs.market,
            'cat': fs.cat,
            'mark': fs.mark
        })

    func.set_view_back(request.session, '/sector/list')
    # 标记筛选后的全量列表作为 view 的自定义 navi（跨页切换）
    custom_navi = [(r.code, r.market) for r in sector_qs]
    func.set_cache(request.session, 'sector-view-custom-navi', custom_navi)
    # 失效旧导航缓存，确保 view 页面用新的 custom_navi 重新生成 navi
    func.delete_cache(request.session, '/sector/view-navi-data')

    return render(request, 'sector-list.html', {
        'list': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'page_size_choices': func.PAGE_SIZE_CHOICES,
        'current_mark_filter': mark_filter,
    })


def sector_view(request, market, code):
    site = '/sector/view'

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效JSON'}, status=400)

        # 设置返回来源（从 stock_sectors 进入板块 view 时使用）
        if 'set_back' in data:
            func.set_view_back(request.session, data['set_back'])
            return JsonResponse({'status': 'success'})

        if data.get('func') == 'major':
            try:
                sector = SectorList.objects.get(code=code)
                sector.mark = '1' if sector.mark != '1' else ''
                sector.save()
                mark = {'status': 'success', 'major': sector.mark}
            except SectorList.DoesNotExist:
                mark = {'status': 'error', 'message': '代码不存在'}
        elif data.get('func') == 'minor':
            try:
                sector = SectorList.objects.get(code=code)
                sector.mark = '2' if sector.mark != '2' else ''
                sector.save()
                mark = {'status': 'success', 'minor': sector.mark}
            except SectorList.DoesNotExist:
                mark = {'status': 'error', 'message': '代码不存在'}
        else:
            mark = {'status': 'error', 'message': '未知操作'}

        return JsonResponse(mark)
    else:
        navi_data = func.get_cache(request.session, f'{site}-navi-data', {})
        if (site, code, market) != navi_data.get('site_code_market', None):
            navi_data = chart.set_navi_data(request.session, site, code, market, None, 'init')
        
        func.set_cache(request.session, 'view', 'kline') 

        sector = SectorList.objects.filter(code=code).first()
        # 图表配置
        chart_init = {
            'site': site,
            'code': code,
            'market': market,
            'name': sector.name,
            'cat': sector.cat,
            'view': 'kline',
            'backUrl': func.get_view_back(request.session) or '/sector/list',
        }

        return render(request, 'sector-view.html', {'chart': json.dumps(chart_init)})


def stocks_list(request, market, code):
    """板块股票清单：显示该板块的所有成分股（从 StockSector 查询，复用 filter-list.html 模板）"""
    site = f'/stocks/list/{market}/{code}'

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'status': 'error', 'message': '无效JSON'}, status=400)
        if 'page' in data:
            func.set_cache(request.session, f'sector-stocks-{code}-page', int(data['page']))
        if 'per_page' in data:
            func.set_page_size(request.session, data['per_page'])
        return JsonResponse({'status': 'success'})

    # 获取板块信息
    sector = SectorList.objects.filter(code=code).first()
    if not sector:
        return redirect('/sector/list')

    # 从 StockSector 查询该板块下的所有股票，关联 StockList 获取详情
    from .models.models import StockList, FocusStock, StockSector
    sector_stocks = StockSector.objects.filter(sector_code=code).select_related()
    stock_codes_markets = [(ss.stock_code, ss.stock_market) for ss in sector_stocks]

    # 构建股票列表（过滤已 hide）
    stocks = []
    for sc, sm in stock_codes_markets:
        stock = StockList.objects.filter(code=sc, market=sm).first()
        if stock and stock.hide != '1':
            stocks.append({'code': sc, 'market': sm, 'name': stock.name})

    # 分页（list 也支持，code_getter 从 dict 取 code）
    pg = func.paginate_queryset(
        request, stocks, f'sector-stocks-{code}-page',
        code_getter=lambda x: x['code']
    )

    # 构建 items（含序号、关注状态、标记）
    base_no = (pg['current_page'] - 1) * pg['per_page']
    items = []
    for idx, s in enumerate(pg['items']):
        focused = FocusStock.objects.filter(code=s['code'], market=s['market'], status=FocusStock.STATUS_WATCHING).exists()
        stock = StockList.objects.filter(code=s['code'], market=s['market']).first()
        mark = stock.mark if stock else ''
        items.append({
            'no': base_no + idx + 1,
            'code': s['code'],
            'market': s['market'],
            'name': s['name'],
            'focused': focused,
            'mark': mark,
        })

    # 设置返回来源和自定义 navi（板块股票全量列表，供 view 页面 navi 跨页切换）
    func.set_view_back(request.session, site)
    custom_navi = [(s['code'], s['market']) for s in stocks]
    func.set_cache(request.session, 'stocks-view-custom-navi', custom_navi)
    func.delete_cache(request.session, '/stocks/view-navi-data')

    return render(request, 'filter-list.html', {
        'items': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'page_size_choices': func.PAGE_SIZE_CHOICES,
        'current_mark_filter': 'all',
        'pagination_url': site,
        'view_url_prefix': '/stocks/view',
        'page_title': f'{sector.name} - 板块股票',
    })


def stock_sectors(request, market, code):
    """股票所属板块列表：显示该股票对应的所有板块（用 sector-list.html 渲染，分页）"""
    from .models.models import StockSector

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'status': 'error', 'message': '无效JSON'}, status=400)
        # 设置返回来源（从股票 view 进入时调用）
        if 'set_back' in data:
            func.set_view_back(request.session, data['set_back'])
            return JsonResponse({'status': 'success'})
        if 'page' in data:
            func.set_cache(request.session, f'stock-sectors-{code}-page', int(data['page']))
        if 'per_page' in data:
            func.set_page_size(request.session, data['per_page'])
        return JsonResponse({'status': 'success'})

    # 从 StockSector 查询该股票的所有板块
    sector_relations = StockSector.objects.filter(stock_code=code, stock_market=market)

    # 兜底：若 StockSector 中无数据，调用 get_industry_member 获取并更新数据库
    if not sector_relations.exists():
        try:
            df = tushare.get_industry_member(f'{code}.{market}')
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    l1_code = row.get('l1_code', '')
                    if not l1_code or '.' not in l1_code:
                        continue
                    sec_code, sec_cat = l1_code.split('.', 1)
                    sec_market = 'SW' if sec_cat == 'SI' else sec_cat
                    StockSector.objects.get_or_create(
                        stock_code=code,
                        stock_market=market,
                        sector_code=sec_code,
                        sector_market=sec_market,
                    )
                sector_relations = StockSector.objects.filter(stock_code=code, stock_market=market)
        except Exception as e:
            print(f"[stock_sectors] 兜底获取板块失败: {e}")

    # 关联 SectorList 获取板块详情
    sector_codes = [sr.sector_code for sr in sector_relations]
    sector_qs = SectorList.objects.filter(code__in=sector_codes).order_by('code')

    # 统一分页
    pg = func.paginate_queryset(request, sector_qs, f'stock-sectors-{code}-page')

    # 全局连续序号
    base_no = (pg['current_page'] - 1) * pg['per_page']
    items = []
    for idx, fs in enumerate(pg['items']):
        items.append({
            'no': base_no + idx + 1,
            'id': fs.id,
            'code': fs.code,
            'name': fs.name,
            'market': fs.market,
            'cat': fs.cat,
            'mark': fs.mark,
        })

    # 设置返回来源（股票 view 页面）
    back_url = func.get_view_back(request.session) or '/focus/list'
    func.set_view_back(request.session, back_url)

    # 标记筛选后的全量列表作为 view 的自定义 navi
    custom_navi = [(r.code, r.market) for r in sector_qs]
    func.set_cache(request.session, 'sector-view-custom-navi', custom_navi)
    func.delete_cache(request.session, '/sector/view-navi-data')

    return render(request, 'sector-list.html', {
        'list': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'page_size_choices': func.PAGE_SIZE_CHOICES,
        'current_mark_filter': 'all',
        'from_stock_sectors': True,
        'stock_code': code,
        'stock_market': market,
    })


def _update_sector_list():
    """
    从 tushare 获取板块列表，更新到本地 SecotrList 表
    """

    try:
        df = tushare.get_all_industry()
        if df is None or df.empty:
            return

        df.rename(columns={'index_code': 'code'}, inplace=True)
        df.rename(columns={'industry_name': 'name'}, inplace=True)

        with transaction.atomic():
            for _, row in df.iterrows():
                code, cat = row['code'].split('.')
                # 先尝试查询现有记录
                sector = SectorList.objects.filter(
                    code=code
                ).first()
                if sector:
                    # 存在则更新
                    sector.name = row['name']
                    sector.save()
                else:
                    # 不存在则创建
                    SectorList.objects.create(
                        code=code,
                        name=row['name'],
                        # 申万行业列表
                        market='SW',
                        cat=cat
                    )
    except Exception as e:
        print(f"更新板块列表失败: {e}")


def rebuild_stock_sector(request):
    """重建板块关联：清空 StockSector，后台异步全量重建"""
    if request.method != 'POST':
        return JsonResponse({'error': '仅支持POST'}, status=405)
    try:
        # 清空现有数据（触发 _update_stock_sector 的全量模式）
        StockSector.objects.all().delete()
        # 后台异步执行全量重建
        t = threading.Thread(target=func._update_stock_sector, args=([],), daemon=True)
        t.start()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

