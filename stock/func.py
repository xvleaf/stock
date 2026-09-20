import os
import threading
import pandas as pd
import decimal
from .fetch import kline, trend
from .fetch import tushare
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models.models import StockList, StockSector, SectorList
from django.db import connection, transaction
from django.core.cache import cache
import pytz
from datetime import datetime, time, date as date_type


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
            return JsonResponse({'code': code, 'market': market, 'name': stock.name, 'cat': stock.cat})
    except Exception:
        pass

    # 数据库中不存在，尝试更新股票列表
    _update_stock_list()

    # 再次从数据库查询
    try:
        stock = StockList.objects.filter(code=code, market=market).first()
        if stock:
            return JsonResponse({'code': code, 'market': market, 'name': stock.name, 'cat': stock.cat})
        else:
            return JsonResponse({'code': code, 'market': market, 'name': '', 'cat': ''})
    except Exception:
        return JsonResponse({'code': code, 'market': market, 'name': '', 'cat': ''})
        

def date_to_timestamp(date_obj):
    """
    将日期转换为13位毫秒时间戳（强制中国时区，并设为当天00:00:00）
    date_obj: 字符串'YYYYMMDD' 或 datetime/date 对象
    """
    tz = pytz.timezone('Asia/Shanghai')
    
    if isinstance(date_obj, str):
        # 解析 '20230104' 格式
        dt = datetime.strptime(date_obj, '%Y%m%d')
    elif isinstance(date_obj, date_type):
        # date 对象转为 datetime
        dt = datetime.combine(date_obj, time.min)
    elif isinstance(date_obj, datetime):
        dt = date_obj
        if dt.tzinfo is not None:
            # 如果已有时区，转换为中国时区
            dt = dt.astimezone(tz)
        else:
            dt = tz.localize(dt)
    else:
        # 其他类型（如 pandas Timestamp）转换为 datetime
        dt = pd.to_datetime(date_obj).to_pydatetime()
        dt = tz.localize(dt)
    
    # 如果 dt 还不是 aware，本地化
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    else:
        # 确保在中国时区
        dt = dt.astimezone(tz)
    
    # 保留日期部分（即当天00:00:00）
    # 这里返回 00:00:00 的时间戳
    return int(dt.timestamp() * 1000)


def set_cache(session, key, value, expiry=None):
    """
    将值存入缓存，支持指定该 key 的过期时间（秒）
    expiry: 整数秒，若为 None 则使用缓存默认超时
    """
    if not session.session_key:
        session._get_or_create_session_key()
    session.modified = True  # 触发 session 保存，确保 session cookie 发送到客户端（否则匿名用户每次请求 session_key 不同，cache 读不到）
    prefix = f"user_{session.session_key}_"
    cache_key = prefix + key
    cache.set(cache_key, value, timeout=expiry)


def get_cache(session, key, init=None):
    """
    从缓存中取值，若 key 不存在则返回 init
    """
    if not session.session_key:
        session._get_or_create_session_key()
    prefix = f"user_{session.session_key}_"
    cache_key = prefix + key
    return cache.get(cache_key, init)


def delete_cache(session, key):
    """
    删除指定 key 的缓存
    """
    if not session.session_key:
        session._get_or_create_session_key()
    prefix = f"user_{session.session_key}_"
    cache_key = prefix + key
    cache.delete(cache_key)


def _update_stock_list():
    """
    从 tushare 获取最新股票基础信息，更新到本地 StockList 表
    不删除旧数据，仅更新或新增；末尾异步更新股票-板块关联
    """
    EXCHANGE_MAP = {
        'SSE': 'SH',
        'SZSE': 'SZ',
        'BSE': 'BJ',
    }
    new_stocks = []

    try:
        df = tushare.get_stock_basic()
        if df is None or df.empty:
            return

        df.rename(columns={'symbol': 'code'}, inplace=True)
        df['market'] = df['exchange'].map(EXCHANGE_MAP)
        df = df.dropna(subset=['market'])
        df['industry'] = df['industry'].fillna('')

        with transaction.atomic():
            for _, row in df.iterrows():
                # 先尝试查询现有记录
                stock = StockList.objects.filter(
                    code=row['code'],
                    market=row['market']
                ).first()
                if stock:
                    # 存在则更新
                    stock.name = row['name']
                    stock.industry = row['industry']
                    stock.save()
                else:
                    # 不存在则创建
                    StockList.objects.create(
                        code=row['code'],
                        market=row['market'],
                        name=row['name'],
                        industry=row['industry']
                    )
                    new_stocks.append((row['code'], row['market']))
    except Exception as e:
        print(f"更新股票列表失败: {e}")
        return

    # 异步更新股票-板块关联（不阻塞当前请求）
    if new_stocks or not StockSector.objects.exists():
        t = threading.Thread(target=_update_stock_sector, args=(new_stocks,), daemon=True)
        t.start()


