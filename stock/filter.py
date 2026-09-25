import os
import json
import time
import threading
import datetime
from decimal import Decimal
import pandas as pd
from django.http import JsonResponse, HttpResponseRedirect, Http404
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.db import transaction
from .fetch import quote, tushare
from . import func, chart, cash
from .models.models import (StockList, FilterTask, FilterResult, FocusStock,
                            FilterGlobalConfig, BOARD_DEFS, BOARD_LABELS, board_of_code)
from django.core.cache import cache

# 筛选进行中的全局锁（防止并发重复筛选）
FILTER_RUNNING_KEY = 'filter-running'
FILTER_RUNNING_TIMEOUT = 7200   # 2 小时

# 筛选添加关注时的默认倍率
TARGET_PROFIT_RATIO = 1.1    # 目标价 = 计划价 × 1.1
STOP_LOSS_RATIO = 0.98       # 止损价 = 计划价 × 0.98
FILTER_PROGRESS_KEY = 'filter-progress'
FILTER_STOP_KEY = 'filter-stop'
FILTER_TIMEOUT_KEY = 'filter-timeout'


# =====================================================================
# 筛选条件数据结构说明
# =====================================================================
# 条件列表 conditions: List[Cond]，多个条件之间为 AND 关系
#
# 1) 比较条件 type = 'compare'
#    左侧恒为「收盘价」（可乘倍率），右侧恒为 EMA/MA（带周期与倍率），
#    左右两侧基于同一个 freq 的 K 线逐周期比较，不存在跨周期比较。
# {
#   "type": "compare",
#   "freq": "D"|"W"|"M",          # 本条件的周期（收盘价/均线/M根 都用它）
#   "close_mult": 1.0,            # 左侧收盘价倍率，默认1.0
#   "right_kind": "ema"|"ma",     # 右侧均线类型
#   "right_period": 30,           # 右侧均线周期
#   "right_mult": 1.0,            # 右侧均线倍率
#   "op": ">" | "<",
#   "window": 10,                 # M：考察最近 M 个周期
#   "min_count": 8                # N：其中至少 N 个周期满足
# }
#
# 2) 趋势条件 type = 'trend'
# {
#   "type": "trend",
#   "freq": "D"|"W"|"M",
#   "kind": "ema"|"ma",
#   "period": 30,
#   "direction": "up"|"down"|"accel_up"|"accel_down",
#   "window": 5
# }
#   - up:        最近 window 个差值均为正（单调上升）
#   - down:      最近 window 个差值均为负（单调下降）
#   - accel_up:  差值均为正且递增（加速上升）
#   - accel_down:差值均为负且递减（加速下降）


FREQ_LABEL = {'D': '日线', 'W': '周线', 'M': '月线'}
KIND_LABEL = {'close': '收盘价', 'volume': '成交量', 'ema': 'EMA', 'ma': 'MA'}
OP_LABEL = {'>': '大于', '<': '小于'}
DIR_LABEL = {
    'up': '上升趋势', 'down': '下降趋势',
    'accel_up': '加速上升', 'accel_down': '加速下降',
}


# =====================================================================
# K 线数据加载（带本次请求内缓存）
# =====================================================================
def _used_freqs(conditions):
    """根据条件列表决定需要拉取哪些周期"""
    freqs = set()
    for c in conditions:
        if not isinstance(c, dict):
            continue
        freqs.add(c.get('freq', 'D'))
    return freqs or {'D'}


def _load_kline_map(cache, code, market, cat, conditions):
    """
    拉取某股票所需周期的前复权 K 线，返回 {freq: DataFrame(按 trade_date 升序)}。
    cache: {tscode: {freq: df} | None}，本次筛选内复用。
    """
    tscode = f'{code}.{market}'
    if tscode in cache:
        return cache[tscode]

    asset_map = {'stock': 'E', 'index': 'I', 'fund': 'FD', 'bond': 'CB'}
    asset = asset_map.get(cat, 'E')
    start = os.getenv('KLINE_START_DATE', '20230101')
    end = datetime.datetime.now().strftime('%Y%m%d')
    need_freqs = _used_freqs(conditions)

    df_map = {}
    for freq in sorted(need_freqs):
        try:
            df = tushare.get_kline_data(
                asset=asset, tscode=tscode, start=start, end=end,
                freq=freq, adj='qfq'
            )
        except Exception as e:
            print(f'[filter] K线获取失败 {tscode} {freq}: {e}')
            df = None
        if df is None or df.empty:
            # 该周期无数据：若本条件只需要该周期则该股票不参与；其他周期照常
            continue
        df = df.dropna(subset=['close']).sort_values('trade_date').reset_index(drop=True)
        df_map[freq] = df

    if not df_map:
        cache[tscode] = None
        return None
    cache[tscode] = df_map
    return df_map


# =====================================================================
# 单条件判定
# =====================================================================
def _cmp_bool_series(df_map, cond):
    """对 EMA/MA 比较条件，返回逐根满足的 bool Series；PRC 返回 None。"""
    freq = cond.get('freq', 'D')
    df = df_map.get(freq)
    if df is None:
        return None
    left_kind = cond.get('left_kind', 'close')
    if left_kind == 'volume':
        src = df.get('vol') if 'vol' in df.columns else df.get('volume')
    else:
        src = df['close']
    if src is None or len(src) == 0:
        return None
    right_kind = cond.get('right_kind', 'ema')
    if right_kind == 'prc':
        return None
    period = int(cond.get('right_period', 30))
    if right_kind == 'ma':
        ma = src.rolling(window=period).mean()
    else:
        ma = src.ewm(span=period, adjust=False).mean()
    right = ma * float(cond.get('right_mult', 1.0))
    left = src * float(cond.get('left_mult', 1.0))
    op = cond.get('op', '>')
    return (left > right) if op == '>' else (left < right)


def _prc_match(df_map, cond):
    """PRC 比较条件：只看最新一根。"""
    freq = cond.get('freq', 'D')
    df = df_map.get(freq)
    if df is None:
        return False
    left_kind = cond.get('left_kind', 'close')
    if left_kind == 'volume':
        src = df.get('vol') if 'vol' in df.columns else df.get('volume')
    else:
        src = df['close']
    if src is None or len(src) == 0:
        return False
    left_last = float(src.iloc[-1]) * float(cond.get('left_mult', 1.0))
    price = float(cond.get('right_price', 0))
    return bool((left_last > price) if cond.get('op', '>') == '>' else (left_last < price))


