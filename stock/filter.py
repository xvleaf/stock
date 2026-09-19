import os
import json
import datetime
from decimal import Decimal
import pandas as pd
from django.http import JsonResponse, HttpResponseRedirect, Http404
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from .fetch import quote, tushare
from . import func, chart, cash
from .models.models import (StockList, FilterTask, FilterResult, FocusStock,
                            FilterGlobalConfig, BOARD_DEFS, BOARD_LABELS, board_of_code)
from django.core.cache import cache

# 筛选进行中的全局锁（防止并发重复筛选）
FILTER_RUNNING_KEY = 'filter-running'
FILTER_RUNNING_TIMEOUT = 1800   # 30 分钟兜底，防止异常崩溃后死锁


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
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        if cond.get('type') == 'compare':
            if not _eval_compare(df_map, cond):
                return False
        elif cond.get('type') == 'trend':
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
    """筛选结果清单。URL 恒为 /filter/list，task/page/per_page 存 session。"""
    from django.core.paginator import Paginator

    # 从未筛选过：自动建一条默认 task（收盘价>0，全量非隐藏股）
    if FilterTask.objects.count() == 0:
        _build_default_task()

    # POST：切换 task / 每页条数 / 翻页（存 session，保持 URL 干净）
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': '无效JSON'}, status=400)
        if 'task_id' in data:
            func.set_cache(request.session, 'filter-list-task', data['task_id'])
        if 'page' in data:
            func.set_cache(request.session, 'filter-list-page', int(data['page']))
        if 'per_page' in data:
            func.set_cache(request.session, 'filter-list-per-page', str(data['per_page']))
        return JsonResponse({'status': 'success'})

    # GET：从 session 读状态，默认最新 task / 第1页 / 每页20
    sid = func.get_cache(request.session, 'filter-list-task')
    task = FilterTask.objects.filter(id=sid).first() if sid else None
    if task is None:
        task = FilterTask.objects.first()
    # 记录当前展示的 task，供点进 view 页时定位（URL 不带 task_id）
    if task:
        func.set_cache(request.session, 'filter-list-task', task.id)
        func.set_cache(request.session, 'filter-current-task', task.id)
    page_raw = str(func.get_cache(request.session, 'filter-list-page', 1))
    per_page_raw = str(func.get_cache(request.session, 'filter-list-per-page', '20'))

    results_qs = task.results.exclude(hide='1') if task else FilterResult.objects.none()

    if per_page_raw == 'all':
        items_qs = results_qs
        total_pages = 1
        current_page = 1
        per_page = 20
    else:
        try:
            per_page = int(per_page_raw)
        except (TypeError, ValueError):
            per_page = 20
        paginator = Paginator(results_qs, per_page)
        try:
            current_page = int(page_raw)
        except (TypeError, ValueError):
            current_page = 1
        page = paginator.get_page(current_page)
        items_qs = page.object_list
        total_pages = paginator.num_pages

    items = []
    base_no = 0 if per_page_raw == 'all' else (current_page - 1) * per_page
    # 本页结果中正在关注的 (code, market)
    codes = [(r.code, r.market) for r in items_qs]
    focused_set = set()
    if codes:
        watched = FocusStock.objects.filter(
            status=FocusStock.STATUS_WATCHING,
            code__in=[c for c, _ in codes],
        ).values_list('code', 'market')
        focused_set = set(watched)
    for idx, r in enumerate(items_qs):
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
        'per_page': per_page_raw,
        'current_page': current_page,
        'total_pages': total_pages,
        'result_total': results_qs.count(),
    })


