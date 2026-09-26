import { chartPageContainer, initChartPage, setPageConfig } from './chart.js';
import { refreshQuotes, postRequest, showAlert, getCsrfToken } from './func.js';

// ===================== 交易页面 =====================
export function initTransDeal(opts = {}) {
    const form = document.getElementById('transForm');
    if (!form) return;

    const currentRisk = opts.current_risk || 0;
    const allowance = opts.allowance || 0;
    const avgCost = opts.avg_cost || 0;
    const avgCostNoFee = opts.avg_cost_no_fee || 0;
    const positionQty = opts.position_qty || 0;
    const initChart = opts.initChart || {};

    setPageConfig(initChart);
    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }

    const intentSelect = document.getElementById('id_intent');
    const priceInput = document.getElementById('id_price');
    const qtyInput = document.getElementById('id_qty');
    const targetInput = document.getElementById('id_target_price');
    const stopInput = document.getElementById('id_stop_price');
    const winInput = document.getElementById('id_win_ratio');
    const amountInput = document.getElementById('id_amount');
    const feeInput = document.getElementById('id_fee');
    const profitInput = document.getElementById('id_profit');
    const riskInput = document.getElementById('id_risk');
    const allowedInput = document.getElementById('id_allowed_qty');

    // 上一次提交的参数（用于值变化判断）
    let lastParams = null;
    let calcTimer = null;

    // 收集当前参数
    function collectParams() {
        return {
            intent: intentSelect ? intentSelect.value : 'B',
            price: parseFloat(priceInput.value) || 0,
            qty: parseInt(qtyInput.value) || 0,
            target_price: parseFloat(targetInput.value) || 0,
            stop_price: parseFloat(stopInput.value) || 0,
            position_qty: positionQty,
            current_risk: currentRisk,
            avg_cost: avgCost,
            avg_cost_no_fee: avgCostNoFee,
        };
    }

    // 判断参数是否变化
    function isParamsChanged(params) {
        if (!lastParams) return true;
        return JSON.stringify(params) !== JSON.stringify(lastParams);
    }

    // 请求后台计算
    function requestCalc() {
        const params = collectParams();
        if (!isParamsChanged(params)) return;
        lastParams = { ...params };

        fetch('/trans/calc', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(params),
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) return;
            amountInput.value = data.amount.toFixed(2);
            feeInput.value = data.fee.toFixed(2);
            profitInput.value = data.profit.toFixed(2);
            riskInput.value = data.risk_amount.toFixed(2);
            allowedInput.value = data.allowed_qty;
            winInput.value = data.win_ratio;

            // 风险资金超过剩余风险额度时，风险资金输入框变红
            const remainingRisk = allowance - currentRisk;
            if (data.risk_amount > remainingRisk && remainingRisk > 0) {
                riskInput.classList.add('text-danger');
            } else {
                riskInput.classList.remove('text-danger');
            }

            // 成交数量超过允许数量时，成交数量变红
            const qty = parseInt(qtyInput.value) || 0;
            const allowedQty = parseInt(allowedInput.value) || 0;
            if (qty > allowedQty && allowedQty > 0) {
                qtyInput.classList.add('text-danger');
            } else {
                qtyInput.classList.remove('text-danger');
            }
        })
        .catch(() => {});
    }

    // 防抖触发计算
    function scheduleCalc() {
        if (calcTimer) clearTimeout(calcTimer);
        calcTimer = setTimeout(requestCalc, 300);
    }

    // 事件绑定
    if (intentSelect) intentSelect.addEventListener('change', scheduleCalc);
    priceInput.addEventListener('input', scheduleCalc);
    qtyInput.addEventListener('input', scheduleCalc);
    targetInput.addEventListener('input', scheduleCalc);
    stopInput.addEventListener('input', scheduleCalc);
    feeInput.addEventListener('input', scheduleCalc);

    // 表单提交：AJAX 方式，失败时弹窗报错，成功时跳转
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        const formData = new FormData(form);
        const submitBtn = document.getElementById('submitBtn');
        if (submitBtn) submitBtn.disabled = true;

        fetch(window.location.href, {
            method: 'POST',
            body: formData,
            headers: {'X-CSRFToken': getCsrfToken()}
        })
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success' && data.redirect) {
                window.location.href = data.redirect;
            } else if (data.status === 'error') {
                showAlert({ text: data.error || '交易失败，请重试', type: 'error' });
                if (submitBtn) submitBtn.disabled = false;
            } else {
                showAlert({ text: '交易失败，请重试', type: 'error' });
                if (submitBtn) submitBtn.disabled = false;
            }
        })
        .catch(() => {
            showAlert({ text: '网络错误，请重试', type: 'error' });
            if (submitBtn) submitBtn.disabled = false;
        });
    });

    // 初始化计算
    requestCalc();
}

// ===================== 交易清单 =====================
export function initTransList(interval = 20000) {
    const tbody = document.getElementById('stockBody');
    if (!tbody) return;

    refreshQuotes('/trans/list', tbody);
    setInterval(() => refreshQuotes('/trans/list', tbody), interval);
}

