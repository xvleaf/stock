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


@require_http_methods(["GET"])
def sector_list(request):
    items = []
    sector_qs = SectorList.objects.all()
    
    if not sector_qs:
        _update_sector_list()
        sector_qs = SectorList.objects.all()

    for fs in sector_qs:
        items.append({
            'id': fs.id,
            'code': fs.code,
            'name': fs.name,
            'market': fs.market,
            'cat': fs.cat,
            'mark': fs.mark
        })

    return render(request, 'sector-list.html', {'list': items})


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
                mark = {'msg': 'done', 'major': sector.mark}
            except SectorList.DoesNotExist:
                mark = {'msg': '代码不存在'}
        else:
            try:
                sector = SectorList.objects.get(code=code)
                sector.mark = '2' if sector.mark != '2' else ''
                sector.save()
                mark = {'msg': 'done', 'minor': sector.mark}
            except SectorList.DoesNotExist:
                mark = {'msg': '代码不存在'}
            
        return JsonResponse(mark)
    else:
        navi_data = func.get_cache(request.session, f'{site}-navi-data', {})
        if (site, code, market) != navi_data.get('site_code_market', None):
            navi_data = chart.set_navi_data(request.session, site, code, market, None, 'init')
        
        view_mode = func.get_cache(request.session, 'view', 'kline') 

        sector = SectorList.objects.filter(code=code).first()
        # 图表配置
        chart_init = {
            'site': site,
            'code': code,
            'market': market,
            'name': sector.name,
            'cat': sector.cat,
            'view': view_mode
        }

        return render(request, 'sector-view.html', {'chart': json.dumps(chart_init)})


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

