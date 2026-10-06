import json
import time
import logging
import threading
import datetime
from decimal import Decimal
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db import transaction
from ..fetch import tushare
from . import chart
from .. import utils
from ..models import (StockList, FilterTask, FilterResult, FocusStock,
                            FilterConfig, BOARD_DEFS, BOARD_LABELS, board_of_code, ReviewList)
from django.core.cache import cache

logger = logging.getLogger('stock')

# 筛选进行中的全局锁（防止并发重复筛选）
FILTER_RUNNING_KEY = 'filter-running'

# 筛选添加关注时的默认倍率（从数据库读取，此处仅作兜底）
FILTER_PROGRESS_KEY = 'filter-progress'
FILTER_STOP_KEY = 'filter-stop'
FILTER_TIMEOUT_KEY = 'filter-timeout'


def _get_filter_config():
    """获取筛选全局配置"""
    return FilterConfig.load()


def _get_filter_timeout():
    """获取筛选超时时间（秒）"""
    try:
        return int(_get_filter_config().filter_timeout)
    except Exception:
        return 3600


def _get_target_profit_ratio():
    """获取添加关注目标价倍率"""
    try:
        return float(_get_filter_config().target_profit_ratio)
    except Exception:
        return 1.1


def _get_stop_loss_ratio():
    """获取添加关注止损价倍率"""
    try:
        return float(_get_filter_config().stop_loss_ratio)
    except Exception:
        return 0.98


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
    end = datetime.datetime.now().strftime('%Y%m%d')
    need_freqs = _used_freqs(conditions)

    df_map = {}
    for freq in sorted(need_freqs):
        try:
            from ..fetch.config import get_kline_start_date
            start = get_kline_start_date(freq)
            df = tushare.get_kline_data(
                asset=asset, tscode=tscode, start=start, end=end,
                freq=freq, adj='qfq'
            )
        except Exception:
            logger.exception('[filter] K线获取失败 %s %s', tscode, freq)
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
    cfg = FilterConfig.load()
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
    # 自动设为默认任务
    cfg = FilterConfig.load()
    cfg.default_task_id = task.id
    cfg.save(update_fields=['default_task_id'])
    return task


def filter_list(request):
    """筛选结果清单。默认任务从全局配置读取，page/per_page 存 session，分页用统一工具。"""
    # 从未筛选过：自动建一条默认 task（收盘价>0，全量非隐藏股）
    if FilterTask.objects.count() == 0:
        _build_default_task()

    # POST：每页条数 / 翻页 / 二次筛选parent_id / 标记筛选（存 session，保持 URL 干净）
    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        if 'page' in data:
            utils.set_cache(request.session, 'filter-list-page', int(data['page']))
        if 'per_page' in data:
            utils.set_page_size(request.session, data['per_page'])
        if 'parent_id' in data:
            utils.set_cache(request.session, 'filter-run-parent-id', data['parent_id'])
        if 'mark_filter' in data:
            utils.set_cache(request.session, 'filter-list-mark-filter', data['mark_filter'])
            utils.set_cache(request.session, 'filter-list-page', 1)  # 切换标记筛选时重置到第1页
        return JsonResponse({'status': 'success'})

    # GET：从全局配置读默认任务，0 或不存在则回退最新任务
    gcfg = FilterConfig.objects.first()
    default_id = gcfg.default_task_id if gcfg else 0
    task = FilterTask.objects.filter(id=default_id).first() if default_id else None
    if task is None:
        task = FilterTask.objects.first()
    if task:
        utils.set_cache(request.session, 'filter-current-task', task.id)

    results_qs = task.results.exclude(hide='1').order_by('sort_order', 'id') if task else FilterResult.objects.none()

    # 标记筛选（后端过滤，与对比清单一致）
    mark_filter = utils.get_cache(request.session, 'filter-list-mark-filter', 'all')
    if mark_filter not in ('all', '1', '2'):
        mark_filter = 'all'
    if mark_filter in ('1', '2'):
        results_qs = results_qs.filter(mark=mark_filter)

    # 统一分页（含 view-current-code 页码定位）
    pg = utils.paginate_queryset(request, results_qs, 'filter-list-page')

    # 记录来源，供 view 返回列表时定位
    utils.set_view_back(request.session, '/filter/list')
    # 标记筛选后的全量列表作为 view 的自定义 navi（跨页切换）
    custom_navi = [(r.id, r.code, r.market) for r in results_qs]
    utils.set_cache(request.session, 'filter-view-custom-navi', custom_navi)
    # 失效旧导航缓存，确保 view 页面用新的 custom_navi 重新生成 navi（标记筛选后 next 正确）
    utils.delete_cache(request.session, '/filter/view-navi-data')

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
    filter_timeout = _get_filter_timeout()
    cache.set(FILTER_PROGRESS_KEY,
              {'task_id': task_id, 'done': 0, 'total': total, 'start_time': start_time},
              filter_timeout)

    cache_disk = {}
    passed_count = 0
    aborted = False
    for idx, (code, market, sname, cat) in enumerate(sample):
        # 强制终止
        if cache.get(FILTER_STOP_KEY):
            aborted = True
            break
        # 超时
        if time.time() - start_time > filter_timeout:
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
                      filter_timeout)

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
        gcfg = FilterConfig.load()
        gcfg.default_task_id = task.id
        gcfg.save(update_fields=['default_task_id'])

    cache.delete(FILTER_PROGRESS_KEY)
    cache.delete(FILTER_RUNNING_KEY)


