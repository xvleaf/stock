import pandas as pd
import datetime
import decimal
from .fetch import kline, trend
from .fetch import tushare
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .models.models import StockList
from django.db import connection, transaction


# 类型转换映射：类型名 -> 转换函数（用于 get_session 将字符串还原为对应类型）
TYPE_CONVERTERS = {
    'datetime': datetime.datetime.fromisoformat,
    'date': datetime.date.fromisoformat,
    'decimal': decimal.Decimal,
}



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
        

def date_to_timestamp(date_obj):
    """日期转13位毫秒时间戳"""
    if isinstance(date_obj, str):
        date_obj = pd.to_datetime(date_obj)    
    return int(date_obj.timestamp() * 1000)


"""
包括：
view, kline_params, navi_params, trend_data_last_timestamp
"""
def set_session(session, key, value):
    """
    将值存入 session
    自动包装非 JSON 可序列化的类型（datetime, date, Decimal）
    其他类型（如 str, int, float, bool, list, dict, None）直接存储
    """
    # 判断是否为需要包装的类型
    if isinstance(value, datetime.datetime):
        wrapped = {'__type__': 'datetime', '__value__': value.isoformat()}
    elif isinstance(value, datetime.date):
        wrapped = {'__type__': 'date', '__value__': value.isoformat()}
    elif isinstance(value, decimal.Decimal):
        wrapped = {'__type__': 'decimal', '__value__': str(value)}
    else:
        # 其他类型（假定可 JSON 序列化）直接存储
        wrapped = value
    session[key] = wrapped


def get_session(session, key, init=None):
    """
    从 session 中取值
    如果存储时是经过包装的类型，则自动还原为原始类型
    如果键不存在，返回 init
    """
    
    # 显式检查键是否存在，避免使用默认值引发的歧义
    if key not in session:
        return init

    wrapped = session[key]

    # 检查是否为包装的类型字典
    if isinstance(wrapped, dict) and '__type__' in wrapped and '__value__' in wrapped:
        type_name = wrapped['__type__']
        raw_value = wrapped['__value__']
        converter = TYPE_CONVERTERS.get(type_name)
        if converter:
            try:
                return converter(raw_value)
            except (ValueError, TypeError):
                # 如果转换失败（例如数据损坏），返回原始包装字典
                return wrapped
        else:
            # 未知类型，返回原始包装字典
            return wrapped
    # 普通值（未包装）直接返回
    return wrapped

    
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
