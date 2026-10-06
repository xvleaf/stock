import json
import logging
import threading
from ..fetch import tushare
from django.http import JsonResponse
from django.shortcuts import render, redirect
from ..models import SectorList, StockSector, StockList, FocusStock
from django.db import transaction
from . import chart
from .. import utils

logger = logging.getLogger('stock')


def sector_list(request):
    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        if 'page' in data:
            utils.set_cache(request.session, 'sector-list-page', int(data['page']))
        if 'per_page' in data:
            utils.set_page_size(request.session, data['per_page'])
        if 'mark_filter' in data:
            utils.set_cache(request.session, 'sector-list-mark-filter', data['mark_filter'])
            utils.set_cache(request.session, 'sector-list-page', 1)  # 切换标记筛选时重置到第1页
        return JsonResponse({'status': 'success'})

    items = []
    sector_qs = SectorList.objects.all().order_by('code')

    if not sector_qs:
        _update_sector_list()
        sector_qs = SectorList.objects.all().order_by('code')

    # 标记筛选（后端过滤，与筛选清单一致）
    mark_filter = utils.get_cache(request.session, 'sector-list-mark-filter', 'all')
    if mark_filter not in ('all', '1', '2'):
        mark_filter = 'all'
    if mark_filter in ('1', '2'):
        sector_qs = sector_qs.filter(mark=mark_filter)

    # 统一分页
    pg = utils.paginate_queryset(request, sector_qs, 'sector-list-page')

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

    utils.set_view_back(request.session, '/sector/list')
    # 标记筛选后的全量列表作为 view 的自定义 navi（跨页切换）
    custom_navi = [(r.id, r.code, r.market) for r in sector_qs]
    utils.set_cache(request.session, 'sector-view-custom-navi', custom_navi)
    # 失效旧导航缓存，确保 view 页面用新的 custom_navi 重新生成 navi
    utils.delete_cache(request.session, '/sector/view-navi-data')

    return render(request, 'sector-list.html', {
        'list': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'current_mark_filter': mark_filter,
    })


def sector_view(request, market, code):
    site = '/sector/view'

    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err

        # 设置返回来源（从 stock_sectors 进入板块 view 时使用）
        if 'set_back' in data:
            utils.set_view_back(request.session, data['set_back'])
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
        navi_data = utils.get_cache(request.session, f'{site}-navi-data', {})
        if (site, code, market) != navi_data.get('site_code_market', None):
            navi_data = chart.set_navi_data(request.session, site, code, market, None, 'init')
        
        utils.set_cache(request.session, 'view', 'kline') 

        sector = SectorList.objects.filter(code=code).first()
        # 构建 navi 和 mark 配置（与其他 view 页面一致，否则前端 pageConfig.navi 为 undefined 导致 initPageElements 中断）
        navi_init = chart.get_navi_params(request.session, site, navi_data)
        mark_init = chart.get_mark_config(request.session, site, navi_data)
        # 图表配置
        chart_init = utils.build_chart_init(
            site, code, market, sector.name, sector.cat,
            back_url=utils.get_view_back(request.session) or '/sector/list',
            navi=navi_init, mark=mark_init)

        return render(request, 'sector-view.html', {'chart': json.dumps(chart_init)})


def stocks_list(request, market, code):
    """板块股票清单：显示该板块的所有成分股（从 StockSector 查询，复用 filter-list.html 模板）"""
    site = f'/stocks/list/{market}/{code}'

    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        if 'page' in data:
            utils.set_cache(request.session, f'sector-stocks-{code}-page', int(data['page']))
        if 'per_page' in data:
            utils.set_page_size(request.session, data['per_page'])
        return JsonResponse({'status': 'success'})

    # 获取板块信息
    sector = SectorList.objects.filter(code=code).first()
    if not sector:
        return redirect('/sector/list')

    # 该板块下所有成分股的 (code, market)
    from django.db.models import Q
    pairs = list(StockSector.objects.filter(
        sector_code=code).values_list('stock_code', 'stock_market'))

    # 一次性批量取出 StockList 建映射（消除循环内逐个查询的 N+1）
    q = Q()
    for sc, sm in pairs:
        q |= Q(code=sc, market=sm)
    stock_map = {(s.code, s.market): s for s in StockList.objects.filter(q)}

    # 构建股票列表（过滤已 hide）
    stocks = []
    for sc, sm in pairs:
        stock = stock_map.get((sc, sm))
        if stock and stock.hide != '1':
            stocks.append({'code': sc, 'market': sm, 'name': stock.name})

    # 分页（list 也支持，code_getter 从 dict 取 code）
    pg = utils.paginate_queryset(
        request, stocks, f'sector-stocks-{code}-page',
        code_getter=lambda x: x['code'])

    # 当前页关注状态一次性批量查询（再消除每页逐个 FocusStock 查询）
    page_pairs = [(s['code'], s['market']) for s in pg['items']]
    pq = Q()
    for sc, sm in page_pairs:
        pq |= Q(code=sc, market=sm)
    focused_set = set(FocusStock.objects.filter(
        pq, status=FocusStock.STATUS_WATCHING).values_list('code', 'market'))

    # 构建 items（含序号、关注状态、标记）
    base_no = (pg['current_page'] - 1) * pg['per_page']
    items = []
    for idx, s in enumerate(pg['items']):
        key = (s['code'], s['market'])
        stock = stock_map.get(key)
        items.append({
            'no': base_no + idx + 1,
            'code': s['code'],
            'market': s['market'],
            'name': s['name'],
            'focused': key in focused_set,
            'mark': stock.mark if stock else '',
        })

    # 设置返回来源和自定义 navi（板块股票全量列表，供 view 页面 navi 跨页切换，用索引作临时 id）
    utils.set_view_back(request.session, site)
    custom_navi = [(idx, s['code'], s['market']) for idx, s in enumerate(stocks)]
    utils.set_cache(request.session, 'stocks-view-custom-navi', custom_navi)
    utils.delete_cache(request.session, '/stocks/view-navi-data')

    return render(request, 'filter-list.html', {
        'items': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'current_mark_filter': 'all',
        'pagination_url': site,
        'view_url_prefix': '/stocks/view',
        'page_title': f'{sector.name} - 板块股票',
    })