// ===================== 交易详情（只读） =====================
export function initTransView(opts = {}) {
    const isSummary = opts.is_summary !== false;
    let pilotIdx = opts.pilot_idx !== undefined ? opts.pilot_idx : -1;
    const pilotTotal = opts.pilot_total || 0;
    const pilotDate = opts.pilot_date || '';
    const pilotAction = opts.pilot_action || '';
    const pilotQty = opts.pilot_qty || '';
    const pilotPrice = opts.pilot_price || '';
    const initChart = opts.initChart || {};

    setPageConfig(initChart);
    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }

    // 汇总模式且只有一条历史记录时，显示建仓记录指示器
    if (isSummary && pilotTotal === 1) {
        const pilotIndicator = document.getElementById('transPilotIndicator');
        if (pilotIndicator) {
            const qtyPriceStr = (pilotQty && pilotPrice !== '') ? `${pilotQty}股@${pilotPrice}元` : '';
            const dateStr = pilotDate ? ` [${pilotDate}` : '';
            const actionDisplay = pilotAction === '编辑' ? '调整目标/止损' : pilotAction;
            const actionStr = pilotAction ? ` ${actionDisplay}${qtyPriceStr}]` : (pilotDate ? ']' : '');
            pilotIndicator.textContent = `第 1 / 1 笔${dateStr}${actionStr}`;
        }
    }

    // 历史模式下文字变灰
    if (!isSummary) {
        document.querySelectorAll('#transViewForm .readonly-field').forEach(el => {
            el.style.color = '#6c757d';
        });
    }

    // up/down 切换历史记录（备用，实际通过 chart.js 的 naviSwitch 实现）
    function switchPilot(delta) {
        let newIdx = pilotIdx + delta;
        // 从汇总（-1）点 up → 最近一笔（N-1）
        if (pilotIdx === -1 && delta === -1) {
            newIdx = pilotTotal - 1;
        }
        // 从最近一笔（N-1）点 down → 汇总（-1）
        if (pilotIdx === pilotTotal - 1 && delta === 1) {
            newIdx = -1;
        }
        if (newIdx < -1 || newIdx >= pilotTotal) return;
        pilotIdx = newIdx;
        postRequest('/trans/view/' + initChart.market + '/' + initChart.code, { pilot: pilotIdx })
            .then(() => {
                window.location.reload();
            })
            .catch(() => {
                window.location.reload();
            });
    }

    // 暴露给图表的 up/down 按钮
    window.switchTransPilot = switchPilot;
}

// ===================== 交易编辑 =====================
export function initTransEdit(opts = {}) {
    const form = document.getElementById('transForm');
    if (!form) return;

    const avgCost = opts.avg_cost || 0;
    const avgCostNoFee = opts.avg_cost_no_fee || 0;
    const positionQty = opts.position_qty || 0;
    const positionCost = opts.position_cost || 0;
    const currentRisk = opts.current_risk || 0;
    const allowance = opts.allowance || 0;
    const oldRisk = opts.old_risk || 0;
    const intent = opts.intent || 'B';
    const initChart = opts.initChart || {};

    setPageConfig(initChart);
    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }

    const targetInput = document.getElementById('id_target_price');
    const stopInput = document.getElementById('id_stop_price');
    const profitInput = document.getElementById('id_profit');
    const riskInput = document.getElementById('id_risk');
    const winInput = document.getElementById('id_win_ratio');

    // 上一次提交的参数
    let lastParams = null;
    let calcTimer = null;

    function collectParams() {
        return {
            intent: intent,
            price: avgCostNoFee,
            qty: 0,
            target_price: parseFloat(targetInput.value) || 0,
            stop_price: parseFloat(stopInput.value) || 0,
            position_qty: positionQty,
            current_risk: currentRisk,
            avg_cost: avgCost,
            avg_cost_no_fee: avgCostNoFee,
        };
    }

    function isParamsChanged(params) {
        if (!lastParams) return true;
        return JSON.stringify(params) !== JSON.stringify(lastParams);
    }

    function requestCalc() {
        const params = collectParams();
        if (!isParamsChanged(params)) return;
        lastParams = { ...params };

        fetch('/trans/calc', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(params),
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) return;
            profitInput.value = data.profit.toFixed(2);
            riskInput.value = data.risk_amount.toFixed(2);
            winInput.value = data.win_ratio;

            // 风险资金变动部分超过剩余风险额度时，风险资金输入框变红
            const riskChange = data.risk_amount - oldRisk;
            const remainingRisk = allowance - currentRisk;
            if (riskChange > remainingRisk && riskChange > 0) {
                riskInput.classList.add('text-danger');
            } else {
                riskInput.classList.remove('text-danger');
            }
        })
        .catch(() => {});
    }

    function scheduleCalc() {
        if (calcTimer) clearTimeout(calcTimer);
        calcTimer = setTimeout(requestCalc, 300);
    }

    targetInput.addEventListener('input', scheduleCalc);
    stopInput.addEventListener('input', scheduleCalc);

    // 初始化计算
    requestCalc();
}