def _eval_compare(df_map, cond):
    """
    比较条件，左右同周期、无跨周期比较。
    - right_kind = 'ema'/'ma'：在 freq 最近 window 根K线上统计
      「左值*left_mult  op  (右均线(right_period)*right_mult)」成立根数 >= min_count。
    - right_kind = 'prc'：固定价格，只看最新一根K线（当日）
      「左值*left_mult  op  right_price」是否成立（窗口不参与）。
    左值 left_kind = 'close'(收盘价) 或 'volume'(成交量)；均线基于左值同一序列。
    """
    freq = cond.get('freq', 'D')
    df = df_map.get(freq)
    if df is None:
        return False

    left_kind = cond.get('left_kind', 'close')
    if left_kind == 'volume':
        src = df.get('vol') if 'vol' in df.columns else df.get('volume')
    else:
        src = df['close']
    if src is None or len(src) == 0:
        return False

    right_kind = cond.get('right_kind', 'ema')

    # PRC：固定价格，仅当日判断
    if right_kind == 'prc':
        left_last = float(src.iloc[-1]) * float(cond.get('left_mult', 1.0))
        price = float(cond.get('right_price', 0))
        return bool((left_last > price) if cond.get('op', '>') == '>' else (left_last < price))

    # EMA / MA：窗口统计
    period = int(cond.get('right_period', 30))
    if right_kind == 'ma':
        ma = src.rolling(window=period).mean()
    else:
        ma = src.ewm(span=period, adjust=False).mean()
    right = ma * float(cond.get('right_mult', 1.0))
    left = src * float(cond.get('left_mult', 1.0))

    op = cond.get('op', '>')
    cmp_series = (left > right) if op == '>' else (left < right)
    window = int(cond.get('window', 1))
    min_count = int(cond.get('min_count', 1))

    tail = cmp_series.tail(window).dropna()
    if len(tail) < window:
        return False
    return int(tail.sum()) >= min_count


def _eval_trend(df_map, cond):
    kind = cond.get('kind', 'ema')
    freq = cond.get('freq', 'D')
    period = int(cond.get('period', 30))
    direction = cond.get('direction', 'up')
    window = int(cond.get('window', 5))

    df = df_map.get(freq)
    if df is None:
        return False
    close = df['close']
    if kind == 'ema':
        v = close.ewm(span=period, adjust=False).mean().dropna()
    else:
        v = close.rolling(window=period).mean().dropna()

    if len(v) < window + 1:
        return False
    tail = v.tail(window + 1).to_numpy()
    diffs = tail[1:] - tail[:-1]   # window 个差值

    if direction == 'up':
        return bool((diffs > 0).all())
    if direction == 'down':
        return bool((diffs < 0).all())
    if direction == 'accel_up':
        pos = bool((diffs > 0).all())
        inc = all(diffs[i] < diffs[i + 1] for i in range(len(diffs) - 1))
        return pos and inc
    if direction == 'accel_down':
        neg = bool((diffs < 0).all())
        dec = all(diffs[i] > diffs[i + 1] for i in range(len(diffs) - 1))
        return neg and dec
    return False


def _match_all(conditions, df_map):
    """
    多条件 AND 判定：
    - PRC 比较条件：只看最新一根，单独判定。
    - EMA/MA 比较条件：按周期(freq)分组，同组内逐根同时满足，再窗口统计根数≥阈值。
    - 趋势条件：单独判定。
    全部通过才返回 True。
    """
    # 按周期收集 EMA/MA 比较条件
    ema_groups = {}  # freq -> [cond, ...]
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        if cond.get('type') != 'compare':
            continue
        if cond.get('right_kind') == 'prc':
            # PRC 只看最新一根，单独判定
            if not _prc_match(df_map, cond):
                return False
        else:
            freq = cond.get('freq', 'D')
            ema_groups.setdefault(freq, []).append(cond)

    # 每个周期的 EMA/MA 组：逐根同时满足，窗口统计
    for freq, group in ema_groups.items():
        series_list = []
        max_window = 1
        max_min_count = 1
        for cond in group:
            s = _cmp_bool_series(df_map, cond)
            if s is None:
                return False
            series_list.append(s)
            max_window = max(max_window, int(cond.get('window', 1)))
            max_min_count = max(max_min_count, int(cond.get('min_count', 1)))
        # 逐根同时满足（AND）
        combined = series_list[0]
        for s in series_list[1:]:
            combined = combined & s
        # 窗口统计
        tail = combined.tail(max_window).dropna()
        if len(tail) < max_window:
            return False
        if int(tail.sum()) < max_min_count:
            return False

    # 趋势条件单独判定
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        if cond.get('type') == 'trend':
            if not _eval_trend(df_map, cond):
                return False

    return True


# =====================================================================
# 条件描述（用于历史任务展示）
# =====================================================================
def _right_label(c):
    """右侧描述：均线 如 日线EMA(30)*1.1；PRC 如 价格10.5"""
    if c.get('right_kind') == 'prc':
        return f"价格{float(c.get('right_price', 0)):g}"
    freq = FREQ_LABEL.get(c.get('freq', 'D'), '日线')
    kind = KIND_LABEL.get(c.get('right_kind', 'ema'), 'EMA')
    p = int(c.get('right_period', 30))
    mult = float(c.get('right_mult', 1.0))
    base = f'{freq}{kind}({p})'
    if abs(mult - 1.0) < 1e-9:
        return base
    return f'{base}*{mult:g}'


def describe_conditions(conditions):
    lines = []
    for i, c in enumerate(conditions, 1):
        if c.get('type') == 'compare':
            freq = FREQ_LABEL.get(c.get('freq', 'D'), '日线')
            op = OP_LABEL.get(c.get('op', '>'), '大于')
            left_name = '成交量' if c.get('left_kind') == 'volume' else '收盘价'
            lm = float(c.get('left_mult', 1.0))
            left_txt = left_name if abs(lm - 1.0) < 1e-9 else f'{left_name}*{lm:g}'
            if c.get('right_kind') == 'prc':
                lines.append(f'{i}. {freq}：当日 {left_txt} {op} {_right_label(c)}')
            else:
                w = int(c.get('window', 1))
                n = int(c.get('min_count', 1))
                lines.append(
                    f'{i}. {freq}：近{w}根K线有≥{n}根 {left_txt} {op} {_right_label(c)}'
                )
        else:
            freq = FREQ_LABEL.get(c.get('freq', 'D'), '日线')
            kind = c.get('kind', 'ema')
            p = int(c.get('period', 30))
            w = int(c.get('window', 5))
            lines.append(
                f'{i}. {freq}{KIND_LABEL[kind]}({p}) 近{w}根呈「{DIR_LABEL.get(c.get("direction"), "")}」'
            )
    return lines