def filter_run(request):
    """条件配置页 / 执行筛选。二次筛选的 parent_id 存 session，URL 恒为 /filter/run。"""
    parent = None
    parent_id = utils.get_cache(request.session, 'filter-run-parent-id')
    if parent_id:
        parent = FilterTask.objects.filter(id=parent_id).first()
        utils.delete_cache(request.session, 'filter-run-parent-id')  # 消费掉，避免残留

    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        # 注：原错误文案为“无效的JSON”，统一为公共 400 响应

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
        cache.set(FILTER_RUNNING_KEY, '1', _get_filter_timeout())
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


def _toggle_mark_obj(obj, mark_type):
    """
    统一切换标记（优先股/潜力股），同时适用于 FilterResult 与 StockList。
    mark_type: 'major' 或 'minor'
    """
    if isinstance(obj, FilterResult):
        pref, pot = FilterResult.MARK_PREF, FilterResult.MARK_POT
    else:
        pref, pot = '1', '2'
    target = pref if mark_type == 'major' else pot
    obj.mark = '' if obj.mark == target else target
    obj.save()
    return JsonResponse({
        'status': 'success',
        'major': obj.mark if obj.mark == pref else '',
        'minor': obj.mark if obj.mark == pot else '',
    })


def _view_obj_name(code, market, name_source):
    """view 页切换时取下一只/前一只名称：'result' 取最新 FilterResult，'stock' 取 StockList。"""
    if name_source == 'result':
        obj = FilterResult.objects.filter(code=code, market=market).order_by('-task_id').first()
    else:
        obj = StockList.objects.filter(code=code, market=market).first()
    return obj.name if obj else ''


def _handle_hide_view(request, site, code, market, custom_key,
                      name_source='stock', result=None, task=None):
    """
    统一处理 view 页面隐藏股票（filter/stocks/refer 三模式复用）：
    - 计算下一只/前一只（优先 custom navi；filter 模式无 custom 时用该 task 结果集）
    - 同步 StockList / 全部 FilterResult 的 hide、更新相关 task 的 stock_count
    - 失效 navi 缓存、更新 custom navi
    """
    resp = {'status': 'success', 'hide': '1'}
    custom = utils.get_cache(request.session, custom_key)
    if custom:
        custom_list = [tuple(x) for x in custom]
        idx = next((i for i, it in enumerate(custom_list) if it[1] == code and it[2] == market), -1)
        remaining = [x for x in custom_list if x[1] != code or x[2] != market]
        if 0 <= idx < len(remaining):
            _, nc, nm = remaining[idx]
            resp['next'] = {'code': nc, 'market': nm, 'name': _view_obj_name(nc, nm, name_source)}
        elif remaining:
            _, pc, pm = remaining[-1]
            resp['prev'] = {'code': pc, 'market': pm, 'name': _view_obj_name(pc, pm, name_source)}
    elif result is not None and task is not None:
        qs = task.results.exclude(hide='1').order_by('sort_order', 'id')
        nxt = qs.filter(sort_order__gt=result.sort_order).first()
        if nxt:
            resp['next'] = {'code': nxt.code, 'market': nxt.market, 'name': nxt.name}
        else:
            prv = qs.filter(sort_order__lt=result.sort_order).last()
            if prv:
                resp['prev'] = {'code': prv.code, 'market': prv.market, 'name': prv.name}

    with transaction.atomic():
        StockList.objects.filter(code=code, market=market).update(hide='1')
        FilterResult.objects.filter(code=code, market=market).update(hide='1')
        for t in FilterTask.objects.filter(results__code=code, results__market=market).distinct():
            t.stock_count = t.results.exclude(hide='1').count()
            t.save(update_fields=['stock_count'])

    utils.delete_cache(request.session, f'{site}-navi-data')
    if custom:
        custom_list = [tuple(x) for x in custom if x[1] != code or x[2] != market]
        utils.set_cache(request.session, custom_key, custom_list)
    return JsonResponse(resp)


