import { chartPageContainer, initChartPage, setPageConfig } from './chart.js';
import { calcAllowedQty, calcWinRatio, refreshQuotes, postRequest, showAlert, getCsrfToken } from './func.js';

// ===================== 交易页面 =====================
export function initTransDeal(opts = {}) {
    const form = document.getElementById('transForm');
    if (!form) return;

    const cash = opts.cash || 0;
    const available = opts.available || 0;
    const currentRisk = opts.current_risk || 0;
    const avgCost = opts.avg_cost || 0;
    const positionQty = opts.position_qty || 0;
    const commissionRatio = opts.commission_ratio || 0;
    const commissionMin = opts.commission_min || 0;
    const stampSellRatio = opts.stamp_sell_ratio || 0;
    const initChart = opts.initChart || {};

    setPageConfig(initChart);
    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }

    const intentSelect = document.getElementById('id_intent_choice');
    const intentHidden = document.getElementById('id_intent');
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

    // 计算交易费用
    function calcFee(amount, intent) {
        const amt = Math.max(0, amount);
        let commission = amt * commissionRatio;
        if (commission < commissionMin) commission = commissionMin;
        let stamp = 0;
        if (intent === 'S') {
            stamp = amt * stampSellRatio;
        }
        return (commission + stamp).toFixed(2);
    }

    // 计算允许数量（买入）— 使用通用函数
    // calcAllowedQty(price, stopPrice, cash, available) 已从 func.js 导入

    // 计算风险资金（买入）
    function calcRisk(price, stopPrice, qty) {
        const p = parseFloat(price) || 0;
        const s = parseFloat(stopPrice) || 0;
        const q = parseInt(qty) || 0;
        if (p <= s || q <= 0) return 0;
        return ((p - s) * q).toFixed(2);
    }

    // 计算预计收益
    function calcProfit(intent, price, qty, targetPrice, fee) {
        const p = parseFloat(price) || 0;
        const q = parseInt(qty) || 0;
        const t = parseFloat(targetPrice) || 0;
        const f = parseFloat(fee) || 0;
        if (q <= 0 || p <= 0) return '0.00';

        if (intent === 'B') {
            // 买入：按目标价计算预计收益
            if (t <= 0) return '0.00';
            const sellAmount = t * q;
            const sellFee = parseFloat(calcFee(sellAmount, 'S'));
            return ((t - p) * q - f - sellFee).toFixed(2);
        } else {
            // 卖出：按成交价计算实现收益
            if (avgCost <= 0) return '0.00';
            return ((p - avgCost) * q - f).toFixed(2);
        }
    }

    // 保存买入时的目标价/止损价/盈利机会原值（切换方向时保留）
    let savedTarget = '';
    let savedStop = '';
    let savedWin = '';

    // 更新所有自动计算字段
    function updateCalculations() {
        const intent = getIntentValue();
        const price = parseFloat(priceInput.value) || 0;
        const qty = parseInt(qtyInput.value) || 0;
        const target = parseFloat(targetInput.value) || 0;
        const stop = parseFloat(stopInput.value) || 0;

        // 成交金额
        const amount = price * qty;
        amountInput.value = amount.toFixed(2);

        // 交易费用（价格/数量变化时自动计算）
        const fee = calcFee(amount, intent);
        feeInput.value = fee;

        // 预计收益
        profitInput.value = calcProfit(intent, price, qty, target, fee);

        // 风险资金
        if (intent === 'B') {
            riskInput.value = calcRisk(price, stop, qty);
        } else {
            // 卖出：显示当前持仓风险资金
            riskInput.value = currentRisk.toFixed(2);
        }

        // 允许数量
        if (intent === 'B') {
            allowedInput.value = calcAllowedQty(price, stop, cash, available, 'B');
        } else {
            allowedInput.value = positionQty;
        }

        // 盈利机会（仅买入时自动计算）
        if (intent === 'B' && !winInput.readOnly) {
            winInput.value = calcWinRatio(price, target, stop, 'B');
        }

        // 成交数量超过允许数量时，成交数量变红加粗
        const allowedQty = parseInt(allowedInput.value) || 0;
        if (qty > allowedQty && allowedQty > 0) {
            qtyInput.style.color = '#8B0000';
            qtyInput.style.fontWeight = 'bold';
        } else {
            qtyInput.style.color = '';
            qtyInput.style.fontWeight = '';
        }
    }

    // 仅更新预计收益（用户手动修改费用时调用）
    function updateProfitOnly() {
        const intent = getIntentValue();
        const price = parseFloat(priceInput.value) || 0;
        const qty = parseInt(qtyInput.value) || 0;
        const target = parseFloat(targetInput.value) || 0;
        const fee = parseFloat(feeInput.value) || 0;
        profitInput.value = calcProfit(intent, price, qty, target, fee);
    }

    // 获取交易方向（B/S），兼容文本框显示"买入"/"卖出"
    function getIntentValue() {
        const val = intentSelect.value;
        if (val === '买入' || val === 'B') return 'B';
        if (val === '卖出' || val === 'S') return 'S';
        return intentHidden.value || 'B';
    }

    // 切换交易方向（现在方向不可切换，仅用于初始化状态）
    function switchIntent() {
        const intent = getIntentValue();
        intentHidden.value = intent;

        if (intent === 'S') {
            // 保存买入时的原值
            savedTarget = targetInput.value;
            savedStop = stopInput.value;
            savedWin = winInput.value;
            // 卖出：目标价/止损价/盈利机会设为只读，值为"-"，不设灰色背景
            [targetInput, stopInput, winInput].forEach(el => {
                if (el) {
                    el.value = '-';
                    el.readOnly = true;
                }
            });
            // 卖出数量默认持仓量
            if (positionQty > 0) {
                qtyInput.value = positionQty;
                qtyInput.max = positionQty;
            }
        } else {
            // 买入：恢复可编辑，仅从卖出切换回来时恢复原值（初始化时不覆盖模板数据）
            targetInput.readOnly = false;
            stopInput.readOnly = false;
            winInput.readOnly = false;
            if (savedTarget !== '') targetInput.value = savedTarget;
            if (savedStop !== '') stopInput.value = savedStop;
            if (savedWin !== '') winInput.value = savedWin;
            qtyInput.removeAttribute('max');
        }
        updateCalculations();
    }

    // 事件绑定
    priceInput.addEventListener('input', updateCalculations);
    qtyInput.addEventListener('input', updateCalculations);
    targetInput.addEventListener('input', updateCalculations);
    stopInput.addEventListener('input', updateCalculations);
    feeInput.addEventListener('input', updateProfitOnly);
    // 交易方向变化时重新计算（无持仓时为下拉框）
    if (intentSelect.tagName === 'SELECT') {
        intentSelect.addEventListener('change', () => {
            updateCalculations();
            // 切换方向时更新目标价/止损价/盈利机会的只读状态
            const intent = getIntentValue();
            if (intent === 'S') {
                targetInput.readOnly = true;
                stopInput.readOnly = true;
                winInput.readOnly = true;
                targetInput.value = '-';
                stopInput.value = '-';
                winInput.value = '-';
            } else {
                targetInput.readOnly = false;
                stopInput.readOnly = false;
                winInput.readOnly = false;
                targetInput.value = '';
                stopInput.value = '';
                winInput.value = '';
            }
        });
    }

    // 表单提交：AJAX 方式，失败时弹窗报错，成功时跳转
    form.addEventListener('submit', (e) => {
        e.preventDefault();
        intentHidden.value = getIntentValue();
        // 卖出时目标价/止损价/盈利机会提交空值
        if (getIntentValue() === 'S') {
            targetInput.value = '';
            stopInput.value = '';
            winInput.value = '';
        }

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

    // 初始化
    switchIntent();
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
    const initChart = opts.initChart || {};

    setPageConfig(initChart);
    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
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

    const cash = opts.cash || 0;
    const available = opts.available || 0;
    const avgCost = opts.avg_cost || 0;
    const avgCostNoFee = opts.avg_cost_no_fee || 0;
    const positionQty = opts.position_qty || 0;
    const positionCost = opts.position_cost || 0;
    const commissionRatio = opts.commission_ratio || 0;
    const commissionMin = opts.commission_min || 0;
    const stampSellRatio = opts.stamp_sell_ratio || 0;
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

    // 自动计算
    function updateCalculations() {
        const target = parseFloat(targetInput.value) || 0;
        const stop = parseFloat(stopInput.value) || 0;
        const qty = positionQty;

        // 预期收益 = 卖出收入 - 卖出费用 - 持仓成本(含买入手续费)
        if (qty > 0 && target > 0) {
            const sellAmount = target * qty;
            const commission = Math.max(sellAmount * commissionRatio, commissionMin);
            const stamp = sellAmount * stampSellRatio;
            const sellFee = commission + stamp;
            profitInput.value = (sellAmount - sellFee - positionCost).toFixed(2);
        } else {
            profitInput.value = '0.00';
        }

        // 风险资金 = (不含手续费均价 - 止损价) × 数量
        if (avgCostNoFee > stop && qty > 0) {
            riskInput.value = ((avgCostNoFee - stop) * qty).toFixed(2);
        } else {
            riskInput.value = '0.00';
        }

        // 盈利机会（持仓股票默认买入逻辑）
        winInput.value = calcWinRatio(avgCost, target, stop, 'B');
    }

    targetInput.addEventListener('input', updateCalculations);
    stopInput.addEventListener('input', updateCalculations);
}