# =====================================================================
# 筛选样本
# =====================================================================
def _stock_sample(parent_task=None):
    """返回 [(code, market, name, cat), ...]"""
    if parent_task:
        qs = parent_task.results.all()
        return [(r.code, r.market, r.name, r.cat) for r in qs]
    cfg = FilterGlobalConfig.load()
    enabled = cfg.get_enabled()
    excl_st = cfg.is_exclude_st()
    qs = StockList.objects.exclude(hide='1').filter(cat='stock')
    rows = []
    for s in qs:
        if board_of_code(s.code) not in enabled:
            continue
        if excl_st and 'ST' in (s.name or '').upper():
            continue
        rows.append((s.code, s.market, s.name, s.cat))
    return rows


# =====================================================================
# Views
# =====================================================================
def _build_default_task():
    """
    从未筛选过（库内无任何 task）时，自动跑一次默认筛选：
    样本 = 全部非 hide 股票，条件 = 收盘价 > 0（PRC 固定价格），结果即全部样本。
    返回新建的 FilterTask。仅在 task 总数为 0 时调用。
    """
    default_cond = [{
        'type': 'compare', 'freq': 'D',
        'left_kind': 'close', 'left_mult': 1.0,
        'right_kind': 'prc', 'right_price': 0,
        'op': '>', 'window': 1, 'min_count': 1,
    }]
    sample = _stock_sample(None)
    task = FilterTask.objects.create(
        name='全部股票（默认）',
        parent=None,
        source=FilterTask.SOURCE_STOCK,
        conditions=json.dumps(default_cond, ensure_ascii=False),
        stock_count=len(sample),
    )
    for idx, (code, market, sname, cat) in enumerate(sample, 1):
        FilterResult.objects.get_or_create(
            task=task, code=code, market=market,
            defaults={'name': sname, 'cat': cat, 'sort_order': idx}
        )
    return task


def filter_list(request):
    """筛选结果清单。默认任务从全局配置读取，page/per_page 存 session，分页用统一工具。"""
    # 从未筛选过：自动建一条默认 task（收盘价>0，全量非隐藏股）
    if FilterTask.objects.count() == 0:
        _build_default_task()

    # POST：每页条数 / 翻页 / 二次筛选parent_id / 标记筛选（存 session，保持 URL 干净）
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': '无效JSON'}, status=400)
        if 'page' in data:
            func.set_cache(request.session, 'filter-list-page', int(data['page']))
        if 'per_page' in data:
            func.set_page_size(request.session, data['per_page'])
        if 'parent_id' in data:
            func.set_cache(request.session, 'filter-run-parent-id', data['parent_id'])
        if 'mark_filter' in data:
            func.set_cache(request.session, 'filter-list-mark-filter', data['mark_filter'])
            func.set_cache(request.session, 'filter-list-page', 1)  # 切换标记筛选时重置到第1页
        return JsonResponse({'status': 'success'})

    # GET：从全局配置读默认任务，0 或不存在则回退最新任务
    gcfg = FilterGlobalConfig.objects.first()
    default_id = gcfg.default_task_id if gcfg else 0
    task = FilterTask.objects.filter(id=default_id).first() if default_id else None
    if task is None:
        task = FilterTask.objects.first()
    if task:
        func.set_cache(request.session, 'filter-current-task', task.id)

    results_qs = task.results.exclude(hide='1').order_by('sort_order', 'id') if task else FilterResult.objects.none()

    # 标记筛选（后端过滤，与对比清单一致）
    mark_filter = func.get_cache(request.session, 'filter-list-mark-filter', 'all')
    if mark_filter not in ('all', '1', '2'):
        mark_filter = 'all'
    if mark_filter in ('1', '2'):
        results_qs = results_qs.filter(mark=mark_filter)

    # 统一分页（含 view-current-code 页码定位）
    pg = func.paginate_queryset(request, results_qs, 'filter-list-page')

    # 记录来源，供 view 返回列表时定位
    func.set_view_back(request.session, '/filter/list')
    # 标记筛选后的全量列表作为 view 的自定义 navi（跨页切换）
    custom_navi = [(r.code, r.market) for r in results_qs]
    func.set_cache(request.session, 'filter-view-custom-navi', custom_navi)
    # 失效旧导航缓存，确保 view 页面用新的 custom_navi 重新生成 navi（标记筛选后 next 正确）
    func.delete_cache(request.session, '/filter/view-navi-data')

    items = []
    base_no = (pg['current_page'] - 1) * pg['per_page']
    codes = [(r.code, r.market) for r in pg['items']]
    focused_set = set()
    if codes:
        watched = FocusStock.objects.filter(
            status=FocusStock.STATUS_WATCHING,
            code__in=[c for c, _ in codes],
        ).values_list('code', 'market')
        focused_set = set(watched)
    for idx, r in enumerate(pg['items']):
        items.append({
            'no': base_no + idx + 1,
            'code': r.code, 'market': r.market, 'name': r.name,
            'mark': r.mark,
            'focused': (r.code, r.market) in focused_set,
        })

    return render(request, 'filter-list.html', {
        'task': task,
        'tasks': FilterTask.objects.all()[:50],
        'items': items,
        'conditions_desc': describe_conditions(task.condition_list) if task else [],
        'per_page': pg['per_page'],
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'result_total': pg['total_count'],
        'current_mark_filter': mark_filter,
    })


