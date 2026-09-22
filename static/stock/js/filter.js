import { chartPageContainer, initChartPage, setPageConfig } from './chart.js';
import { postRequest, getCsrfToken, showRadioModal, showConfirm } from './func.js';

// ===================== filter-list 结果清单 =====================
export function initFilterList(opts = {}) {
    const tbody = document.getElementById('stockBody');

    // 存 session 后回到干净的 /filter/list
    function savePref(patch) {
        postRequest('/filter/list', patch).then(() => {
            window.location.href = '/filter/list';
        });
    }

    // 每页条数切换
    const perPageSelect = document.getElementById('perPageSelect');
    perPageSelect?.addEventListener('change', (e) => {
        savePref({ per_page: e.target.value, page: 1 });
    });

    // 翻页
    document.getElementById('prevPage')?.addEventListener('click', (e) => {
        savePref({ page: parseInt(e.currentTarget.dataset.page) });
    });
    document.getElementById('nextPage')?.addEventListener('click', (e) => {
        savePref({ page: parseInt(e.currentTarget.dataset.page) });
    });

    // 表头"标记"按钮：弹窗选择后 POST 提交，后端过滤+重新分页（与对比清单一致）
    let currentMarkFilter = opts.currentMarkFilter || 'all';
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.mark-filter-btn');
        if (!btn) return;
        showRadioModal({
            title: '标记筛选',
            options: [['all', '全部'], ['1', '优先'], ['2', '潜力']],
            defaultValue: currentMarkFilter,
        }).then((value) => {
            if (value !== null) {
                currentMarkFilter = value;
                savePref({ mark_filter: value });
            }
        });
    });
}


// ===================== filter-view 单股详情 =====================
export function initFilterView(config) {
    const initChart = config.initChart || {};
    setPageConfig(initChart);
    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }
}


// ===================== filter-run 条件配置 =====================
const FREQ_OPTS = ['D', 'W', 'M'];
const OP_OPTS = [['>', '大于'], ['<', '小于']];
const DIR_OPTS = [
    ['up', '上升趋势'], ['down', '下降趋势'],
    ['accel_up', '加速上升'], ['accel_down', '加速下降'],
];

function FREQ_LABEL(f) { return ({ D: '日线', W: '周线', M: '月线' })[f] || f; }

function compareCard(opt) {
    opt = opt || {};
    const freqOpts = FREQ_OPTS.map(f => `<option value="${f}" ${f === (opt.freq || 'D') ? 'selected' : ''}>${FREQ_LABEL(f)}</option>`).join('');
    const lkindOpts = [['close', '收盘价'], ['volume', '成交量']]
        .map(([v, t]) => `<option value="${v}" ${v === (opt.left_kind || 'close') ? 'selected' : ''}>${t}</option>`).join('');
    const rkindOpts = [['ema', 'EMA'], ['ma', 'MA'], ['prc', '价格']]
        .map(([v, t]) => `<option value="${v}" ${v === (opt.right_kind || 'ema') ? 'selected' : ''}>${t}</option>`).join('');
    const opOpts = OP_OPTS.map(([v, t]) => `<option value="${v}" ${v === (opt.op || '>') ? 'selected' : ''}>${t}</option>`).join('');
    const isPrc = opt.right_kind === 'prc';
    return `
        <div class="cond-head">
            <span class="fw-bold small">比较条件</span>
            <button type="button" class="btn btn-sm btn-outline-danger del-cond">删除</button>
        </div>
        <div class="cond-row">
            <div class="field"><label>指标</label><select class="cmp-lkind form-select form-select-sm">${lkindOpts}</select></div>
            <div class="field"><label>倍率</label><input class="cmp-lmult form-control form-control-sm" type="number" step="0.01" value="${opt.left_mult || 1}"></div>
            <div class="field"><label>比较</label><select class="cmp-op form-select form-select-sm">${opOpts}</select></div>
            <div class="cond-break"></div>
            <div class="field"><label>指标</label><select class="cmp-rkind form-select form-select-sm">${rkindOpts}</select></div>
            <div class="field r-ma-fields"><label>周期</label><input class="cmp-rperiod form-control form-control-sm" type="number" value="${opt.right_period || 30}"></div>
            <div class="field r-ma-fields"><label>倍率</label><input class="cmp-rmult form-control form-control-sm" type="number" step="0.01" value="${opt.right_mult || 1}"></div>
            <div class="field r-price-field" style="display:none;"><label>价格</label><input class="cmp-price form-control form-control-sm" type="number" step="0.01" value="${opt.right_price || 0}"></div>
        </div>
        <div class="cond-row mt-2">
            <div class="field"><label>K线周期</label><select class="cmp-freq form-select form-select-sm">${freqOpts}</select></div>
            <div class="field"><label>观察窗口</label><input class="cmp-window form-control form-control-sm" type="number" value="${opt.window || 10}"></div>
            <div class="field"><label>满足条件</label><input class="cmp-min form-control form-control-sm" type="number" value="${opt.min_count || 8}"></div>
        </div>
    `;
}

