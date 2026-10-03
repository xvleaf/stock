// cash.js — 资金总览页面：图表初始化 + 资金调整 + 日期筛选
import { showAlert, showConfirm, getCsrfToken } from './func.js';

const HISTORY_URL = '/cash/history';
const ADJUST_URL = '/cash/adjust';
const REVOKE_URL = '/cash/revoke';
const INIT_URL = '/cash/init';

let chartInstance = null;
let currentAdjustAction = 'deposit';
let adjustModalInstance = null;

// ===================== 图表初始化 =====================
export function initCashChart() {
    const url = HISTORY_URL;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            const placeholder = document.getElementById('cashPlaceholder');
            const chartEl = document.getElementById('cashChart');
            const chartWrap = chartEl?.closest('.cash-chart-wrap');
            if (!data || !data.total || data.total.length === 0) {
                if (placeholder) placeholder.style.display = 'flex';
                if (chartEl) chartEl.style.display = 'none';
                if (chartWrap) chartWrap.style.height = '25px';
                return;
            }
            if (placeholder) placeholder.style.display = 'none';
            if (chartEl) chartEl.style.display = 'block';
            const chartHeight = window.UI_CONFIG ? window.UI_CONFIG.cash_chart_height : 400;
            if (chartWrap) chartWrap.style.height = chartHeight + 'px';
            renderChart(data);
        })
        .catch(err => {
            console.error('加载资金历史失败:', err);
        });
}