def _run_filter_background(task_id, conditions, parent_id):
    """后台线程：逐股匹配，实时写 FilterResult，支持终止/超时回滚。"""
    from django.db import connection
    connection.close()  # 后台线程用新连接
    try:
        task = FilterTask.objects.get(id=task_id)
    except FilterTask.DoesNotExist:
        return
    parent = FilterTask.objects.filter(id=parent_id).first() if parent_id else None
    sample = _stock_sample(parent)
    total = len(sample)
    start_time = time.time()
    cache.set(FILTER_PROGRESS_KEY,
              {'task_id': task_id, 'done': 0, 'total': total, 'start_time': start_time},
              FILTER_RUNNING_TIMEOUT)

    cache_disk = {}
    passed_count = 0
    aborted = False
    for idx, (code, market, sname, cat) in enumerate(sample):
        # 强制终止
        if cache.get(FILTER_STOP_KEY):
            aborted = True
            break
        # 超时
        if time.time() - start_time > FILTER_RUNNING_TIMEOUT:
            cache.set(FILTER_TIMEOUT_KEY, '1', 120)
            aborted = True
            break
        df_map = _load_kline_map(cache_disk, code, market, cat, conditions)
        if df_map is None:
            continue
        if _match_all(conditions, df_map):
            FilterResult.objects.get_or_create(
                task=task, code=code, market=market,
                defaults={'name': sname, 'cat': cat, 'sort_order': passed_count + 1}
            )
            passed_count += 1
        # 每 10 只更新一次进度
        if (idx + 1) % 10 == 0 or idx + 1 == total:
            cache.set(FILTER_PROGRESS_KEY,
                      {'task_id': task_id, 'done': idx + 1, 'total': total, 'start_time': start_time},
                      FILTER_RUNNING_TIMEOUT)

    if aborted:
        # 回滚：删除本次 task 及其所有结果
        task.delete()
        # 保留终止/超时标志 60 秒，供前端轮询识别最终状态
        if cache.get(FILTER_TIMEOUT_KEY):
            cache.set(FILTER_TIMEOUT_KEY, '1', 60)
        else:
            cache.set(FILTER_STOP_KEY, '1', 60)
    else:
        task.status = FilterTask.STATUS_DONE
        task.stock_count = passed_count
        task.save()
        # 筛选完成后，默认任务自动改为最新筛选任务
        gcfg = FilterGlobalConfig.load()
        gcfg.default_task_id = task.id
        gcfg.save(update_fields=['default_task_id'])

    cache.delete(FILTER_PROGRESS_KEY)
    cache.delete(FILTER_RUNNING_KEY)


def filter_run(request):
    """条件配置页 / 执行筛选。二次筛选的 parent_id 存 session，URL 恒为 /filter/run。"""
    parent = None
    parent_id = func.get_cache(request.session, 'filter-run-parent-id')
    if parent_id:
        parent = FilterTask.objects.filter(id=parent_id).first()
        func.delete_cache(request.session, 'filter-run-parent-id')  # 消费掉，避免残留

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': '无效的JSON'}, status=400)

        conditions = data.get('conditions', [])
        name = data.get('name', '').strip()
        parent_id = data.get('parent_id')
        if parent_id:
            parent = FilterTask.objects.filter(id=parent_id).first()
        if not conditions:
            return JsonResponse({'status': 'error', 'message': '请至少添加一个筛选条件'}, status=400)

        # 防重复：已有筛选在跑则拒绝
        if cache.get(FILTER_RUNNING_KEY):
            return JsonResponse({'status': 'error', 'message': '正在筛选中，请等待本次完成后再试'},
                                status=409)
        cache.set(FILTER_RUNNING_KEY, '1', FILTER_RUNNING_TIMEOUT)
        cache.delete(FILTER_STOP_KEY)
        cache.delete(FILTER_TIMEOUT_KEY)
        cache.delete(FILTER_PROGRESS_KEY)

        # 先建 running task，后台线程实时写库
        task = FilterTask.objects.create(
            name=name or f'筛选#{FilterTask.objects.count() + 1}',
            parent=parent,
            source=FilterTask.SOURCE_TASK if parent else FilterTask.SOURCE_STOCK,
            conditions=json.dumps(conditions, ensure_ascii=False),
            stock_count=0,
            status=FilterTask.STATUS_RUNNING,
        )
        t = threading.Thread(target=_run_filter_background,
                             args=(task.id, conditions, parent.id if parent else None))
        t.daemon = True
        t.start()
        return JsonResponse({'status': 'running', 'task_id': task.id})

    # GET
    sample_total = len(_stock_sample(parent))
    # 检测是否有正在运行的筛选
    running_task = FilterTask.objects.filter(status=FilterTask.STATUS_RUNNING).first()
    running_state = None
    if running_task:
        prog = cache.get(FILTER_PROGRESS_KEY) or {}
        running_state = json.dumps({
            'task_id': running_task.id,
            'name': running_task.name,
            'done': int(prog.get('done', 0)),
            'total': int(prog.get('total', 0)),
        }, ensure_ascii=False)
    # 最近一次已完成筛选的条件（回填表单）
    last_task = FilterTask.objects.exclude(status=FilterTask.STATUS_RUNNING).order_by('-id').first()
    last_conditions = json.dumps(last_task.condition_list, ensure_ascii=False) if last_task else '[]'
    return render(request, 'filter-run.html', {
        'parent': parent,
        'parent_id': parent.id if parent else None,
        'sample_total': sample_total,
        'last_conditions': last_conditions,
        'running_state': running_state,
    })


def filter_run_status(request):
    """查询当前筛选进度。"""
    prog = cache.get(FILTER_PROGRESS_KEY)
    running = cache.get(FILTER_RUNNING_KEY) is not None
    timeout = cache.get(FILTER_TIMEOUT_KEY)
    stopped = cache.get(FILTER_STOP_KEY)

    if timeout:
        status = 'timeout'
    elif stopped:
        status = 'stopped'
    elif running:
        status = 'running'
    else:
        status = 'idle'

    return JsonResponse({
        'running': running,
        'status': status,
        'done': int(prog.get('done', 0)) if prog else 0,
        'total': int(prog.get('total', 0)) if prog else 0,
        'task_id': prog.get('task_id') if prog else None,
    })


def filter_run_stop(request):
    """强制终止当前筛选。"""
    if not cache.get(FILTER_RUNNING_KEY):
        return JsonResponse({'status': 'error', 'message': '当前没有筛选在运行'}, status=400)
    cache.set(FILTER_STOP_KEY, '1', 120)
    return JsonResponse({'status': 'stopping'})


def _toggle_mark(result, mark_type):
    """
    切换标记（优先股/潜力股），消除 major/minor 重复代码。
    mark_type: 'major' 或 'minor'
    """
    target_mark = FilterResult.MARK_PREF if mark_type == 'major' else FilterResult.MARK_POT
    result.mark = '' if result.mark == target_mark else target_mark
    result.save()
    return JsonResponse({
        'status': 'success',
        'major': result.mark if result.mark == FilterResult.MARK_PREF else '',
        'minor': result.mark if result.mark == FilterResult.MARK_POT else '',
    })


