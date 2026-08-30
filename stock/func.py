import pandas as pd
import decimal
from .fetch import kline, trend
from .fetch import tushare
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models.models import StockList
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
    不删除旧数据，仅更新或新增
    """
    EXCHANGE_MAP = {
        'SSE': 'SH',
        'SZSE': 'SZ',
        'BSE': 'BJ',
    }

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
                stock = StockList.objects.filter(
                    code=row['code'],
                    market=row['market']
                ).first()
                if stock:
                    stock.name = row['name']
                    stock.industry = row['industry']
                    stock.cat = 'stock'   # 设置类别
                    stock.save()
                else:
                    StockList.objects.create(
                        code=row['code'],
                        market=row['market'],
                        name=row['name'],
                        industry=row['industry'],
                        cat='stock'       # 新增
                    )
    except Exception as e:
        print(f"更新股票列表失败: {e}")




def _update_stock_list():
    """
    从 tushare 获取最新股票基础信息，更新到本地 StockList 表
    不删除旧数据，仅更新或新增
    """
    EXCHANGE_MAP = {
        'SSE': 'SH',
        'SZSE': 'SZ',
        'BSE': 'BJ',
    }

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