function renderChart(data) {
    const chartEl = document.getElementById('cashChart');
    if (!chartEl || typeof Highcharts === 'undefined') return;

    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }

    // 按数据点顺序收集日期（不去重，同一天多笔变动各自独立显示）
    const maxLen = Math.max(data.total.length, data.cash.length, data.stock.length, data.profit ? data.profit.length : 0);
    const refSeries = data.total.length ? data.total : (data.cash.length ? data.cash : data.stock);
    const allDates = [];
    for (let i = 0; i < maxLen; i++) {
        allDates.push(refSeries[i] ? refSeries[i][0] : '');
    }

    // 按索引取值转为纯数值数组（同一天多个点各自保留，不覆盖）
    function toValues(seriesData) {
        const result = [];
        for (let i = 0; i < maxLen; i++) {
            result.push(seriesData[i] ? seriesData[i][1] : null);
        }
        return result;
    }

    // 根据可见曲线数据计算纵轴范围（全隐藏时按4条均显示兜底）
    function calcYAxisRange(visibleSeries) {
        const Y_AXIS_PADDING = 0.05;
        const allFour = [data.total, data.cash, data.stock, data.profit || []];
        // 若所有曲线均隐藏，则按四条曲线均显示来计算
        let seriesToUse = visibleSeries.length > 0 ? visibleSeries : allFour;

        const allValues = [];
        seriesToUse.forEach(series => {
            if (!series) return;
            series.forEach(p => { if (p && p[1] !== null && p[1] !== undefined) allValues.push(p[1]); });
        });
        if (allValues.length === 0) return { min: 0, max: 100 };

        const minVal = Math.min(...allValues);
        const maxVal = Math.max(...allValues);
        let yMin = minVal >= 0 ? minVal * (1 - Y_AXIS_PADDING) : minVal * (1 + Y_AXIS_PADDING);
        let yMax = maxVal >= 0 ? maxVal * (1 + Y_AXIS_PADDING) : maxVal * (1 - Y_AXIS_PADDING);
        const padding = Math.max(yMax - maxVal, minVal - yMin);
        return { min: minVal - padding, max: maxVal + padding };
    }

    // 初始化时按可见曲线计算（默认只有收益可见）
    const initialRange = calcYAxisRange([data.profit || []]);
    let yMin = initialRange.min;
    let yMax = initialRange.max;

    // 图表创建前：混合方案计算刻度位置（优先整除均匀间距，太少时回退循环去掉）
    const total = allDates.length;
    const chartWidth = chartEl.offsetWidth || 800;
    const LABEL_WIDTH = 60;
    const maxLabels = Math.min(24, Math.max(3, Math.floor(chartWidth / LABEL_WIDTH)));

    let tickPositions;
    if (total <= maxLabels) {
        // 数据点少，全部显示
        tickPositions = [];
        for (let i = 0; i < total; i++) tickPositions.push(i);
    } else {
        const expectedStep = Math.max(1, Math.ceil((total - 1) / (maxLabels - 1)));
        // 方案A：向上找能整除 (total-1) 的 step，实现间距均匀
        let step = expectedStep;
        while (step <= total - 1 && (total - 1) % step !== 0) {
            step++;
        }
        const actualLabels = (total - 1) / step + 1;

        if (actualLabels >= maxLabels / 2) {
            // 整除方案：标签数可接受，所有间距严格相等
            tickPositions = [];
            for (let i = 0; i <= total - 1; i += step) {
                tickPositions.push(i);
            }
        } else {
            // 回退方案：步长 + 首尾保留 + 循环去掉间距不足的倒数第二个
            step = expectedStep;
            tickPositions = [];
            for (let i = 0; i < total; i += step) {
                tickPositions.push(i);
            }
            if (tickPositions[tickPositions.length - 1] !== total - 1) {
                tickPositions.push(total - 1);
            }
            while (tickPositions.length >= 2) {
                const last = tickPositions[tickPositions.length - 1];
                const secondLast = tickPositions[tickPositions.length - 2];
                if (last - secondLast < step) {
                    tickPositions.splice(tickPositions.length - 2, 1);
                } else {
                    break;
                }
            }
        }
    }

    const chartHeight = window.UI_CONFIG ? window.UI_CONFIG.cash_chart_height : 400;
    chartInstance = Highcharts.chart(chartEl, {
        chart: {
            height: chartHeight,
            spacing: [10, 5, 10, 2],
            borderWidth: 0,
            events: {
                load: function () {
                    if (allDates.length < 2) return;
                    const xAxis = this.xAxis[0];
                    const px25 = xAxis.toValue(25) - xAxis.toValue(0);
                    // 仅扩展x轴两端25px边距，刻度位置由tickPositions限定在数据点范围内
                    xAxis.update({
                        min: -px25,
                        max: (allDates.length - 1) + px25,
                    });
                },
            },
        },
        title: {
            text: '资金变化趋势',
            margin: 5,
            style: { fontSize: '1rem', color: '#212529' },
        },
        xAxis: {
            type: 'linear',
            min: 0,
            max: allDates.length - 1,
            tickPositions: tickPositions,
            minPadding: 0,
            maxPadding: 0,
            labels: {
                rotation: 0,
                style: { fontSize: '11px' },
                formatter: function () {
                    const cat = allDates[this.value];
                    return cat && cat.length >= 5 ? cat.substring(5) : '';
                },
            },
        },
        yAxis: {
            min: yMin,
            max: yMax,
            title: { text: '金额（元）', margin: 3 },
            labels: {
                formatter: function () {
                    return this.value >= 10000
                        ? (this.value / 10000).toFixed(1) + '万'
                        : this.value.toFixed(0);
                },
            },
        },
        tooltip: {
            shared: true,
            animation: false,
            useHTML: true,
            backgroundColor: '#fff',
            borderColor: '#e8ecf0',
            borderRadius: 8,
            style: { fontSize: '13px' },
            crosshairs: [{
                color: '#c0c4cc',
                width: 1,
                dashStyle: 'dash',
            }, false],
            formatter: function () {
                const dateStr = allDates[this.x] !== undefined ? allDates[this.x] : this.x;
                const reasonItem = data.reasons && data.reasons[this.x] ? data.reasons[this.x] : null;
                const eventStr = reasonItem ? reasonItem.event : '';
                const remarkStr = reasonItem && reasonItem.remark ? reasonItem.remark : '';

                // 获取各曲线值
                const getVal = (name) => {
                    const s = chartInstance.series.find(s => s.name === name);
                    const p = s && s.data[this.x];
                    return (p && p.y !== null && p.y !== undefined) ? p.y.toFixed(2) : '--';
                };

                return `<div style="font-size:13px;">
                    <div style="font-weight:bold;margin-bottom:4px;">${dateStr}${eventStr ? ', ' + eventStr : ''}</div>
                    ${remarkStr ? `<div style="margin-bottom:4px;color:#666;">[${remarkStr}]</div>` : ''}
                    <table>
                        <tr>
                            <td style="padding:4px 8px 4px 0;">资产：${getVal('资产')}</td>
                            <td style="padding:4px 0;">收益：${getVal('收益')}</td>
                        </tr>
                        <tr>
                            <td style="padding:4px 8px 4px 0;">现金：${getVal('现金')}</td>
                            <td style="padding:4px 0;">股票：${getVal('股票')}</td>
                        </tr>
                    </table>
                </div>`;
            },
        },
        legend: {
            enabled: true,
            align: 'center',
            verticalAlign: 'top',
            y: 0,
            margin: 0,
        },
        plotOptions: {
            series: {
                animation: false,
                states: { hover: { enabled: false } },
                events: {
                    legendItemClick: function () {
                        // 延迟执行，等 Highcharts 切换可见状态后再重新计算
                        setTimeout(() => {
                            if (!chartInstance) return;
                            const visibleSeries = chartInstance.series
                                .filter(s => s.visible)
                                .map(s => s.options.rawData || []);
                            const range = calcYAxisRange(visibleSeries);
                            chartInstance.yAxis[0].update({ min: range.min, max: range.max });
                        }, 50);
                    },
                },
            },
        },
        series: [
            { name: '资产', data: toValues(data.total), rawData: data.total, color: '#06b6d4', lineWidth: 2, visible: false },
            { name: '现金', data: toValues(data.cash), rawData: data.cash, color: '#2563eb', lineWidth: 1.5, visible: false },
            { name: '股票', data: toValues(data.stock), rawData: data.stock, color: '#8b5cf6', lineWidth: 1.5, visible: false },
            { name: '收益', data: toValues(data.profit || []), rawData: data.profit || [], color: '#dc2626', lineWidth: 1.5 },
        ],
        credits: { enabled: false },
    });
}