def _handle_hide(request, result, task, code, market):
    """
    隐藏股票：计算下一只/前一只、更新 StockList/FilterResult、更新 task stock_count、
    失效导航缓存、更新自定义 navi 列表。从 filter_view POST 中提取，提高可读性。
    """
    resp = {'status': 'success', 'hide': '1'}
    custom = func.get_cache(request.session, 'filter-view-custom-navi')
    if custom:
        custom_list = [tuple(x) for x in custom]
        try:
            idx = custom_list.index((code, market))
        except ValueError:
            idx = -1
        remaining = [x for x in custom_list if x != (code, market)]
        if 0 <= idx < len(remaining):
            nc, nm = remaining[idx]
            nres = FilterResult.objects.filter(code=nc, market=nm).order_by('-task_id').first()
            resp['next'] = {'code': nc, 'market': nm, 'name': nres.name if nres else ''}
        elif remaining:
            pc, pm = remaining[-1]
            pres = FilterResult.objects.filter(code=pc, market=pm).order_by('-task_id').first()
            resp['prev'] = {'code': pc, 'market': pm, 'name': pres.name if pres else ''}
    else:
        qs = FilterResult.objects.filter(task=task).exclude(hide='1').order_by('sort_order', 'id')
        nxt = qs.filter(sort_order__gt=result.sort_order).first()
        if nxt:
            resp['next'] = {'code': nxt.code, 'market': nxt.market, 'name': nxt.name}
        else:
            prv = qs.filter(sort_order__lt=result.sort_order).last()
            if prv:
                resp['prev'] = {'code': prv.code, 'market': prv.market, 'name': prv.name}
    # 隐藏该股票：同步 StockList，以及所有历史结果中的同代码记录
    with transaction.atomic():
        StockList.objects.filter(code=code, market=market).update(hide='1')
        FilterResult.objects.filter(code=code, market=market).update(hide='1')
        # 更新所有包含该股票的 FilterTask 的 stock_count
        for t in FilterTask.objects.filter(results__code=code, results__market=market).distinct():
            t.stock_count = t.results.exclude(hide='1').count()
            t.save(update_fields=['stock_count'])
    # 失效导航缓存
    func.delete_cache(request.session, '/filter/view-navi-data')
    # 更新自定义 navi 列表（对比页进入）：移除被 hide 的股票
    if custom:
        custom_list = [tuple(x) for x in custom if tuple(x) != (code, market)]
        func.set_cache(request.session, 'filter-view-custom-navi', custom_list)
    return JsonResponse(resp)


def _do_focus(result, ema_price=None):
    """
    关注/取消关注（双向）。
    - 未关注：建关注记录，plan_price=前端传来的当前 EMA 值；
      target=1.1倍，stop=0.98倍，数量按可用资金，备注「筛选时添加」，排在关注列表最后。
    - 已关注：关闭该记录，备注「筛选时关闭」。
    """
    existing = FocusStock.objects.filter(
        code=result.code, market=result.market,
        status=FocusStock.STATUS_WATCHING).first()

    import decimal
    if existing:
        # 取消关注
        with transaction.atomic():
            existing.status = FocusStock.STATUS_CLOSED
            existing.close_reason = FocusStock.CLOSE_REASON_MANUAL
            existing.close_date = timezone.now().date()
            existing.save()
            existing.save_history(action='close', comments='筛选时关闭')
        return JsonResponse({'status': 'success', 'focus': 0, 'msg': '已取消关注'})

    if ema_price is None:
        return JsonResponse({'status': 'error', 'message': 'EMA价格缺失'}, status=400)
    # 兼容前端误传 Highstock [时间戳, 值] 数组
    if isinstance(ema_price, (list, tuple)):
        ema_price = ema_price[1] if len(ema_price) >= 2 else None
    if ema_price is None or float(ema_price) <= 0:
        return JsonResponse({'status': 'error', 'message': 'EMA价格缺失'}, status=400)

    plan = float(ema_price)
    target = round(plan * TARGET_PROFIT_RATIO, 3)
    stop = round(plan * STOP_LOSS_RATIO, 3)
    qty = cash.calc_allowed_qty(plan, stop) if plan > 0 else 0

    # 排在关注列表最后
    from django.db.models import Max as _Max
    max_order = FocusStock.objects.aggregate(m=_Max('sort_order'))['m'] or 0

    with transaction.atomic():
        new_focus = FocusStock.objects.create(
            code=result.code, name=result.name, market=result.market, cat=result.cat,
            plan_price=decimal.Decimal(str(round(plan, 3))),
            plan_qty=qty,
            target_price=decimal.Decimal(str(target)),
            stop_price=decimal.Decimal(str(stop)),
            allowed_qty=qty,
            sort_order=max_order + 1,
        )
        new_focus.save_history(action='create', comments='筛选时添加')
    return JsonResponse({'status': 'success', 'focus': 1,
                         'plan': round(plan, 3), 'target': target, 'stop': stop, 'qty': qty})


# ===================== /stocks/view 模式辅助函数 =====================

def _toggle_mark_stocks(stock, mark_type):
    """切换 StockList 全局标记（优选股/潜力股）"""
    target_mark = '1' if mark_type == 'major' else '2'
    stock.mark = '' if stock.mark == target_mark else target_mark
    stock.save()
    return JsonResponse({
        'status': 'success',
        'major': stock.mark if stock.mark == '1' else '',
        'minor': stock.mark if stock.mark == '2' else '',
    })


