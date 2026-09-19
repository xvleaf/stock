import { chartPageContainer, initChartPage, setPageConfig } from './chart.js';
import { postRequest, getCsrfToken } from './func.js';

// ===================== filter-list 结果清单 =====================
export function initFilterList() {
    const tbody = document.getElementById('stockBody');
    const taskSelect = document.getElementById('taskSelect');
    const markFilter = document.getElementById('markFilter');

    // 存 session 后回到干净的 /filter/list
    function savePref(patch) {
        postRequest('/filter/list', patch).then(() => {
            window.location.href = '/filter/list';
        });
    }

    // 任务切换
    taskSelect?.addEventListener('change', (e) => {
        savePref({ task_id: parseInt(e.target.value), page: 1 });
    });

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

    // 标记筛选（纯前端显隐）
    markFilter?.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-mark]');
        if (!btn) return;
        markFilter.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const mark = btn.dataset.mark;
        tbody.querySelectorAll('tr[data-mark]').forEach(tr => {
            tr.style.display = (!mark || tr.dataset.mark === mark) ? '' : 'none';
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
    const rkindOpts = [['ema', 'EMA'], ['ma', 'MA'], ['prc', 'PRC价格']]
        .map(([v, t]) => `<option value="${v}" ${v === (opt.right_kind || 'ema') ? 'selected' : ''}>${t}</option>`).join('');
    const opOpts = OP_OPTS.map(([v, t]) => `<option value="${v}" ${v === (opt.op || '>') ? 'selected' : ''}>${t}</option>`).join('');
    const isPrc = opt.right_kind === 'prc';
    return `
        <div class="cond-head">
            <span class="fw-bold small">比较条件（左值 与 均线/价格比较）</span>
            <button type="button" class="btn btn-sm btn-outline-danger del-cond">删</button>
        </div>
        <div class="cond-row">
            <div class="field"><label>左值</label><select class="cmp-lkind form-select form-select-sm">${lkindOpts}</select></div>
            <div class="field"><label>左值倍率</label><input class="cmp-lmult form-control form-control-sm" type="number" step="0.01" value="${opt.left_mult || 1}" style="width:70px"></div>
            <div class="field"><label>关系</label><select class="cmp-op form-select form-select-sm">${opOpts}</select></div>
            <div class="field"><label>右值</label><select class="cmp-rkind form-select form-select-sm">${rkindOpts}</select></div>
            <div class="field r-ma-fields"><label>均线周期</label><input class="cmp-rperiod form-control form-control-sm" type="number" value="${opt.right_period || 30}" style="width:70px"></div>
            <div class="field r-ma-fields"><label>均线倍率</label><input class="cmp-rmult form-control form-control-sm" type="number" step="0.01" value="${opt.right_mult || 1}" style="width:70px"></div>
            <div class="field r-price-field" style="display:none;"><label>价格</label><input class="cmp-price form-control form-control-sm" type="number" step="0.01" value="${opt.right_price || 0}" style="width:80px"></div>
        </div>
        <div class="cond-row mt-2">
            <div class="field"><label>周期</label><select class="cmp-freq form-select form-select-sm">${freqOpts}</select></div>
            <div class="field"><label>考察K线数 M</label><input class="cmp-window form-control form-control-sm" type="number" value="${opt.window || 10}" style="width:80px"></div>
            <div class="field"><label>满足根数 N≥</label><input class="cmp-min form-control form-control-sm" type="number" value="${opt.min_count || 8}" style="width:80px"></div>
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
            <button type="button" class="btn btn-sm btn-outline-danger del-cond">删</button>
        </div>
        <div class="cond-row">
            <div class="field"><label>指标</label><select class="tr-kind form-select form-select-sm">${kindOpts}</select></div>
            <div class="field"><label>周期</label><select class="tr-freq form-select form-select-sm">${freqOpts}</select></div>
            <div class="field"><label>均线周期</label><input class="tr-period form-control form-control-sm" type="number" value="${opt.period || 30}" style="width:80px"></div>
            <div class="field"><label>形态</label><select class="tr-dir form-select form-select-sm">${dirOpts}</select></div>
            <div class="field"><label>观察窗口</label><input class="tr-window form-control form-control-sm" type="number" value="${opt.window || 5}" style="width:80px"></div>
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

export function initFilterRun({ parentId }) {
    const list = document.getElementById('condList');
    const errBox = document.getElementById('errorText');
    const statusBox = document.getElementById('runStatus');

    function addCompare(opt) {
        const div = document.createElement('div');
        div.className = 'cond-card';
        div.dataset.type = 'compare';
        div.innerHTML = compareCard(opt);
        list.appendChild(div);
        // 右值类型切换联动
        const rkindSel = div.querySelector('.cmp-rkind');
        rkindSel.addEventListener('change', () => updateCompareMode(div));
        updateCompareMode(div);
    }
    function addTrend(opt) {
        const div = document.createElement('div');
        div.className = 'cond-card';
        div.dataset.type = 'trend';
        div.innerHTML = trendCard(opt);
        list.appendChild(div);
    }

    // 默认给两个示例条件（举例1的上下界：收盘在 EMA30 的 0.9~1.1 倍之间），方便上手
    addCompare({
        freq: 'D', left_kind: 'close', left_mult: 1.0,
        op: '>', right_kind: 'ema', right_period: 30, right_mult: 0.9,
        window: 10, min_count: 8,
    });
    addCompare({
        freq: 'D', left_kind: 'close', left_mult: 1.0,
        op: '<', right_kind: 'ema', right_period: 30, right_mult: 1.1,
        window: 10, min_count: 8,
    });

    document.getElementById('addCompare').addEventListener('click', () => addCompare());
    document.getElementById('addTrend').addEventListener('click', () => addTrend());
    list.addEventListener('click', (e) => {
        const del = e.target.closest('.del-cond');
        if (del) del.closest('.cond-card').remove();
    });

    document.getElementById('runBtn').addEventListener('click', async () => {
        errBox.classList.add('d-none');
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

        if (!conditions.length) {
            errBox.textContent = '请至少添加一个筛选条件';
            errBox.classList.remove('d-none');
            return;
        }

        const btn = document.getElementById('runBtn');
        btn.disabled = true;
        statusBox.classList.remove('d-none');
        statusBox.textContent = '正在筛选，全市场逐股计算，请耐心等待……';

        const res = await postRequest('/filter/run', {
            name: document.getElementById('taskName').value,
            parent_id: parentId,
            conditions,
        });
        if (res && res.status === 'success') {
            window.location.href = res.redirect;
        } else {
            btn.disabled = false;
            statusBox.classList.add('d-none');
            errBox.textContent = (res && res.message) || '筛选失败';
            errBox.classList.remove('d-none');
        }
    });
}


// ===================== filter-refer 对比 =====================
export function initFilterRefer() {
    const tbody = document.getElementById('stockBody');
    document.getElementById('referBtn').addEventListener('click', async () => {
        const a = document.getElementById('taskA').value;
        const b = document.getElementById('taskB').value;
        const res = await postRequest('/filter/refer', { task_a: a, task_b: b });
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
    });
}


// ===================== filter-config 历史管理 =====================
export function initFilterConfig() {
    document.addEventListener('click', async (e) => {
        const btn = e.target.closest('.del-task');
        if (btn) {
            if (!confirm('确认删除该筛选任务及其结果？')) return;
            const res = await postRequest('/filter/config', { action: 'delete', task_id: btn.dataset.id });
            if (res && res.status === 'success') window.location.reload();
            return;
        }
        const saveBtn = e.target.closest('#saveBoards');
        if (saveBtn) {
            const boards = Array.from(document.querySelectorAll('.board-check:checked')).map(el => el.value);
            if (boards.length === 0) { alert('至少勾选一个板块'); return; }
            const exclEl = document.getElementById('excludeStCheck');
            const exclude_st = exclEl ? exclEl.checked : false;
            const res = await postRequest('/filter/config', {
                action: 'save_boards', boards, exclude_st,
            });
            if (res && res.status === 'success') { alert('已保存，对下一次筛选生效'); }
        }
    });
}