def filter_run(request):
    """条件配置页 / 执行筛选。?parent_id=xx 在某结果上二次筛选。"""
    parent = None
    parent_id = request.GET.get('parent_id') or request.POST.get('parent_id')
    if parent_id:
        parent = FilterTask.objects.filter(id=parent_id).first()

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

        try:
            sample = _stock_sample(parent)
            cache_disk = {}
            passed = []
            for code, market, sname, cat in sample:
                df_map = _load_kline_map(cache_disk, code, market, cat, conditions)
                if df_map is None:
                    continue
                if _match_all(conditions, df_map):
                    passed.append((code, market, sname, cat))

            # 写库
            task = FilterTask.objects.create(
                name=name or f'筛选#{FilterTask.objects.count()+1}',
                parent=parent,
                source=FilterTask.SOURCE_TASK if parent else FilterTask.SOURCE_STOCK,
                conditions=json.dumps(conditions, ensure_ascii=False),
                stock_count=len(passed),
            )
            for idx, (code, market, sname, cat) in enumerate(passed, 1):
                FilterResult.objects.get_or_create(
                    task=task, code=code, market=market,
                    defaults={'name': sname, 'cat': cat, 'sort_order': idx}
                )
        finally:
            cache.delete(FILTER_RUNNING_KEY)

        # 记住本次结果任务，回到干净的 /filter/list
        func.set_cache(request.session, 'filter-list-task', task.id)
        func.set_cache(request.session, 'filter-list-page', 1)
        return JsonResponse({
            'status': 'success',
            'task_id': task.id,
            'count': task.stock_count,
            'redirect': '/filter/list',
        })

    # GET
    sample_total = len(_stock_sample(parent))
    return render(request, 'filter-run.html', {
        'parent': parent,
        'parent_id': parent.id if parent else None,
        'sample_total': sample_total,
    })


def _do_focus(result, ema_price=None):
    """
    关注/取消关注（双向）。
    - 未关注：建关注记录，plan_price=前端传来的当前 EMA 值；
      target=1.1倍，stop=0.95倍，数量按可用资金，备注「筛选时添加」，排在关注列表最后。
    - 已关注：关闭该记录，备注「筛选时关闭」。
    """
    existing = FocusStock.objects.filter(
        code=result.code, market=result.market,
        status=FocusStock.STATUS_WATCHING).first()

    import decimal
    if existing:
        # 取消关注
        existing.status = FocusStock.STATUS_CLOSED
        existing.close_reason = FocusStock.CLOSE_REASON_MANUAL
        existing.close_date = timezone.now().date()
        existing.comments = '筛选时关闭'
        existing.save()
        return JsonResponse({'status': 'success', 'focus': 0, 'msg': '已取消关注'})

    if ema_price is None:
        return JsonResponse({'status': 'error', 'message': 'EMA价格缺失'}, status=400)
    # 兼容前端误传 Highstock [时间戳, 值] 数组
    if isinstance(ema_price, (list, tuple)):
        ema_price = ema_price[1] if len(ema_price) >= 2 else None
    if ema_price is None or float(ema_price) <= 0:
        return JsonResponse({'status': 'error', 'message': 'EMA价格缺失'}, status=400)

    plan = float(ema_price)
    target = round(plan * 1.1, 3)
    stop = round(plan * 0.95, 3)
    qty = cash.calc_allowed_qty(plan) if plan > 0 else 0

    # 排在关注列表最后
    from django.db.models import Max as _Max
    max_order = FocusStock.objects.aggregate(m=_Max('sort_order'))['m'] or 0

    FocusStock.objects.create(
        code=result.code, name=result.name, market=result.market, cat=result.cat,
        plan_price=decimal.Decimal(str(round(plan, 3))),
        plan_qty=qty,
        target_price=decimal.Decimal(str(target)),
        stop_price=decimal.Decimal(str(stop)),
        allowed_qty=qty,
        comments='筛选时添加',
        sort_order=max_order + 1,
    )
    return JsonResponse({'status': 'success', 'focus': 1,
                         'plan': round(plan, 3), 'target': target, 'stop': stop, 'qty': qty})