def _handle_hide_stocks(request, code, market):
    """
    /stocks/view 模式隐藏股票：计算下一只/前一只、更新 StockList/FilterResult、
    更新 task stock_count、失效导航缓存、更新 stocks-view-custom-navi。
    """
    resp = {'status': 'success', 'hide': '1'}
    custom = func.get_cache(request.session, 'stocks-view-custom-navi')
    if custom:
        custom_list = [tuple(x) for x in custom]
        try:
            idx = custom_list.index((code, market))
        except ValueError:
            idx = -1
        remaining = [x for x in custom_list if x != (code, market)]
        if 0 <= idx < len(remaining):
            nc, nm = remaining[idx]
            nstock = StockList.objects.filter(code=nc, market=nm).first()
            resp['next'] = {'code': nc, 'market': nm, 'name': nstock.name if nstock else ''}
        elif remaining:
            pc, pm = remaining[-1]
            pstock = StockList.objects.filter(code=pc, market=pm).first()
            resp['prev'] = {'code': pc, 'market': pm, 'name': pstock.name if pstock else ''}
    # 隐藏该股票：同步 StockList，以及所有历史结果中的同代码记录
    with transaction.atomic():
        StockList.objects.filter(code=code, market=market).update(hide='1')
        FilterResult.objects.filter(code=code, market=market).update(hide='1')
        # 更新所有包含该股票的 FilterTask 的 stock_count
        for t in FilterTask.objects.filter(results__code=code, results__market=market).distinct():
            t.stock_count = t.results.exclude(hide='1').count()
            t.save(update_fields=['stock_count'])
    # 失效导航缓存
    func.delete_cache(request.session, '/stocks/view-navi-data')
    # 更新自定义 navi 列表：移除被 hide 的股票
    if custom:
        custom_list = [tuple(x) for x in custom if tuple(x) != (code, market)]
        func.set_cache(request.session, 'stocks-view-custom-navi', custom_list)
    return JsonResponse(resp)


def _do_focus_stocks(stock, ema_price=None):
    """/stocks/view 模式关注/取消关注（复用 _do_focus 逻辑，传入 StockList 对象）"""
    return _do_focus(stock, ema_price)


def _handle_hide_refer(request, code, market):
    """
    /refer/view 模式隐藏股票：计算下一只/前一只、更新 StockList/FilterResult、
    更新 task stock_count、失效导航缓存、更新 refer-view-custom-navi。
    """
    resp = {'status': 'success', 'hide': '1'}
    custom = func.get_cache(request.session, 'refer-view-custom-navi')
    if custom:
        custom_list = [tuple(x) for x in custom]
        try:
            idx = custom_list.index((code, market))
        except ValueError:
            idx = -1
        remaining = [x for x in custom_list if x != (code, market)]
        if 0 <= idx < len(remaining):
            nc, nm = remaining[idx]
            nstock = StockList.objects.filter(code=nc, market=nm).first()
            resp['next'] = {'code': nc, 'market': nm, 'name': nstock.name if nstock else ''}
        elif remaining:
            pc, pm = remaining[-1]
            pstock = StockList.objects.filter(code=pc, market=pm).first()
            resp['prev'] = {'code': pc, 'market': pm, 'name': pstock.name if pstock else ''}
    # 隐藏该股票：同步 StockList，以及所有历史结果中的同代码记录
    with transaction.atomic():
        StockList.objects.filter(code=code, market=market).update(hide='1')
        FilterResult.objects.filter(code=code, market=market).update(hide='1')
        # 更新所有包含该股票的 FilterTask 的 stock_count
        for t in FilterTask.objects.filter(results__code=code, results__market=market).distinct():
            t.stock_count = t.results.exclude(hide='1').count()
            t.save(update_fields=['stock_count'])
    # 失效导航缓存
    func.delete_cache(request.session, '/refer/view-navi-data')
    # 更新自定义 navi 列表：移除被 hide 的股票
    if custom:
        custom_list = [tuple(x) for x in custom if tuple(x) != (code, market)]
        func.set_cache(request.session, 'refer-view-custom-navi', custom_list)
    return JsonResponse(resp)


