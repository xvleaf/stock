import json
import decimal
import datetime
from .fetch import kline, trend
from .fetch import tushare
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_http_methods
from .models.models import SectorList
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
    sector_qs = SectorList.objects.exclude(hide='1').order_by('code')

    if not sector_qs:
        _update_sector_list()
        sector_qs = SectorList.objects.all().exclude(hide='1').order_by('code')

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
        # elif data.get('func') == 'hide':
        else:
            try:
                sector = SectorList.objects.get(code=code)
                # 在剔除前，计算下一只（最后一只则取前一只），供前端不刷新切换
                resp = {'status': 'success', 'hide': '1'}
                custom = func.get_cache(request.session, 'sector-view-custom-navi')
                if custom:
                    navi_list = [tuple(x) for x in custom]
                else:
                    navi_list = list(SectorList.objects.exclude(hide='1').order_by('code').values_list('code', 'market'))
                try:
                    idx = navi_list.index((code, market))
                except ValueError:
                    idx = -1
                remaining = [x for x in navi_list if x != (code, market)]
                if 0 <= idx < len(remaining):
                    nc, nm = remaining[idx]
                    nsec = SectorList.objects.filter(code=nc).first()
                    resp['next'] = {'code': nc, 'market': nm, 'name': nsec.name if nsec else ''}
                elif remaining:
                    pc, pm = remaining[-1]
                    psec = SectorList.objects.filter(code=pc).first()
                    resp['prev'] = {'code': pc, 'market': pm, 'name': psec.name if psec else ''}
                # 隐藏该板块
                sector.hide = '1'
                sector.save()
                # 失效导航缓存
                func.delete_cache(request.session, '/sector/view-navi-data')
                # 更新自定义 navi 列表：移除被 hide 的板块
                if custom:
                    custom_list = [tuple(x) for x in custom if tuple(x) != (code, market)]
                    func.set_cache(request.session, 'sector-view-custom-navi', custom_list)
                mark = resp
            except SectorList.DoesNotExist:
                mark = {'status': 'error', 'message': '代码不存在'}
            
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
    """板块股票清单：显示该板块的所有成分股（复用 filter-list.html 模板）"""
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

    # 从 tushare 获取板块成分股（缓存 2 小时）
    cache_key = f'sector-stocks-{code}'
    stocks = cache.get(cache_key)
    if stocks is None:
        try:
            df = tushare.get_match_industry(f'{code}.{sector.cat}')
            if df is not None and not df.empty:
                stocks = []
                for _, row in df.iterrows():
                    ts_code = row['ts_code']  # 如 600000.SH
                    parts = ts_code.split('.')
                    if len(parts) == 2:
                        stocks.append({'code': parts[0], 'market': parts[1], 'name': row['name']})
                cache.set(cache_key, stocks, timeout=7200)
            else:
                stocks = []
        except Exception as e:
            print(f"获取板块股票失败: {e}")
            stocks = []

    # 过滤掉已 hide 的股票（hide 操作后 tushare 缓存未更新，需实时过滤）
    from .models.models import StockList
    hidden_codes = set(StockList.objects.filter(hide='1').values_list('code', flat=True))
    stocks = [s for s in stocks if s['code'] not in hidden_codes]

    # 分页（list 也支持，code_getter 从 dict 取 code）
    pg = func.paginate_queryset(
        request, stocks, f'sector-stocks-{code}-page',
        code_getter=lambda x: x['code']
    )

    # 构建 items（含序号、关注状态、标记）
    from .models.models import FocusStock
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