// ===================== 资金调整 Modal =====================
export function initAdjustModal() {
    // +/- 按钮打开 Modal
    document.querySelectorAll('.cash-adjust-btn').forEach(btn => {
        btn.addEventListener('click', () => openAdjustModal(btn.dataset.action));
    });
    // 取消按钮
    const cancelBtn = document.getElementById('adjustModalCancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            if (adjustModalInstance) adjustModalInstance.hide();
        });
    }
    // 确认按钮
    const confirmBtn = document.getElementById('adjustModalConfirm');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', () => adjustCash(currentAdjustAction));
    }
}

// ===================== 变更风险额度 Modal =====================
let quotaModalInstance = null;

export function initQuotaModal() {
    // 编辑图标打开 Modal
    const editBtn = document.getElementById('cashEditQuota');
    if (editBtn) {
        editBtn.addEventListener('click', openQuotaModal);
    }
    // 取消按钮
    const cancelBtn = document.getElementById('quotaModalCancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            if (quotaModalInstance) quotaModalInstance.hide();
        });
    }
    // 确认按钮
    const confirmBtn = document.getElementById('quotaModalConfirm');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', submitQuota);
    }
}

function openQuotaModal() {
    // 填入当前额度
    const amountEl = document.getElementById('modalQuotaAmount');
    const currentEl = document.getElementById('cashAllowance');
    if (amountEl && currentEl) {
        amountEl.value = currentEl.textContent.replace(/,/g, '');
    }
    // 显示 Modal
    const modalEl = document.getElementById('quotaModal');
    if (modalEl && typeof bootstrap !== 'undefined') {
        if (!quotaModalInstance) {
            quotaModalInstance = new bootstrap.Modal(modalEl);
        }
        quotaModalInstance.show();
    }
}