def _update_stock_sector(new_stocks):
    """
    更新股票-板块关联（StockSector 表）。
    智能切换：StockSector 为空时全量模式（遍历板块，31次API），否则增量模式（仅新增股票，N次API）。
    """
    try:
        if not StockSector.objects.exists():
            # ===== 全量模式：遍历所有板块，调用 get_match_industry =====
            print("[StockSector] 全量初始化开始...")
            sectors = SectorList.objects.all()
            bulk_list = []
            for sector in sectors:
                try:
                    df = tushare.get_match_industry(f'{sector.code}.{sector.cat}')
                    if df is None or df.empty:
                        continue
                    for _, row in df.iterrows():
                        ts_code = row.get('ts_code', '')
                        if not ts_code or '.' not in ts_code:
                            continue
                        code, market = ts_code.split('.', 1)
                        bulk_list.append(StockSector(
                            stock_code=code,
                            stock_market=market,
                            sector_code=sector.code,
                            sector_market=sector.market,
                        ))
                except Exception as e:
                    print(f"[StockSector] 板块 {sector.code} 获取成分股失败: {e}")
            if bulk_list:
                with transaction.atomic():
                    StockSector.objects.all().delete()
                    StockSector.objects.bulk_create(bulk_list, batch_size=500)
            print(f"[StockSector] 全量初始化完成，共 {len(bulk_list)} 条关联")
        else:
            # ===== 增量模式：仅处理新增股票，调用 get_industry_member =====
            if not new_stocks:
                return
            print(f"[StockSector] 增量更新开始，新增 {len(new_stocks)} 只股票...")
            count = 0
            for code, market in new_stocks:
                try:
                    df = tushare.get_industry_member(f'{code}.{market}')
                    if df is None or df.empty:
                        continue
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
                        count += 1
                except Exception as e:
                    print(f"[StockSector] 股票 {code}.{market} 获取板块失败: {e}")
            print(f"[StockSector] 增量更新完成，新增 {count} 条关联")
    except Exception as e:
        print(f"[StockSector] 更新失败: {e}")


# =====================================================================
# 统一列表分页 / 导航工具（供筛选列表、筛选对比、关注列表等复用）
# =====================================================================
PAGE_SIZE_CHOICES = [10, 20, 50]
DEFAULT_PAGE_SIZE = int(os.environ.get('GLOBAL_PER_PAGE', '10'))
GLOBAL_PAGE_SIZE_KEY = 'global-per-page'


def get_page_size(session):
    """从全局 session 读取每页条数，非法值回退默认。"""
    raw = str(get_cache(session, GLOBAL_PAGE_SIZE_KEY, str(DEFAULT_PAGE_SIZE)))
    try:
        v = int(raw)
        return v if v in PAGE_SIZE_CHOICES else DEFAULT_PAGE_SIZE
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE


def set_page_size(session, value):
    try:
        v = int(value)
        if v in PAGE_SIZE_CHOICES:
            set_cache(session, GLOBAL_PAGE_SIZE_KEY, str(v))
    except (TypeError, ValueError):
        pass


def resolve_focus_page(session, queryset, per_page, code_getter=None):
    """
    若 session 中有 view-current-code（从 view 返回列表时带入），
    计算其在已排序 queryset 中的页码（1-based），消费掉该 code 并返回页码；无则返回 None。
    """
    if code_getter is None:
        code_getter = lambda obj: getattr(obj, 'code', None)
    focus_code = get_cache(session, 'view-current-code')
    if not focus_code:
        return None
    delete_cache(session, 'view-current-code')
    for idx, obj in enumerate(iter(queryset)):
        if code_getter(obj) == focus_code:
            return idx // per_page + 1
    return None


def paginate_queryset(request, queryset, page_key, code_getter=None):
    """
    统一分页入口。
    - queryset: 已排序的查询集
    - page_key: 存储当前页码的 session key，如 'filter-list-page'
    - code_getter: 从对象取 code 的函数，默认 obj.code
    - 返回 dict: items, current_page, total_pages, per_page, total_count
    """
    from django.core.paginator import Paginator
    per_page = get_page_size(request.session)

    # 优先用 view-current-code 定位页码（从 view 返回列表时）
    focus_page = resolve_focus_page(request.session, queryset, per_page, code_getter)
    if focus_page is not None:
        current_page = focus_page
        set_cache(request.session, page_key, current_page)
    else:
        raw = get_cache(request.session, page_key, 1)
        try:
            current_page = int(raw)
        except (TypeError, ValueError):
            current_page = 1

    paginator = Paginator(queryset, per_page)
    current_page = max(1, min(current_page, paginator.num_pages or 1))
    page = paginator.get_page(current_page)
    return {
        'items': page.object_list,
        'current_page': current_page,
        'total_pages': paginator.num_pages,
        'per_page': per_page,
        'total_count': paginator.count,
    }


# ---- view 返回列表来源记忆 ----
def set_view_back(session, url):
    set_cache(session, 'view-back-url', url)


def get_view_back(session):
    return get_cache(session, 'view-back-url')


def set_view_current_code(session, code):
    set_cache(session, 'view-current-code', code)


def get_view_current_code(session):
    return get_cache(session, 'view-current-code')