// 右值类型切换：PRC 时隐藏均线周期/倍率、显示价格、左值锁定收盘价、M/N=1 只读
function updateCompareMode(card) {
    const rkind = card.querySelector('.cmp-rkind').value;
    const isPrc = rkind === 'prc';
    card.querySelectorAll('.r-ma-fields').forEach(el => el.style.display = isPrc ? 'none' : '');
    const pf = card.querySelector('.r-price-field');
    if (pf) pf.style.display = isPrc ? '' : 'none';
    const lkind = card.querySelector('.cmp-lkind');
    lkind.disabled = isPrc;
    if (isPrc) lkind.value = 'close';
    const w = card.querySelector('.cmp-window');
    const n = card.querySelector('.cmp-min');
    w.disabled = isPrc; n.disabled = isPrc;
    if (isPrc) { w.value = 1; n.value = 1; }
}

function trendCard(opt) {
    opt = opt || {};
    const kindOpts = [['ema', 'EMA'], ['ma', 'MA']].map(([v, t]) => `<option value="${v}" ${v === (opt.kind || 'ema') ? 'selected' : ''}>${t}</option>`).join('');
    const freqOpts = FREQ_OPTS.map(f => `<option value="${f}" ${f === (opt.freq || 'D') ? 'selected' : ''}>${FREQ_LABEL(f)}</option>`).join('');
    const dirOpts = DIR_OPTS.map(([v, t]) => `<option value="${v}" ${v === (opt.direction || 'up') ? 'selected' : ''}>${t}</option>`).join('');
    return `
        <div class="cond-head">
            <span class="fw-bold small">趋势条件</span>
            <button type="button" class="btn btn-sm btn-outline-danger del-cond">删除</button>
        </div>
        <div class="cond-row">
            <div class="field"><label>指标</label><select class="tr-kind form-select form-select-sm">${kindOpts}</select></div>
            <div class="field"><label>周期</label><input class="tr-period form-control form-control-sm" type="number" value="${opt.period || 30}"></div>
            <div class="field"><label>形态</label><select class="tr-dir form-select form-select-sm">${dirOpts}</select></div>
            <div class="field"><label>K线周期</label><select class="tr-freq form-select form-select-sm">${freqOpts}</select></div>
            <div class="field"><label>观察窗口</label><input class="tr-window form-control form-control-sm" type="number" value="${opt.window || 5}"></div>
        </div>
    `;
}

function readCompare(card) {
    const rkind = card.querySelector('.cmp-rkind').value;
    const cond = {
        type: 'compare',
        freq: card.querySelector('.cmp-freq').value,
        left_kind: card.querySelector('.cmp-lkind').value,
        left_mult: parseFloat(card.querySelector('.cmp-lmult').value) || 1.0,
        right_kind: rkind,
        op: card.querySelector('.cmp-op').value,
        window: parseInt(card.querySelector('.cmp-window').value) || 1,
        min_count: parseInt(card.querySelector('.cmp-min').value) || 1,
    };
    if (rkind === 'prc') {
        cond.right_price = parseFloat(card.querySelector('.cmp-price').value) || 0;
    } else {
        cond.right_period = parseInt(card.querySelector('.cmp-rperiod').value) || 30;
        cond.right_mult = parseFloat(card.querySelector('.cmp-rmult').value) || 1.0;
    }
    return cond;
}