def stock_sectors(request, market, code):
    """股票所属板块列表：显示该股票对应的所有板块（用 sector-list.html 渲染，分页）"""

    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        # 设置返回来源（从股票 view 进入时调用）
        if 'set_back' in data:
            utils.set_view_back(request.session, data['set_back'])
            return JsonResponse({'status': 'success'})
        if 'page' in data:
            utils.set_cache(request.session, f'stock-sectors-{code}-page', int(data['page']))
        if 'per_page' in data:
            utils.set_page_size(request.session, data['per_page'])
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
            logger.warning("兜底获取板块失败: %s", e)

    # 关联 SectorList 获取板块详情
    sector_codes = [sr.sector_code for sr in sector_relations]
    sector_qs = SectorList.objects.filter(code__in=sector_codes).order_by('code')

    # 统一分页
    pg = utils.paginate_queryset(request, sector_qs, f'stock-sectors-{code}-page')

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
    back_url = utils.get_view_back(request.session) or '/focus/list'
    utils.set_view_back(request.session, back_url)

    # 标记筛选后的全量列表作为 view 的自定义 navi
    custom_navi = [(r.id, r.code, r.market) for r in sector_qs]
    utils.set_cache(request.session, 'sector-view-custom-navi', custom_navi)
    utils.delete_cache(request.session, '/sector/view-navi-data')

    return render(request, 'sector-list.html', {
        'list': items,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'current_mark_filter': 'all',
        'from_stock_sectors': True,
        'stock_code': code,
        'stock_market': market,
    })


def _update_sector_list():
    """从 tushare 获取申万板块列表，增量更新到 SectorList 表（bulk，避免逐条写库）。"""
    try:
        df = tushare.get_all_industry()
        if df is None or df.empty:
            return
        df = df.rename(columns={'index_code': 'code', 'industry_name': 'name'})
        df = df.sort_values('code').reset_index(drop=True)
    except Exception as e:
        logger.warning("获取板块列表失败: %s", e)
        return

    incoming = {}  # code -> (name, cat)
    for _, row in df.iterrows():
        code, cat = row['code'].split('.')
        incoming[code] = (row['name'], cat)

    with transaction.atomic():
        existing = {s.code: s for s in SectorList.objects.all()}
        to_create = []
        to_update = []
        for code, (name, cat) in incoming.items():
            sector = existing.get(code)
            if sector is None:
                to_create.append(SectorList(code=code, name=name, market='SW', cat=cat))
            elif sector.name != name:
                sector.name = name
                to_update.append(sector)
        if to_create:
            SectorList.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            SectorList.objects.bulk_update(to_update, ['name'], batch_size=500)


def rebuild_stock_sector(request):
    """重建板块关联：全量更新StockList和SectorList（不覆盖已有数据），再清空StockSector后台异步全量重建"""
    if request.method != 'POST':
        return JsonResponse({'error': '仅支持POST'}, status=405)
    try:
        # 全量更新StockList（存在则更新name/industry，不存在则创建，不覆盖mark/hide）
        logger.info("rebuild: 全量更新股票列表...")
        utils._update_stock_list()
        logger.info("rebuild: 股票列表更新完成，共 %d 只", StockList.objects.count())
        # 全量更新SectorList（存在则更新name，不存在则创建，不覆盖原记录）
        logger.info("rebuild: 全量更新板块列表...")
        _update_sector_list()
        logger.info("rebuild: 板块列表更新完成，共 %d 个", SectorList.objects.count())
        # 清空现有数据（触发 _update_stock_sector 的全量模式）
        StockSector.objects.all().delete()
        # 后台异步执行全量重建
        t = threading.Thread(target=utils._update_stock_sector, args=([],), daemon=True)
        t.start()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.exception("重建板块关联失败")
        return JsonResponse({'status': 'error', 'message': str(e)})

