import json
import logging
import threading

import pandas as pd
import pytz
from datetime import datetime, time, timedelta, date as date_type
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.core.cache import cache
from django.http import JsonResponse

from .fetch import tushare
from .models import StockList, StockSector, SectorList, CashConfig

logger = logging.getLogger('stock')

# 中国时区（模块级复用，避免每次转换重复构造）
SH_TZ = pytz.timezone('Asia/Shanghai')


# =====================================================================
# 请求体解析等视图公共小工具
# =====================================================================
def parse_json_body(request):
    """
    解析 POST 请求的 JSON body。
    返回 (data, error_response)：
      - 成功：(dict/list, None)
      - 失败：(None, 400 JsonResponse)
    """
    try:
        return json.loads(request.body), None
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None, JsonResponse({'error': '无效JSON'}, status=400)


def price_places(cat):
    """返回该类资产价格小数位：基金/债券 3 位，其余 2 位。"""
    return 3 if cat in ('fund', 'bond') else 2


def build_chart_init(site, code, market, name, cat, view='kline', back_url=None, **extra):
    """
    构造图表页面 pageConfig 的初始字典（各 view 页面复用）。
    navi/mark/taskId 等附加字段通过 extra 传入。
    """
    chart = {
        'site': site,
        'code': code,
        'market': market,
        'name': name,
        'cat': cat,
        'view': view,
    }
    if back_url is not None:
        chart['backUrl'] = back_url
    chart.update(extra)
    return chart


def get_stat_range(prefix):
    """
    统计页（cash/review）日期范围，返回 (start_date, end_date, start_str, end_str)。
    - 起始：WebSetting '{prefix}_stat_start'，空则默认去年今天 +1 天
    - 结束：仅当天有效，跨天自动重置为当天，并写回
      '{prefix}_stat_end' / '{prefix}_stat_end_set_day'
    """
    from .fetch.config import get_config, set_config

    today = date_type.today()
    today_str = today.strftime('%Y-%m-%d')
    try:
        default_start_date = today.replace(year=today.year - 1) + timedelta(days=1)
    except ValueError:
        # 2月29日等边界
        default_start_date = today.replace(year=today.year - 1, day=28) + timedelta(days=1)
    default_start = default_start_date.strftime('%Y-%m-%d')

    start_str = str(get_config(f'{prefix}_stat_start', '') or default_start)
    end_set_day = str(get_config(f'{prefix}_stat_end_set_day', ''))
    if end_set_day == today_str:
        end_str = str(get_config(f'{prefix}_stat_end', '') or today_str)
    else:
        end_str = today_str
        set_config(f'{prefix}_stat_end', today_str)
        set_config(f'{prefix}_stat_end_set_day', today_str)

    try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        start_date = default_start_date
        start_str = start_date.strftime('%Y-%m-%d')
    try:
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        end_date = today
        end_str = end_date.strftime('%Y-%m-%d')

    return start_date, end_date, start_str, end_str


def refresh_prices(code_markets, model, status_field, status_value):
    """
    按 "code.market" 列表批量取最新价（一次查询取出对应标的，再逐个取行情）。
    :param model: 标的模型（FocusStock / TransOrder）
    :param status_field / status_value: 状态过滤，如 ('status', FocusStock.STATUS_WATCHING)
    :return: list[dict]，每项 {code, market, close, change, deci}
    """
    from django.db.models import Q
    from .fetch import quote

    pairs = []
    for cm in code_markets:
        parts = str(cm).split('.')
        if len(parts) == 2:
            pairs.append((parts[0], parts[1]))
    if not pairs:
        return []

    q = Q()
    for c, m in pairs:
        q |= Q(code=c, market=m)
    qs = model.objects.filter(q, **{status_field: status_value})

    result = []
    for obj in qs:
        deci = price_places(getattr(obj, 'cat', 'stock'))
        close, change = quote.get_last_price(f'{obj.code}.{obj.market}', deci)
        result.append({
            'code': obj.code,
            'market': obj.market,
            'close': close,
            'change': change,
            'deci': deci,
        })
    return result