// 根据条件自动生成任务名摘要
function autoTaskName(conditions) {
    if (!conditions || !conditions.length) return '';
    const FREQ_SHORT = { D: '日', W: '周', M: '月' };
    const LKIND = { close: '收盘', volume: '成交量' };
    const RKIND = { ema: 'EMA', ma: 'MA', prc: '价' };
    const DIR = { up: '上升趋势', down: '下降趋势', accel_up: '加速上升', accel_down: '加速下降' };
    const parts = conditions.map(c => {
        const freq = FREQ_SHORT[c.freq] || c.freq;
        if (c.type === 'compare') {
            const left = `${LKIND[c.left_kind] || c.left_kind}${c.left_mult && c.left_mult !== 1 ? '×' + c.left_mult : ''}`;
            let right;
            if (c.right_kind === 'prc') {
                right = `${c.right_price}`;
            } else {
                right = `${RKIND[c.right_kind]}${c.right_period}${c.right_mult && c.right_mult !== 1 ? '×' + c.right_mult : ''}`;
            }
            const win = (c.window && c.window > 1) || (c.min_count && c.min_count > 1)
                ? `[${c.min_count || 1}/${c.window || 1}]` : '';
            return `${freq}${left}${c.op}${right}${win}`;
        } else {
            const win = c.window && c.window > 1 ? `[${c.window}]` : '';
            return `${freq}${RKIND[c.kind] || c.kind}${c.period}${DIR[c.direction] || c.direction}${win}`;
        }
    });
    return parts.join(' 且 ').slice(0, 80);
}