def filter_view(request, market, code):
    """单只结果股详情（K线），支持打标记1/2。URL 不带 task_id，从 session 定位任务。"""
    # 候选 task_id 依次尝试：URL参数 -> current -> list；任一不存在则跳过，避免 session 残留旧 task 导致 404
    candidates = [
        request.GET.get('task_id'),
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
        if func_name == 'major':
            result.mark = '' if result.mark == FilterResult.MARK_PREF else FilterResult.MARK_PREF
            result.save()
            return JsonResponse({
                'status': 'success',
                'major': result.mark if result.mark == FilterResult.MARK_PREF else '',
                'minor': result.mark if result.mark == FilterResult.MARK_POT else '',
            })
        elif func_name == 'minor':
            result.mark = '' if result.mark == FilterResult.MARK_POT else FilterResult.MARK_POT
            result.save()
            return JsonResponse({
                'status': 'success',
                'major': result.mark if result.mark == FilterResult.MARK_PREF else '',
                'minor': result.mark if result.mark == FilterResult.MARK_POT else '',
            })
        elif func_name == 'hide':
            # 隐藏该股票：同步 StockList，以及所有历史结果中的同代码记录
            StockList.objects.filter(code=code, market=market).update(hide='1')
            FilterResult.objects.filter(code=code, market=market).update(hide='1')
            # 失效导航缓存，并计算下一只（已排除 hide）
            func.delete_cache(request.session, '/filter/view-navi-data')
            qs = FilterResult.objects.filter(task=task).exclude(hide='1').order_by('sort_order', 'id')
            nxt = qs.filter(sort_order__gt=result.sort_order).first()
            if nxt is None:
                nxt = qs.first()
            resp = {'status': 'success', 'hide': '1'}
            if nxt:
                resp['next'] = {'code': nxt.code, 'market': nxt.market}
            return JsonResponse(resp)
        elif func_name == 'focus':
            return _do_focus(result, data.get('ema_price'))
        else:
            return JsonResponse({'status': 'error', 'message': '未知操作'})

    # GET
    func.set_cache(request.session, 'filter-current-task', task.id)
    navi_data = func.get_cache(request.session, '/filter/view-navi-data', {})
    if ('/filter/view', code, market) != navi_data.get('site_code_market', None):
        navi_data = chart.set_navi_data(request.session, '/filter/view', code, market, None, 'init')

    func.set_cache(request.session, 'view', 'kline')
    chart_init = {
        'site': '/filter/view',
        'code': code,
        'market': market,
        'name': result.name,
        'cat': result.cat,
        'view': 'kline',
        'taskId': task.id,
    }
    return render(request, 'filter-view.html', {
        'chart': json.dumps(chart_init),
        'mark': result.mark,
        'task_id': task.id,
    })


def filter_refer(request):
    """两次筛选结果对比，差异股票高亮。"""
    tasks = FilterTask.objects.all()[:50]

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': '无效JSON'}, status=400)
        a_id, b_id = data.get('task_a'), data.get('task_b')
        ta = FilterTask.objects.filter(id=a_id).first()
        tb = FilterTask.objects.filter(id=b_id).first()
        if not ta or not tb:
            return JsonResponse({'error': '请选择两个筛选任务'}, status=400)

        map_a = {(r.code, r.market): r for r in ta.results.all()}
        map_b = {(r.code, r.market): r for r in tb.results.all()}
        keys = set(map_a) | set(map_b)
        rows = []
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
            rows.append({
                'code': key[0], 'market': key[1], 'name': r.name,
                'region': region,
            })
        return JsonResponse({
            'rows': rows,
            'label_a': f'#{ta.id} {ta.name}',
            'label_b': f'#{tb.id} {tb.name}',
            'count_a': len(map_a),
            'count_b': len(map_b),
            'count_both': len(set(map_a) & set(map_b)),
        }, safe=False, json_dumps_params={'ensure_ascii': False})

    return render(request, 'filter-refer.html', {'tasks': tasks})


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
            'count': t.stock_count,
            'created': t.created_at.strftime('%Y-%m-%d'),
            'lines': describe_conditions(t.condition_list),
        })
    return render(request, 'filter-config.html', {
        'tasks': tasks, 'boards': boards,
        'exclude_st': cfg.is_exclude_st(),
    })