def create_deal(history_model, **fields):
    """
    创建一条不触发订单自动重算的成交/分红历史（TransHistory）。
    调用方负责在合适时机调用一次 order.recalculate()。
    """
    deal = history_model(**fields)
    deal._skip_recalc = True
    deal.save()
    return deal


def date_to_timestamp(date_obj):
    """
    将日期转换为13位毫秒时间戳（强制中国时区，并设为当天00:00:00）
    date_obj: 字符串'YYYYMMDD' 或 datetime/date 对象
    """
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
            dt = dt.astimezone(SH_TZ)
        else:
            dt = SH_TZ.localize(dt)
    else:
        # 其他类型（如 pandas Timestamp）转换为 datetime
        dt = pd.to_datetime(date_obj).to_pydatetime()
        dt = SH_TZ.localize(dt)

    # 如果 dt 还不是 aware，本地化
    if dt.tzinfo is None:
        dt = SH_TZ.localize(dt)
    else:
        # 确保在中国时区
        dt = dt.astimezone(SH_TZ)

    # 保留日期部分（即当天00:00:00）
    # 这里返回 00:00:00 的时间戳
    return int(dt.timestamp() * 1000)


def dates_to_timestamps(series):
    """
    将一整列日期（date/datetime/pandas.Timestamp/字符串'YYYYMMDD'或'YYYY-MM-DD'）
    一次性【整列向量化】转换为 13 位毫秒时间戳列表（中国时区当天 00:00），
    等价于逐个 date_to_timestamp，但解析、时区本地化、毫秒换算全部在 C 层整列完成，
    无 Python 逐行迭代，适合 DataFrame 整列。
    """
    try:
        # 快路径：整列格式统一（DataFrame 列通常如此）
        parsed = pd.to_datetime(series)
    except (ValueError, TypeError):
        # 兜底：字符串格式混合（'YYYYMMDD' 与 'YYYY-MM-DD' 共存）
        parsed = pd.to_datetime(series, format='mixed')
    # 统一为 Series（DatetimeIndex 没有 .dt accessor），后续全部走 .dt
    dt_series = pd.Series(parsed)
    if dt_series.dt.tz is not None:
        dt_series = dt_series.dt.tz_convert(SH_TZ)
    else:
        dt_series = dt_series.dt.tz_localize(SH_TZ)
    # 归一化到当天 00:00:00
    dt_series = dt_series.dt.normalize()
    # 转 UTC、去时区后整列取 int64 纳秒，再整列换算为毫秒（向量化，无逐行循环）
    ns = dt_series.dt.tz_convert('UTC').dt.tz_localize(None).astype('int64')
    return (ns // 1_000_000).tolist()


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
        # 按代码正序排列
        df = df.sort_values('code').reset_index(drop=True)

        # 一次性取出存量，内存中比对后批量写入（避免逐行查询/保存）
        existing = {(s.code, s.market): s for s in StockList.objects.all()}
        to_create, to_update = [], []
        for _, row in df.iterrows():
            key = (row['code'], row['market'])
            stock = existing.get(key)
            if stock:
                if stock.name != row['name'] or stock.industry != row['industry']:
                    stock.name = row['name']
                    stock.industry = row['industry']
                    to_update.append(stock)
            else:
                to_create.append(StockList(
                    code=row['code'],
                    market=row['market'],
                    name=row['name'],
                    industry=row['industry']
                ))
                new_stocks.append(key)

        with transaction.atomic():
            if to_create:
                StockList.objects.bulk_create(to_create, batch_size=500)
            if to_update:
                StockList.objects.bulk_update(to_update, ['name', 'industry'], batch_size=500)
    except Exception:
        logger.exception('更新股票列表失败')
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
            logger.info("[StockSector] 全量初始化开始...")
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
                except Exception:
                    logger.exception("[StockSector] 板块 %s 获取成分股失败", sector.code)
            if bulk_list:
                # 按股票代码正序排列
                bulk_list.sort(key=lambda x: x.stock_code)
                with transaction.atomic():
                    StockSector.objects.all().delete()
                    StockSector.objects.bulk_create(bulk_list, batch_size=500)
            logger.info("[StockSector] 全量初始化完成，共 %d 条关联", len(bulk_list))
        else:
            # ===== 增量模式：仅处理新增股票，调用 get_industry_member =====
            if not new_stocks:
                return
            logger.info("[StockSector] 增量更新开始，新增 %d 只股票...", len(new_stocks))
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
                except Exception:
                    logger.exception("[StockSector] 股票 %s.%s 获取板块失败", code, market)
            logger.info("[StockSector] 增量更新完成，新增 %d 条关联", count)
    except Exception:
        logger.exception("[StockSector] 更新失败")


# =====================================================================
# 统一列表分页 / 导航工具（供筛选列表、筛选对比、关注列表等复用）
# =====================================================================
GLOBAL_PAGE_SIZE_KEY = 'global-per-page'


def _get_default_page_size():
    """从 WebSetting 读取默认每页数量"""
    try:
        from .fetch.config import get_config
        return int(get_config('default_page_size', 10))
    except Exception:
        return 10


def get_page_size(session):
    """从全局 session 读取每页条数，非法值（非正整数）回退默认。"""
    default_size = _get_default_page_size()
    raw = str(get_cache(session, GLOBAL_PAGE_SIZE_KEY, str(default_size)))
    try:
        v = int(raw)
        return v if v >= 1 else default_size
    except (TypeError, ValueError):
        return default_size


def set_page_size(session, value):
    """设置每页条数，仅接受正整数。"""
    try:
        v = int(value)
        if v >= 1:
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


def paginate_queryset(request, queryset, page_key, code_getter=None, per_page=None):
    """
    统一分页入口。
    - queryset: 已排序的查询集
    - page_key: 存储当前页码的 session key，如 'filter-list-page'
    - code_getter: 从对象取 code 的函数，默认 obj.code
    - per_page: 每页条数，传入则覆盖全局设置（用于页面独立分页）
    - 返回 dict: items, current_page, total_pages, per_page, total_count
    """
    from django.core.paginator import Paginator
    if per_page is None:
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


# =====================================================================
# 数值 / 交易计算公共工具（原 views/cash.py，供 cash/trans/focus 等模块复用）
# =====================================================================
def round_decimal(value, places='0.01'):
    """统一四舍五入（ROUND_HALF_UP）到指定小数位，places 为 Decimal 量化字符串，如 '0.01'"""
    return Decimal(str(value)).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def calc_allowed_qty(plan_price, stop_price=0, intent='B'):
    """
    计算允许购买数量（按手取整），取现金限制和风险额度限制的较小值
    止损价>=成交价时，仅按现金计算
    :param plan_price: 计划买入价
    :param stop_price: 止损价
    :param intent: 'B'买入 / 'S'卖出
    :return: int 股数
    """
    config = CashConfig.get_config()
    price = Decimal(str(plan_price))
    # 现金限制
    if price <= 0 or config.cash <= 0:
        by_cash = 0
    else:
        by_cash = int(config.cash / price)
    # 风险额度限制
    remaining = config.allowance - config.risk
    if intent == 'S':
        # 卖出：风险 = (止损价 - 成交价)
        risk_per_share = Decimal(str(stop_price or 0)) - price
    else:
        # 买入：交易风险 = (成交价 - 止损价)
        risk_per_share = price - Decimal(str(stop_price or 0))
    # 止损价>=成交价时，仅按现金计算
    if risk_per_share <= 0:
        return (by_cash // 100) * 100
    by_risk = int(remaining / risk_per_share) if remaining > 0 else 0
    max_qty = min(by_cash, by_risk)
    # 向下取整（1手100股）
    return (max_qty // 100) * 100


def calc_commission(amount, commission_rate, min_commission):
    """
    计算佣金（不足最低佣金按最低收取）
    :param amount: 成交金额 Decimal
    :param commission_rate: 佣金费率
    :param min_commission: 最低佣金
    :return: Decimal
    """
    amount = Decimal(str(amount))
    rate = Decimal(str(commission_rate))
    minimum = Decimal(str(min_commission))
    commission = amount * rate
    return round_decimal(commission if commission >= minimum else minimum)


def calc_stamp_tax(amount, stamp_tax_rate):
    """
    计算印花税（仅卖出收取）
    :param amount: 成交金额 Decimal
    :param stamp_tax_rate: 印花税率
    :return: Decimal
    """
    return round_decimal(Decimal(str(amount)) * Decimal(str(stamp_tax_rate)))


def calc_fee(amount, intent, market='SH', config=None):
    """
    计算交易费用
    :param amount: 成交金额
    :param intent: 'B'买入 / 'S'卖出
    :param market: 'SH'沪市 / 'SZ'深市 / 'BJ'北交所
    :param config: 保留参数（兼容旧调用），实际从 WebSetting 读取
    :return: dict {commission, stamp_tax, transfer_fee, total}
    """
    from .fetch.config import get_all_config
    cfg = get_all_config()
    amount = Decimal(str(amount))
    commission = calc_commission(amount, cfg.get('commission_ratio', 0.000085), cfg.get('commission_min', 0))
    stamp_tax = Decimal('0')
    if intent == 'S':
        stamp_tax = calc_stamp_tax(amount, cfg.get('stamp_sell_ratio', 0.0005))
    # 过户费：买卖双向收取，按市场选择费率
    transfer_rate = cfg.get(f'transfer_fee_{market.lower()}', 0)
    transfer_fee = round_decimal(amount * Decimal(str(transfer_rate)))
    total = round_decimal(commission + stamp_tax + transfer_fee)
    return {
        'commission': round_decimal(commission),
        'stamp_tax': stamp_tax,
        'transfer_fee': transfer_fee,
        'total': total,
    }


def calc_risk_capital(buy_price, stop_price, qty, intent='B'):
    """
    风险资金
    买入：(买入价 - 止损价) × 数量
    卖出：(止损价 - 卖出价) × 数量
    风险为负时返回0
    """
    price = Decimal(str(buy_price))
    stop = Decimal(str(stop_price))
    qty = int(qty)
    if intent == 'S':
        risk = (stop - price) * qty
    else:
        risk = (price - stop) * qty
    if risk <= 0 or qty <= 0:
        return Decimal('0')
    return round_decimal(risk)


def calc_win_ratio(buy_price, target_price, stop_price, intent='B'):
    """计算成功几率（0-99整数）
    买入：(目标价 - 成交价) / (目标价 - 止损价) × 99
    卖出：(成交价 - 目标价) / (止损价 - 目标价) × 99
    """
    try:
        price = float(buy_price or 0)
        target = float(target_price or 0)
        stop = float(stop_price or 0)
    except (TypeError, ValueError):
        return 0
    if price <= 0:
        return 0
    if intent == 'S':
        # 卖出：止损价 > 成交价 > 目标价
        if stop <= price:
            return 99
        if target >= price:
            return 0
        prob = round((price - target) / (stop - target) * 99)
    else:
        # 买入：目标价 > 成交价 > 止损价
        if stop >= price:
            return 99
        if target <= price:
            return 0
        prob = round((target - price) / (target - stop) * 99)
    return max(0, min(99, prob))


# =====================================================================
# 历史记录备注保存（trans/focus/review 三处共用，统一返回 {success: true}）
# =====================================================================
def save_history_comment(request, history_model):
    """
    保存指定历史模型某条记录的备注
    :param request: HttpRequest，POST JSON：history_id、comments
    :param history_model: 历史模型类（TransHistory / FocusHistory）
    :return: JsonResponse，成功 {'success': True}
    """
    data, err = parse_json_body(request)
    if err:
        return err

    history_id = data.get('history_id')
    comments = data.get('comments', '') or ''
    if not history_id:
        return JsonResponse({'error': '缺少历史记录ID'}, status=400)

    try:
        history = history_model.objects.get(id=history_id)
    except history_model.DoesNotExist:
        return JsonResponse({'error': '历史记录不存在'}, status=404)

    history.comments = comments
    history.save(update_fields=['comments'])
    return JsonResponse({'success': True})