function submitQuota() {
    const amountEl = document.getElementById('modalQuotaAmount');
    const amount = parseFloat(amountEl?.value);
    if (isNaN(amount) || amount < 0) {
        showAlert({ title: '提示', text: '请输入有效的金额', type: 'warning' });
        return;
    }
    fetch('/cash/quota', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ amount }),
    })
        .then(r => r.json())
        .then(res => {
            if (res.error) {
                showAlert({ title: '失败', text: res.error, type: 'error' });
                return;
            }
            if (quotaModalInstance) quotaModalInstance.hide();
            updateCard('cashAllowance', res.allowance);
            showAlert({ title: '成功', text: '风险额度已更新', type: 'success' });
        })
        .catch(err => {
            console.error('变更风险额度失败:', err);
            showAlert({ title: '失败', text: '请求失败，请稍后重试', type: 'error' });
        });
}

function openAdjustModal(action) {
    currentAdjustAction = action;
    const titleEl = document.getElementById('adjustModalTitle');
    if (titleEl) titleEl.textContent = action === 'deposit' ? '存入' : '取出';
    // 清空输入（日期默认填当天）
    const dateEl = document.getElementById('modalAdjustDate');
    const amountEl = document.getElementById('modalAdjustAmount');
    const remarkEl = document.getElementById('modalAdjustRemark');
    if (dateEl) dateEl.value = new Date().toISOString().slice(0, 10);
    if (amountEl) amountEl.value = '';
    if (remarkEl) remarkEl.value = '';
    // 显示 Modal
    const modalEl = document.getElementById('adjustModal');
    if (modalEl && typeof bootstrap !== 'undefined') {
        if (!adjustModalInstance) {
            adjustModalInstance = new bootstrap.Modal(modalEl);
        }
        adjustModalInstance.show();
    }
}

// ===================== 资金调整 =====================
export function adjustCash(action) {
    const amountInput = document.getElementById('modalAdjustAmount');
    const remarkInput = document.getElementById('modalAdjustRemark');
    const dateInput = document.getElementById('modalAdjustDate');
    const amount = parseFloat(amountInput?.value);

    if (!amount || amount <= 0) {
        showAlert({ title: '提示', text: '请输入有效金额', type: 'warning' });
        return;
    }

    const actionText = action === 'deposit' ? '存入' : '取出';
    const dateStr = dateInput?.value?.trim() || '';
    if (dateStr) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
            showAlert({ title: '提示', text: '日期格式应为 YYYY-MM-DD', type: 'warning' });
            return;
        }
        const d = new Date(dateStr + 'T00:00:00');
        if (isNaN(d.getTime()) || d.getFullYear() < 2000 || d.getFullYear() > 2100) {
            showAlert({ title: '提示', text: '日期无效，请检查', type: 'warning' });
            return;
        }
    }

    fetch(ADJUST_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({
            action: action,
            amount: amount,
            remark: remarkInput?.value || '',
            date: dateInput?.value || '',
        }),
    })
        .then(r => r.json())
        .then(res => {
            if (res.error) {
                showAlert({ title: '失败', text: res.error, type: 'error' });
                return;
            }
            // 关闭 Modal
            if (adjustModalInstance) adjustModalInstance.hide();
            // 更新卡片数值
            updateCard('cashTotal', res.total);
            updateCard('cashCash', res.cash);
            updateCard('cashStock', res.stock);
            updateCard('cashAllowance', res.allowance);
            updateCard('cashRisk', res.risk);
            updateCard('cashProfit', res.profit);
            showAlert({ title: '成功', text: `${actionText}成功`, type: 'success' });
            // 自动刷新页面（图表 + 记录表格同时更新）
            setTimeout(() => { window.location.reload(); }, 3000);
        })
        .catch(err => {
            console.error('资金调整失败:', err);
            showAlert({ title: '失败', text: '请求失败，请稍后重试', type: 'error' });
        });
}