def filter_view(request, market, code):
    """单只股票详情（K线）。支持 /filter/view、/stocks/view、/refer/view 三种模式。"""
    # 根据请求路径区分模式
    if request.path.startswith('/stocks/view'):
        site = '/stocks/view'
    elif request.path.startswith('/refer/view'):
        site = '/refer/view'
    else:
        site = '/filter/view'

    if site == '/stocks/view':
        # ===================== /stocks/view 模式 =====================
        stock = StockList.objects.filter(code=code, market=market).first()
        if stock is None:
            raise Http404('股票不存在')

        if request.method == 'POST':
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'error': '无效JSON'}, status=400)
            func_name = data.get('func')
            if func_name in ('major', 'minor'):
                return _toggle_mark_stocks(stock, func_name)
            elif func_name == 'hide':
                return _handle_hide_stocks(request, code, market)
            elif func_name == 'focus':
                return _do_focus_stocks(stock, data.get('ema_price'))
            else:
                return JsonResponse({'status': 'error', 'message': '未知操作'})

        # GET
        func.set_view_current_code(request.session, code)
        navi_data = func.get_cache(request.session, f'{site}-navi-data', {})
        if (site, code, market) != navi_data.get('site_code_market', None):
            navi_data = chart.set_navi_data(request.session, site, code, market, None, 'init')

        # 股票不在导航列表中（已被 hide 或不存在），返回来源列表
        if not navi_data:
            back_url = func.get_view_back(request.session) or '/sector/list'
            return redirect(back_url)

        func.set_cache(request.session, 'view', 'kline')
        back_url = func.get_view_back(request.session) or '/sector/list'
        chart_init = {
            'site': site,
            'code': code,
            'market': market,
            'name': stock.name,
            'cat': stock.cat,
            'view': 'kline',
            'backUrl': back_url,
        }
        return render(request, 'filter-view.html', {
            'chart': json.dumps(chart_init),
            'mark': stock.mark,
            'task_id': 0,
        })

    if site == '/refer/view':
        # ===================== /refer/view 模式（筛选对比结果） =====================
        # 优先从 FilterResult 找最新记录（获取名称），找不到则从 StockList 查找
        result = FilterResult.objects.filter(code=code, market=market).order_by('-task_id').first()
        if result:
            stock_name = result.name
            stock_cat = result.cat
            stock_mark = result.mark
        else:
            stock = StockList.objects.filter(code=code, market=market).first()
            if stock is None:
                raise Http404('股票不存在')
            stock_name = stock.name
            stock_cat = stock.cat
            stock_mark = stock.mark

        if request.method == 'POST':
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse({'error': '无效JSON'}, status=400)
            func_name = data.get('func')
            if func_name in ('major', 'minor'):
                # 操作 StockList 全局标记
                stock = StockList.objects.filter(code=code, market=market).first()
                if stock:
                    return _toggle_mark_stocks(stock, func_name)
                return JsonResponse({'status': 'error', 'message': '股票不存在'})
            elif func_name == 'hide':
                return _handle_hide_refer(request, code, market)
            elif func_name == 'focus':
                stock = StockList.objects.filter(code=code, market=market).first()
                if stock:
                    return _do_focus_stocks(stock, data.get('ema_price'))
                return JsonResponse({'status': 'error', 'message': '股票不存在'})
            else:
                return JsonResponse({'status': 'error', 'message': '未知操作'})

        # GET
        func.set_view_current_code(request.session, code)
        navi_data = func.get_cache(request.session, f'{site}-navi-data', {})
        if (site, code, market) != navi_data.get('site_code_market', None):
            navi_data = chart.set_navi_data(request.session, site, code, market, None, 'init')

        # 股票不在导航列表中（已被 hide 或不存在），返回来源列表
        if not navi_data:
            back_url = func.get_view_back(request.session) or '/refer/list'
            return redirect(back_url)

        func.set_cache(request.session, 'view', 'kline')
        back_url = func.get_view_back(request.session) or '/refer/list'
        chart_init = {
            'site': site,
            'code': code,
            'market': market,
            'name': stock_name,
            'cat': stock_cat,
            'view': 'kline',
            'backUrl': back_url,
        }
        return render(request, 'filter-view.html', {
            'chart': json.dumps(chart_init),
            'mark': stock_mark,
            'task_id': 0,
        })

    # ===================== /filter/view 模式（原有逻辑） =====================
    # 候选 task_id 依次尝试：current -> list；任一不存在则跳过，避免 session 残留旧 task 导致 404
    candidates = [
        func.get_cache(request.session, 'filter-current-task'),
        func.get_cache(request.session, 'filter-list-task'),
    ]
    task = None
    for tid in candidates:
        if not tid:
            continue
        task = FilterTask.objects.filter(id=tid).first()
        if task:
            break
    if task is None:
        task = FilterTask.objects.first()
    if task is None:
        raise Http404('无筛选任务')

    result = FilterResult.objects.filter(task=task, code=code, market=market).first()
    if result is None:
        # 当前 task 不含该股：回退到含该 code 的最新结果（如 session 残留旧 task）
        result = FilterResult.objects.filter(code=code, market=market).order_by('-task_id').first()
        if result is None:
            raise Http404('无该股票结果')
        task = result.task
    func.set_cache(request.session, 'filter-current-task', task.id)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效JSON'}, status=400)

        func_name = data.get('func')
        if func_name in ('major', 'minor'):
            return _toggle_mark(result, func_name)
        elif func_name == 'hide':
            return _handle_hide(request, result, task, code, market)
        elif func_name == 'focus':
            return _do_focus(result, data.get('ema_price'))
        else:
            return JsonResponse({'status': 'error', 'message': '未知操作'})

    # GET
    func.set_cache(request.session, 'filter-current-task', task.id)
    func.set_view_current_code(request.session, code)
    navi_data = func.get_cache(request.session, '/filter/view-navi-data', {})
    if ('/filter/view', code, market) != navi_data.get('site_code_market', None):
        navi_data = chart.set_navi_data(request.session, '/filter/view', code, market, None, 'init')

    # 股票不在导航列表中（已被 hide 或不存在），返回来源列表
    if not navi_data:
        back_url = func.get_view_back(request.session) or '/filter/list'
        return redirect(back_url)

    func.set_cache(request.session, 'view', 'kline')
    # backUrl 统一使用 get_view_back（筛选列表/对比列表各自设置）
    back_url = func.get_view_back(request.session) or '/filter/list'
    chart_init = {
        'site': '/filter/view',
        'code': code,
        'market': market,
        'name': result.name,
        'cat': result.cat,
        'view': 'kline',
        'taskId': task.id,
        'backUrl': back_url,
    }
    return render(request, 'filter-view.html', {
        'chart': json.dumps(chart_init),
        'mark': result.mark,
        'task_id': task.id,
    })