def _do_focus(result, ema_price=None, comments='筛选时添加'):
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
            # 创建复盘记录
            ReviewList.objects.update_or_create(
                focus_stock=existing,
                defaults={
                    'review_type': ReviewList.TYPE_FOCUS,
                    'code': existing.code,
                    'market': existing.market,
                    'name': existing.name,
                    'cat': existing.cat,
                    'open_date': existing.focus_date,
                    'close_date': existing.close_date,
                    'plan_price': existing.plan_price,
                    'target_price': existing.target_price,
                }
            )
        return JsonResponse({'status': 'success', 'focus': 0, 'msg': '已取消关注'})

    if ema_price is None:
        return JsonResponse({'status': 'error', 'message': 'EMA价格缺失'}, status=400)
    # 兼容前端误传对象的情况
    if isinstance(ema_price, dict):
        ema_price = ema_price.get('ema_price') or ema_price.get('price')
    # 兼容前端误传 Highstock [时间戳, 值] 数组
    if isinstance(ema_price, (list, tuple)):
        ema_price = ema_price[1] if len(ema_price) >= 2 else None
    if ema_price is None or float(ema_price) <= 0:
        return JsonResponse({'status': 'error', 'message': 'EMA价格缺失'}, status=400)

    plan = float(ema_price)
    deci = utils.price_places(result.cat)
    target = round(plan * _get_target_profit_ratio(), deci)
    stop = round(plan * _get_stop_loss_ratio(), deci)
    qty = utils.calc_allowed_qty(plan, stop) if plan > 0 else 0

    # 排在关注列表最后
    from django.db.models import Max as _Max
    max_order = FocusStock.objects.aggregate(m=_Max('sort_order'))['m'] or 0

    with transaction.atomic():
        new_focus = FocusStock.objects.create(
            code=result.code, name=result.name, market=result.market, cat=result.cat,
            plan_price=decimal.Decimal(str(round(plan, deci))),
            plan_qty=qty,
            target_price=decimal.Decimal(str(target)),
            stop_price=decimal.Decimal(str(stop)),
            allowed_qty=qty,
            sort_order=max_order + 1,
        )
        new_focus.save_history(action='create', comments=comments)
    return JsonResponse({'status': 'success', 'focus': 1,
                         'plan': round(plan, deci), 'target': target, 'stop': stop, 'qty': qty})



# 各 view 模式：(默认返回列表, custom navi key, 名称来源)
_VIEW_DEFAULTS = {
    '/filter/view': ('/filter/list', 'filter-view-custom-navi', 'result'),
    '/stocks/view': ('/sector/list', 'stocks-view-custom-navi', 'stock'),
    '/refer/view': ('/refer/list', 'refer-view-custom-navi', 'stock'),
}


def _resolve_view_site(path):
    if path.startswith('/stocks/view'):
        return '/stocks/view'
    if path.startswith('/refer/view'):
        return '/refer/view'
    return '/filter/view'


