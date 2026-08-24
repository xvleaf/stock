import pandas as pd
import datetime
import decimal
from .fetch import kline, trend

# 类型转换映射：类型名 -> 转换函数（用于 get_session 将字符串还原为对应类型）
TYPE_CONVERTERS = {
    'datetime': datetime.datetime.fromisoformat,
    'date': datetime.date.fromisoformat,
    'decimal': decimal.Decimal,
}


def date_to_timestamp(date_obj):
    """日期转13位毫秒时间戳"""
    if isinstance(date_obj, str):
        date_obj = pd.to_datetime(date_obj)    
    return int(date_obj.timestamp() * 1000)



"""
包括：
view, kline_params, trend_params, navi_params
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
        print(key, init)
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