def refer_list(request):
    """两次筛选结果对比，后端分页。所有状态（task_a/task_b/scope/page/per_page）均存 session，URL 恒为 /refer/list。"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': '无效JSON'}, status=400)
        if 'task_a' in data:
            func.set_cache(request.session, 'filter-refer-task-a', data['task_a'])
        if 'task_b' in data:
            func.set_cache(request.session, 'filter-refer-task-b', data['task_b'])
        if 'scope' in data:
            scope_val = data['scope'] if data['scope'] in ('all', 'both', 'only_a', 'only_b') else 'all'
            func.set_cache(request.session, 'filter-refer-scope', scope_val)
        if 'page' in data:
            func.set_cache(request.session, 'filter-refer-page', int(data['page']))
        if 'per_page' in data:
            func.set_page_size(request.session, data['per_page'])
        if 'from_view' in data:
            func.set_cache(request.session, 'filter-refer-from-view', data['from_view'])
            func.set_view_back(request.session, '/refer/list')
        # 所有对比页内部 POST 操作后刷新，均保留任务选择（避免重新弹窗）
        func.set_cache(request.session, 'filter-refer-from-view', '1')
        return JsonResponse({'status': 'success'})

    tasks = [
        {'id': t.id, 'name': t.name, 'stock_count': t.results.exclude(hide='1').count(), 'parent_id': t.parent_id}
        for t in FilterTask.objects.all()[:50]
    ]

    # 判断是否从 view 返回：使用独立标记，避免 view-back-url 残留误判
    from_view = bool(func.get_cache(request.session, 'filter-refer-from-view'))
    func.delete_cache(request.session, 'filter-refer-from-view')  # 消费掉，只生效一次

    if from_view:
        # 从 view 返回：尝试保留 session 中的选择
        a_id = func.get_cache(request.session, 'filter-refer-task-a')
        b_id = func.get_cache(request.session, 'filter-refer-task-b')
    else:
        a_id = b_id = None

    # 只要没有有效选择（首次进入、取消后再进、或session无值），就统一计算默认任务A/B
    if not a_id or not b_id:
        func.delete_cache(request.session, 'filter-refer-task-a')
        func.delete_cache(request.session, 'filter-refer-task-b')
        func.delete_cache(request.session, 'filter-refer-scope')
        a_id = b_id = None
        # 任务A：当前默认任务（设定页面设置的 default_task_id），未设置则兜底最近任务
        gcfg = FilterGlobalConfig.objects.first()
        default_a = gcfg.default_task_id if gcfg and gcfg.default_task_id else None
        if not default_a:
            latest_task = FilterTask.objects.order_by('-id').first()
            default_a = latest_task.id if latest_task else None
        # 任务B：按优先级查找——子任务→父任务→最近任务（排除A）
        default_b = None
        if default_a:
            # 1. 任务A是否有子任务（其他任务的parent_id=任务A），取最新子任务
            child = FilterTask.objects.filter(parent_id=default_a).order_by('-id').first()
            if child:
                default_b = child.id
            else:
                # 2. 任务A是否有父任务
                task_a_obj = FilterTask.objects.filter(id=default_a).first()
                if task_a_obj and task_a_obj.parent_id:
                    default_b = task_a_obj.parent_id
                else:
                    # 3. 无关联任务：取最近任务，若A是最近则取第二近；只有一个任务时取自身
                    latest_two = list(FilterTask.objects.order_by('-id')[:2])
                    if latest_two:
                        if latest_two[0].id != default_a:
                            default_b = latest_two[0].id
                        elif len(latest_two) > 1:
                            default_b = latest_two[1].id
                        else:
                            default_b = latest_two[0].id
    else:
        default_a = default_b = None

    scope = func.get_cache(request.session, 'filter-refer-scope', 'all')
    if scope not in ('all', 'both', 'only_a', 'only_b'):
        scope = 'all'

    ta = FilterTask.objects.filter(id=a_id).first() if a_id else None
    tb = FilterTask.objects.filter(id=b_id).first() if b_id else None

    rows = []
    count_a = count_b = count_both = 0
    if ta and tb:
        map_a = {(r.code, r.market): r for r in ta.results.exclude(hide='1')}
        map_b = {(r.code, r.market): r for r in tb.results.exclude(hide='1')}
        count_a = len(map_a)
        count_b = len(map_b)
        count_both = len(set(map_a) & set(map_b))
        keys = set(map_a) | set(map_b)
        for key in sorted(keys):
            in_a = key in map_a
            in_b = key in map_b
            r = map_a.get(key) or map_b.get(key)
            if in_a and in_b:
                region = 'both'
            elif in_a:
                region = 'only_a'
            else:
                region = 'only_b'
            if scope != 'all' and region != scope:
                continue
            rows.append({
                'code': key[0], 'market': key[1], 'name': r.name,
                'region': region,
            })

    # 用统一分页工具（rows 是 list，包装成支持 .iterator() / 切片的对象）
    class _RowIter:
        def __init__(self, rows): self._rows = rows
        def iterator(self): return iter(self._rows)
        def __iter__(self): return iter(self._rows)
        def __getitem__(self, key): return self._rows[key]
        def count(self): return len(self._rows)
        def __len__(self): return len(self._rows)

    # 统一分页（page/per_page 均从 session 读取）

    pg = func.paginate_queryset(
        request, _RowIter(rows), 'filter-refer-page',
        code_getter=lambda obj: obj['code']
    )

    # 全量过滤后的列表作为 view 自定义 navi（可跨页）
    custom_navi = [(r['code'], r['market']) for r in rows]
    func.set_cache(request.session, 'refer-view-custom-navi', custom_navi)
    func.delete_cache(request.session, '/refer/view-navi-data')
    func.set_view_back(request.session, '/refer/list')

    return render(request, 'filter-refer.html', {
        'tasks': tasks,
        'tasks_json': json.dumps(tasks, ensure_ascii=False),
        'task_a': ta,
        'task_b': tb,
        'scope': scope,
        'has_selection': bool(from_view and ta and tb),
        'default_a': default_a,
        'default_b': default_b,
        'items': pg['items'],
        'base_no': (pg['current_page'] - 1) * pg['per_page'] + 1,
        'current_page': pg['current_page'],
        'total_pages': pg['total_pages'],
        'per_page': pg['per_page'],
        'result_total': pg['total_count'],
        'count_a': count_a,
        'count_b': count_b,
        'count_both': count_both,
    })


def filter_config(request):
    """筛选历史任务管理（查看条件、删除）。"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效JSON'}, status=400)
        if data.get('action') == 'delete':
            t = FilterTask.objects.filter(id=data.get('task_id')).first()
            if t:
                t.delete()
                return JsonResponse({'status': 'success'})
            return JsonResponse({'status': 'error', 'message': '任务不存在'}, status=404)
        if data.get('action') == 'save_boards':
            keys = data.get('boards', [])
            cfg = FilterGlobalConfig.load()
            cfg.set_enabled(keys)
            if 'exclude_st' in data:
                cfg.set_exclude_st(bool(data.get('exclude_st')))
            return JsonResponse({'status': 'success',
                                 'enabled': sorted(cfg.get_enabled()),
                                 'exclude_st': cfg.is_exclude_st()})
        if data.get('action') == 'save_exclude_st':
            cfg = FilterGlobalConfig.load()
            cfg.set_exclude_st(bool(data.get('exclude_st')))
            return JsonResponse({'status': 'success',
                                 'exclude_st': cfg.is_exclude_st()})
        if data.get('action') == 'set_default':
            tid = data.get('task_id')
            if FilterTask.objects.filter(id=tid).exists():
                cfg = FilterGlobalConfig.load()
                cfg.default_task_id = tid
                cfg.save(update_fields=['default_task_id'])
                return JsonResponse({'status': 'success'})
            return JsonResponse({'status': 'error', 'message': '任务不存在'}, status=404)
        return JsonResponse({'status': 'error', 'message': '未知操作'}, status=400)

    # 统计各板块股票数量（未隐藏）
    all_stocks = StockList.objects.exclude(hide='1').filter(cat='stock')
    board_counts = {key: 0 for key, _lbl, _pre in BOARD_DEFS}
    for s in all_stocks:
        k = board_of_code(s.code)
        if k in board_counts:
            board_counts[k] += 1
    cfg = FilterGlobalConfig.load()
    enabled_set = cfg.get_enabled()
    boards = [
        {'key': k, 'label': BOARD_LABELS[k], 'count': board_counts[k],
         'checked': k in enabled_set}
        for k, _lbl, _pre in BOARD_DEFS
    ]

    tasks = []
    for t in FilterTask.objects.all()[:100]:
        tasks.append({
            'id': t.id,
            'name': t.name,
            'source': t.source_display_label,
            'count': t.results.exclude(hide='1').count(),
            'created': t.created_at.strftime('%Y-%m-%d'),
            'lines': describe_conditions(t.condition_list),
        })
    return render(request, 'filter-config.html', {
        'tasks': tasks, 'boards': boards,
        'exclude_st': cfg.is_exclude_st(),
        'default_task_id': cfg.default_task_id,
    })