def _resolve_view_target(site, request, code, market):
    """
    解析该模式下的目标，返回 (ctx, error_response)。
    ctx 含 name/cat/mark/task_id/mark_obj/focus_obj/custom_key/name_source/default_back，
    filter 模式另含 result/task（供无 custom navi 时计算下一只/前一只）。
    """
    default_back, custom_key, name_source = _VIEW_DEFAULTS[site]

    if site == '/stocks/view':
        stock = StockList.objects.filter(code=code, market=market).first()
        if stock is None:
            return None, Http404('股票不存在')
        ctx = {
            'name': stock.name, 'cat': stock.cat, 'mark': stock.mark, 'task_id': 0,
            'mark_obj': stock, 'focus_obj': stock,
            'custom_key': custom_key, 'name_source': name_source, 'default_back': default_back,
        }
        return ctx, None

    if site == '/refer/view':
        result = FilterResult.objects.filter(code=code, market=market).order_by('-task_id').first()
        stock = StockList.objects.filter(code=code, market=market).first()
        if result:
            name, cat, mark = result.name, result.cat, result.mark
        elif stock:
            name, cat, mark = stock.name, stock.cat, stock.mark
        else:
            return None, Http404('股票不存在')
        ctx = {
            'name': name, 'cat': cat, 'mark': mark, 'task_id': 0,
            'mark_obj': stock, 'focus_obj': stock,
            'custom_key': custom_key, 'name_source': name_source, 'default_back': default_back,
        }
        return ctx, None

    # /filter/view：候选 task_id 依次尝试 current -> list，避免 session 残留旧 task
    candidates = [
        utils.get_cache(request.session, 'filter-current-task'),
        utils.get_cache(request.session, 'filter-list-task'),
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
        return None, redirect('filter_list')

    result = FilterResult.objects.filter(task=task, code=code, market=market).first()
    if result is None:
        # 当前 task 不含该股：回退到含该 code 的最新结果
        result = FilterResult.objects.filter(code=code, market=market).order_by('-task_id').first()
        if result is None:
            return None, redirect('filter_list')
        task = result.task
    utils.set_cache(request.session, 'filter-current-task', task.id)
    ctx = {
        'name': result.name, 'cat': result.cat, 'mark': result.mark, 'task_id': task.id,
        'mark_obj': result, 'focus_obj': result,
        'custom_key': custom_key, 'name_source': name_source, 'default_back': default_back,
        'result': result, 'task': task,
    }
    return ctx, None


def filter_view(request, market, code):
    """单只股票详情（K线），统一支持 /filter/view、/stocks/view、/refer/view 三种模式。"""
    site = _resolve_view_site(request.path)
    ctx, err = _resolve_view_target(site, request, code, market)
    if err is not None:
        return err

    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        func_name = data.get('func')
        if func_name in ('major', 'minor'):
            if ctx['mark_obj'] is None:
                return JsonResponse({'status': 'error', 'message': '股票不存在'}, status=404)
            return _toggle_mark_obj(ctx['mark_obj'], func_name)
        if func_name == 'hide':
            return _handle_hide_view(
                request, site, code, market, ctx['custom_key'],
                name_source=ctx['name_source'],
                result=ctx.get('result'), task=ctx.get('task'))
        if func_name == 'focus':
            if ctx['focus_obj'] is None:
                return JsonResponse({'status': 'error', 'message': '股票不存在'}, status=404)
            return _do_focus(ctx['focus_obj'], data.get('ema_price'),
                             data.get('comments', '筛选时添加'))
        return JsonResponse({'status': 'error', 'message': '未知操作'})

    # GET
    utils.set_view_current_code(request.session, code)
    navi_data = utils.get_cache(request.session, f'{site}-navi-data', {})
    if (site, code, market) != navi_data.get('site_code_market', None):
        navi_data = chart.set_navi_data(request.session, site, code, market, None, 'init')
    if not navi_data:
        return redirect(utils.get_view_back(request.session) or ctx['default_back'])

    utils.set_cache(request.session, 'view', 'kline')
    back_url = utils.get_view_back(request.session) or ctx['default_back']
    extra = {'taskId': ctx['task_id']} if ctx['task_id'] else {}
    chart_init = utils.build_chart_init(site, code, market, ctx['name'], ctx['cat'],
                                        back_url=back_url, **extra)
    return render(request, 'filter-view.html', {
        'chart': json.dumps(chart_init),
        'mark': ctx['mark'],
        'task_id': ctx['task_id'],
    })


def refer_list(request):
    """两次筛选结果对比，后端分页。所有状态（task_a/task_b/scope/page/per_page）均存 session，URL 恒为 /refer/list。"""
    if request.method == 'POST':
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        if 'task_a' in data:
            utils.set_cache(request.session, 'filter-refer-task-a', data['task_a'])
        if 'task_b' in data:
            utils.set_cache(request.session, 'filter-refer-task-b', data['task_b'])
        if 'scope' in data:
            scope_val = data['scope'] if data['scope'] in ('all', 'both', 'only_a', 'only_b') else 'all'
            utils.set_cache(request.session, 'filter-refer-scope', scope_val)
        if 'page' in data:
            utils.set_cache(request.session, 'filter-refer-page', int(data['page']))
        if 'per_page' in data:
            utils.set_page_size(request.session, data['per_page'])
        if 'from_view' in data:
            utils.set_cache(request.session, 'filter-refer-from-view', data['from_view'])
            utils.set_view_back(request.session, '/refer/list')
        # 所有对比页内部 POST 操作后刷新，均保留任务选择（避免重新弹窗）
        utils.set_cache(request.session, 'filter-refer-from-view', '1')
        return JsonResponse({'status': 'success'})

    tasks = [
        {'id': t.id, 'name': t.name, 'stock_count': t.results.exclude(hide='1').count(), 'parent_id': t.parent_id}
        for t in FilterTask.objects.all()[:50]
    ]

    # 判断是否从 view 返回：使用独立标记，避免 view-back-url 残留误判
    from_view = bool(utils.get_cache(request.session, 'filter-refer-from-view'))
    utils.delete_cache(request.session, 'filter-refer-from-view')  # 消费掉，只生效一次

    if from_view:
        # 从 view 返回：尝试保留 session 中的选择
        a_id = utils.get_cache(request.session, 'filter-refer-task-a')
        b_id = utils.get_cache(request.session, 'filter-refer-task-b')
    else:
        a_id = b_id = None

    # 只要没有有效选择（首次进入、取消后再进、或session无值），就统一计算默认任务A/B
    if not a_id or not b_id:
        utils.delete_cache(request.session, 'filter-refer-task-a')
        utils.delete_cache(request.session, 'filter-refer-task-b')
        utils.delete_cache(request.session, 'filter-refer-scope')
        a_id = b_id = None
        # 任务A：当前默认任务（设定页面设置的 default_task_id），未设置则兜底最近任务
        gcfg = FilterConfig.objects.first()
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

    scope = utils.get_cache(request.session, 'filter-refer-scope', 'all')
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

    pg = utils.paginate_queryset(
        request, _RowIter(rows), 'filter-refer-page',
        code_getter=lambda obj: obj['code']
    )

    # 全量过滤后的列表作为 view 自定义 navi（可跨页，用索引作临时 id）
    custom_navi = [(idx, r['code'], r['market']) for idx, r in enumerate(rows)]
    utils.set_cache(request.session, 'refer-view-custom-navi', custom_navi)
    utils.delete_cache(request.session, '/refer/view-navi-data')
    utils.set_view_back(request.session, '/refer/list')

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
        data, err = utils.parse_json_body(request)
        if err is not None:
            return err
        if data.get('action') == 'delete':
            t = FilterTask.objects.filter(id=data.get('task_id')).first()
            if t:
                cfg = FilterConfig.load()
                is_default = (cfg.default_task_id == t.id)
                t.delete()
                # 若删除的是默认任务，回退到最新任务；无任务则设为-1
                if is_default:
                    latest = FilterTask.objects.order_by('-id').first()
                    cfg.default_task_id = latest.id if latest else -1
                    cfg.save(update_fields=['default_task_id'])
                return JsonResponse({'status': 'success'})
            return JsonResponse({'status': 'error', 'message': '任务不存在'}, status=404)
        if data.get('action') == 'save_boards':
            keys = data.get('boards', [])
            cfg = FilterConfig.load()
            cfg.set_enabled(keys)
            if 'exclude_st' in data:
                cfg.set_exclude_st(bool(data.get('exclude_st')))
            return JsonResponse({'status': 'success',
                                 'enabled': sorted(cfg.get_enabled()),
                                 'exclude_st': cfg.is_exclude_st()})
        if data.get('action') == 'save_exclude_st':
            cfg = FilterConfig.load()
            cfg.set_exclude_st(bool(data.get('exclude_st')))
            return JsonResponse({'status': 'success',
                                 'exclude_st': cfg.is_exclude_st()})
        if data.get('action') == 'set_default':
            tid = data.get('task_id')
            if FilterTask.objects.filter(id=tid).exists():
                cfg = FilterConfig.load()
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
    cfg = FilterConfig.load()
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

    # 有任务时，若default_task_id=-1或任务不存在，自动修正为最新任务
    actual_default_id = cfg.default_task_id
    if tasks and (actual_default_id == -1 or not FilterTask.objects.filter(id=actual_default_id).exists()):
        latest = FilterTask.objects.order_by('-id').first()
        if latest:
            actual_default_id = latest.id
            cfg.default_task_id = actual_default_id
            cfg.save(update_fields=['default_task_id'])

    return render(request, 'filter-config.html', {
        'tasks': tasks, 'boards': boards,
        'exclude_st': cfg.is_exclude_st(),
        'default_task_id': actual_default_id,
        'filter_config': cfg,
    })


def filter_config_save(request):
    """保存筛选通用设置"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '仅支持POST'}, status=405)
    data, err = utils.parse_json_body(request)
    if err is not None:
        return err

    cfg = FilterConfig.load()
    if 'filter_timeout' in data:
        cfg.filter_timeout = int(data['filter_timeout'])
    if 'target_profit_ratio' in data:
        cfg.target_profit_ratio = Decimal(str(data['target_profit_ratio']))
    if 'stop_loss_ratio' in data:
        cfg.stop_loss_ratio = Decimal(str(data['stop_loss_ratio']))
    cfg.save()
    return JsonResponse({'status': 'success'})