export function initFilterRun({ parentId, lastConditions, runningState }) {
    const list = document.getElementById('condList');
    const errBox = document.getElementById('errorText');
    const statusBox = document.getElementById('runStatus');
    const runBtn = document.getElementById('runBtn');
    const runningPanel = document.getElementById('runningPanel');
    const runningLabel = document.getElementById('runningLabel');
    const runningPct = document.getElementById('runningPct');
    const runningBar = document.getElementById('runningBar');
    const runningDetail = document.getElementById('runningDetail');
    const taskNameInput = document.getElementById('taskName');

    let pollTimer = null;
    let userEditedName = false;
    let nameTimer = null;

    function addCompare(opt) {
        const div = document.createElement('div');
        div.className = 'cond-card';
        div.dataset.type = 'compare';
        div.innerHTML = compareCard(opt);
        list.appendChild(div);
        const rkindSel = div.querySelector('.cmp-rkind');
        rkindSel.addEventListener('change', () => { updateCompareMode(div); scheduleAutoName(); });
        updateCompareMode(div);
    }
    function addTrend(opt) {
        const div = document.createElement('div');
        div.className = 'cond-card';
        div.dataset.type = 'trend';
        div.innerHTML = trendCard(opt);
        list.appendChild(div);
    }

    // 回填上次条件（无历史则留空，不添加示例）
    if (lastConditions && lastConditions.length) {
        lastConditions.forEach(c => {
            if (c.type === 'trend') addTrend(c);
            else addCompare(c);
        });
    }
    // 进入页面立即根据当前条件自动填入任务名
    scheduleAutoName();

    // 收集当前条件
    function collectConditions() {
        const conditions = [];
        list.querySelectorAll('.cond-card').forEach(card => {
            if (card.dataset.type === 'compare') {
                conditions.push(readCompare(card));
            } else {
                conditions.push({
                    type: 'trend',
                    kind: card.querySelector('.tr-kind').value,
                    freq: card.querySelector('.tr-freq').value,
                    period: parseInt(card.querySelector('.tr-period').value) || 30,
                    direction: card.querySelector('.tr-dir').value,
                    window: parseInt(card.querySelector('.tr-window').value) || 5,
                });
            }
        });
        return conditions;
    }

    // 自动命名（防抖）
    function scheduleAutoName() {
        if (userEditedName) return;
        clearTimeout(nameTimer);
        nameTimer = setTimeout(() => {
            taskNameInput.value = autoTaskName(collectConditions());
        }, 200);
    }
    taskNameInput.addEventListener('input', () => { userEditedName = true; });

    document.getElementById('addCompare').addEventListener('click', () => { addCompare(); scheduleAutoName(); });
    document.getElementById('addTrend').addEventListener('click', () => { addTrend(); scheduleAutoName(); });
    list.addEventListener('click', (e) => {
        const del = e.target.closest('.del-cond');
        if (del) { del.closest('.cond-card').remove(); scheduleAutoName(); }
    });
    list.addEventListener('input', () => scheduleAutoName());
    list.addEventListener('change', () => scheduleAutoName());

    // ===== 运行中状态展示 =====
    function lockConditions() {
        const addC = document.getElementById('addCompare');
        const addT = document.getElementById('addTrend');
        if (addC) addC.classList.add('d-none');
        if (addT) addT.classList.add('d-none');
        document.querySelectorAll('.del-cond').forEach(b => b.classList.add('d-none'));
        document.querySelectorAll('#condList select, #condList input').forEach(el => el.disabled = true);
    }
    function unlockConditions() {
        const addC = document.getElementById('addCompare');
        const addT = document.getElementById('addTrend');
        if (addC) addC.classList.remove('d-none');
        if (addT) addT.classList.remove('d-none');
        document.querySelectorAll('.del-cond').forEach(b => b.classList.remove('d-none'));
        document.querySelectorAll('#condList select, #condList input').forEach(el => el.disabled = false);
        // 恢复 PRC 模式下左值的只读状态
        document.querySelectorAll('#condList .cond-card').forEach(card => {
            if (typeof updateCompareMode === 'function') updateCompareMode(card);
        });
    }
    function showRunning(done, total) {
        runningPanel.classList.remove('d-none');
        const pct = total > 0 ? Math.round(done / total * 100) : 0;
        runningLabel.textContent = '筛选运行中…';
        runningPct.textContent = pct + '%';
        runningBar.style.width = pct + '%';
        runningDetail.textContent = `已处理 ${done} / ${total} 只`;
        runBtn.textContent = '强制结束';
        runBtn.classList.remove('btn-primary');
        runBtn.classList.add('btn-danger');
        runBtn.disabled = false;
        lockConditions();
    }
    function hideRunning() {
        runningPanel.classList.add('d-none');
        runBtn.textContent = '开始筛选';
        runBtn.classList.remove('btn-danger');
        runBtn.classList.add('btn-primary');
        runBtn.disabled = false;
        unlockConditions();
    }

    // 轮询进度
    function startPolling() {
        stopPolling();
        pollTimer = setInterval(async () => {
            try {
                const res = await fetch('/filter/run/status');
                const data = await res.json();
                if (data.status === 'running') {
                    showRunning(data.done, data.total);
                } else if (data.status === 'idle') {
                    // 正常完成
                    stopPolling();
                    hideRunning();
                    statusBox.classList.remove('d-none');
                    statusBox.textContent = '筛选完成，正在跳转…';
                    setTimeout(() => { window.location.href = '/filter/list'; }, 500);
                } else if (data.status === 'stopped') {
                    stopPolling();
                    hideRunning();
                    statusBox.classList.remove('d-none');
                    statusBox.textContent = '筛选已强制终止，数据已回滚。';
                } else if (data.status === 'timeout') {
                    stopPolling();
                    hideRunning();
                    statusBox.classList.remove('d-none');
                    statusBox.textContent = '筛选超时（2小时），已强制终止并回滚。';
                }
            } catch (e) { /* 忽略轮询错误 */ }
        }, 2000);
    }
    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    // 页面加载时若已有运行中的筛选，直接进入轮询
    if (runningState && runningState.total > 0) {
        showRunning(runningState.done, runningState.total);
        startPolling();
    }

    // 开始筛选 / 强制结束
    runBtn.addEventListener('click', async () => {
        // 如果正在运行，点击则强制结束
        if (runBtn.textContent === '强制结束') {
            await postRequest('/filter/run/stop', {});
            statusBox.classList.remove('d-none');
            statusBox.textContent = '正在终止…';
            return;
        }

        errBox.classList.add('d-none');
        statusBox.classList.add('d-none');
        const conditions = collectConditions();
        if (!conditions.length) {
            errBox.textContent = '请至少添加一个筛选条件';
            errBox.classList.remove('d-none');
            return;
        }

        runBtn.disabled = true;
        const res = await postRequest('/filter/run', {
            name: taskNameInput.value,
            parent_id: parentId,
            conditions,
        });
        if (res && res.status === 'running') {
            showRunning(0, 0);
            startPolling();
        } else {
            runBtn.disabled = false;
            errBox.textContent = (res && res.message) || '筛选启动失败';
            errBox.classList.remove('d-none');
        }
    });
}