function updateCard(id, value) {
    const el = document.getElementById(id);
    if (el && value !== undefined && value !== null) {
        el.textContent = Number(value).toFixed(2);
    }
}

// ===================== 撤回最近一笔存入/取出 =====================
export function initRevokeBtn() {
    document.querySelectorAll('.cash-revoke-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id;
            if (!id) return;
            showConfirm({
                title: '撤回确认',
                text: '确定要撤回该笔操作吗？',
            }).then(confirmed => {
                if (confirmed) revokeCash(id);
            });
        });
    });
}

function revokeCash(historyId) {
    fetch(REVOKE_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({ history_id: parseInt(historyId) }),
    })
        .then(r => r.json())
        .then(res => {
            if (res.error) {
                showAlert({ title: '失败', text: res.error, type: 'error' });
                return;
            }
            showAlert({ title: '成功', text: '已撤回', type: 'success' });
            setTimeout(() => { window.location.reload(); }, 3000);
        })
        .catch(err => {
            console.error('撤回失败:', err);
            showAlert({ title: '失败', text: '请求失败，请稍后重试', type: 'error' });
        });
}

// ===================== 初始化资金弹窗 =====================
let initModalInstance = null;

export function initInitModal(initialized) {
    const modalEl = document.getElementById('initModal');
    if (!modalEl) return;
    initModalInstance = new bootstrap.Modal(modalEl);
    // 未初始化时自动弹出
    if (!initialized) {
        // 默认填写当前日期
        const dateInput = document.getElementById('modalInitDate');
        if (dateInput) {
            const today = new Date();
            const y = today.getFullYear();
            const m = String(today.getMonth() + 1).padStart(2, '0');
            const d = String(today.getDate()).padStart(2, '0');
            dateInput.value = `${y}-${m}-${d}`;
        }
        setTimeout(() => initModalInstance.show(), 300);
    }
    // 取消按钮
    const cancelBtn = document.getElementById('initModalCancel');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => initModalInstance.hide());
    }
    // 确认按钮
    const confirmBtn = document.getElementById('initModalConfirm');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', submitInit);
    }
}

function submitInit() {
    const dateStr = document.getElementById('modalInitDate')?.value?.trim();
    const cash = parseFloat(document.getElementById('modalInitCash')?.value);
    const stock = parseFloat(document.getElementById('modalInitStock')?.value);
    const allowance = parseFloat(document.getElementById('modalInitAllowance')?.value);

    if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) {
        showAlert({ title: '提示', text: '请输入有效的日期（YYYY-MM-DD）', type: 'warning' });
        return;
    }
    if (isNaN(cash) || cash < 0) {
        showAlert({ title: '提示', text: '请输入有效的现金资产', type: 'warning' });
        return;
    }
    if (isNaN(stock) || stock < 0) {
        showAlert({ title: '提示', text: '请输入有效的股票资产', type: 'warning' });
        return;
    }
    if (isNaN(allowance) || allowance < 0) {
        showAlert({ title: '提示', text: '请输入有效的风险额度', type: 'warning' });
        return;
    }

    fetch(INIT_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({
            date: dateStr,
            cash: cash,
            stock: stock,
            allowance: allowance,
        }),
    })
        .then(r => r.json())
        .then(res => {
            if (res.error) {
                showAlert({ title: '失败', text: res.error, type: 'error' });
                return;
            }
            if (initModalInstance) initModalInstance.hide();
            showAlert({ title: '成功', text: '资金初始化完成', type: 'success' });
            setTimeout(() => { window.location.reload(); }, 3000);
        })
        .catch(err => {
            console.error('初始化失败:', err);
            showAlert({ title: '失败', text: '请求失败，请稍后重试', type: 'error' });
        });
}