// ===================== filter-refer 对比 =====================
export function initFilterRefer() {
    const tbody = document.getElementById('stockBody');
    const regionFilter = document.getElementById('regionFilter');

    // 应用归属筛选
    function applyRegionFilter() {
        const val = regionFilter ? regionFilter.value : '';
        tbody.querySelectorAll('tr[data-mark]').forEach(tr => {
            tr.style.display = (!val || tr.dataset.mark === val) ? '' : 'none';
        });
    }
    regionFilter?.addEventListener('change', applyRegionFilter);

    document.getElementById('referBtn').addEventListener('click', async () => {
        const a = document.getElementById('taskA').value;
        const b = document.getElementById('taskB').value;
        const res = await postRequest('/refer/list', { task_a: a, task_b: b });
        if (!res || res.error) return;

        document.getElementById('referSummary').innerHTML =
            `A(${res.label_a}) ${res.count_a} 只 ｜ B(${res.label_b}) ${res.count_b} 只 ｜ 共有 <b>${res.count_both}</b> 只`;

        tbody.innerHTML = '';
        res.rows.forEach((r, i) => {
            const tr = document.createElement('tr');
            const regionText = { both: '共有', only_a: '仅A', only_b: '仅B' }[r.region];
            tr.dataset.mark = r.region;
            if (r.region === 'only_a') tr.classList.add('row-only-a');
            if (r.region === 'only_b') tr.classList.add('row-only-b');
            tr.innerHTML = `
                <td>${i + 1}</td>
                <td><a class="table-code-text" href="/filter/view/${r.market}/${r.code}">${r.code}</a></td>
                <td>${r.name}</td>
                <td><span class="badge bg-${r.region === 'both' ? 'secondary' : (r.region === 'only_a' ? 'primary' : 'danger')}">${regionText}</span></td>
            `;
            tbody.appendChild(tr);
        });
        applyRegionFilter();
    });
}


// ===================== filter-config 历史管理 =====================
export function initFilterConfig() {
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('.del-task');
        if (btn) {
            showConfirm({
                title: '删除任务',
                text: '确认删除该筛选任务及其结果？',
            }).then(async (confirmed) => {
                if (!confirmed) return;
                const res = await postRequest('/filter/config', { action: 'delete', task_id: btn.dataset.id });
                if (res && res.status === 'success') window.location.reload();
            });
            return;
        }
        const defBtn = e.target.closest('.set-default-task');
        if (defBtn) {
            const res = await postRequest('/filter/config', { action: 'set_default', task_id: defBtn.dataset.id });
            if (res && res.status === 'success') window.location.reload();
            return;
        }
        const filterBtn = e.target.closest('.second-filter-task');
        if (filterBtn) {
            const res = await postRequest('/filter/list', { parent_id: filterBtn.dataset.id });
            if (res && res.status === 'success') window.location.href = '/filter/run';
            return;
        }
    });

    // 板块勾选 / 排除ST 即时保存
    function saveBoardsNow() {
        const boards = Array.from(document.querySelectorAll('.board-check:checked')).map(el => el.value);
        const exclEl = document.getElementById('excludeStCheck');
        const exclude_st = exclEl ? exclEl.checked : false;
        postRequest('/filter/config', { action: 'save_boards', boards, exclude_st });
    }
    document.querySelectorAll('.board-check, #excludeStCheck').forEach(el => {
        el.addEventListener('change', saveBoardsNow);
    });
}
