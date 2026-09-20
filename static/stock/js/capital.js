// capital.js — 资金总览页面：图表初始化 + 资金调整 + 日期筛选
import { showAlert, getCsrfToken } from './func.js';

const HISTORY_URL = '/capital/history';
const ADJUST_URL = '/capital/adjust';

let chartInstance = null;
let currentAdjustAction = 'deposit';
let adjustModalInstance = null;

// ===================== 图表初始化 =====================
export function initCapitalChart() {
    const startEl = document.getElementById('filterStartDate');
    const endEl = document.getElementById('filterEndDate');
    const start = (startEl?.textContent || '').replace(/\s/g, '').trim();
    const end = (endEl?.textContent || '').replace(/\s/g, '').trim();
    const url = `${HISTORY_URL}?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;

    fetch(url)
        .then(r => r.json())
        .then(data => {
            const placeholder = document.getElementById('capitalPlaceholder');
            const chartEl = document.getElementById('capitalChart');
            const chartWrap = chartEl?.closest('.capital-chart-wrap');
            if (!data || !data.total || data.total.length === 0) {
                if (placeholder) placeholder.style.display = 'flex';
                if (chartEl) chartEl.style.display = 'none';
                if (chartWrap) chartWrap.style.height = '25px';
                return;
            }
            if (placeholder) placeholder.style.display = 'none';
            if (chartEl) chartEl.style.display = 'block';
            if (chartWrap) chartWrap.style.height = '400px';
            renderChart(data);
        })
        .catch(err => {
            console.error('加载资金历史失败:', err);
        });
}

function renderChart(data) {
    const chartEl = document.getElementById('capitalChart');
    if (!chartEl || typeof Highcharts === 'undefined') return;

    if (chartInstance) {
        chartInstance.destroy();
        chartInstance = null;
    }

    // 收集所有唯一日期作为分类（按字符串排序）
    const allDates = [];
    [data.total, data.cash, data.stock].forEach(series => {
        series.forEach(p => {
            if (p[0] && !allDates.includes(p[0])) allDates.push(p[0]);
        });
    });
    allDates.sort();

    // 将 [date, value] 转为按分类顺序的纯数值数组
    function toValues(seriesData) {
        const map = {};
        seriesData.forEach(p => { map[p[0]] = p[1]; });
        return allDates.map(d => map[d] !== undefined ? map[d] : null);
    }

    // 计算全局最小/最大值，yAxis 上下各留 5%
    const allValues = [];
    [data.total, data.cash, data.stock].forEach(series => {
        series.forEach(p => { if (p[1] !== null && p[1] !== undefined) allValues.push(p[1]); });
    });
    const minVal = Math.min(...allValues);
    const maxVal = Math.max(...allValues);
    const yMin = minVal >= 0 ? minVal * 0.95 : minVal * 1.05;
    const yMax = maxVal >= 0 ? maxVal * 1.05 : maxVal * 0.95;

    chartInstance = Highcharts.chart(chartEl, {
        chart: {
            height: 400,
            spacing: [10, 10, 15, 10],
            borderWidth: 0,
        },
        title: {
            text: '资金变化趋势',
            margin: 5,
            style: { fontSize: '1rem', fontWeight: 'bold' },
        },
        xAxis: {
            type: 'category',
            categories: allDates,
            labels: {
                rotation: -30,
                style: { fontSize: '11px' },
                formatter: function () {
                    const cats = this.axis && this.axis.categories ? this.axis.categories : [];
                    const cat = cats[this.value] !== undefined ? cats[this.value] : this.value;
                    return typeof cat === 'string' && cat.length >= 5 ? cat.substring(5) : cat;
                },
            },
        },
        yAxis: {
            min: yMin,
            max: yMax,
            title: { text: '金额（元）' },
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
                // 从第一个 point 的 xAxis 获取分类名称
                const xAxis = this.points && this.points[0] ? this.points[0].series.xAxis : null;
                const cats = xAxis && xAxis.categories ? xAxis.categories : [];
                const dateStr = cats[this.x] !== undefined ? cats[this.x] : this.x;
                let rows = '';
                this.points.forEach(p => {
                    rows += `<tr><td style="padding:2px 5px"><span style="color:${p.color}">●</span> ${p.series.name}</td><td style="padding:2px 5px">${p.y.toFixed(2)}</td></tr>`;
                });
                return `<div><table>
                    <tr><td colspan="2" style="padding:2px 5px"><span style="font-weight:bold;">${dateStr}</span></td></tr>
                    ${rows}
                </table></div>`;
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
            },
        },
        series: [
            { name: '资产', data: toValues(data.total), color: '#dc2626', lineWidth: 2 },
            { name: '现金', data: toValues(data.cash), color: '#06b6d4', lineWidth: 1.5 },
            { name: '股票', data: toValues(data.stock), color: '#f59e0b', lineWidth: 1.5 },
        ],
        credits: { enabled: false },
    });
}

// ===================== 日期筛选（失焦自动触发） =====================
export function initDateFilter() {
    const startEl = document.getElementById('filterStartDate');
    const endEl = document.getElementById('filterEndDate');
    if (!startEl && !endEl) return;

    // 记录初始值，只有真正变化时才触发
    let origStart = (startEl?.textContent || '').replace(/\s/g, '').trim();
    let origEnd = (endEl?.textContent || '').replace(/\s/g, '').trim();

    function doFilter() {
        const start = (startEl?.textContent || '').replace(/\s/g, '').trim();
        const end = (endEl?.textContent || '').replace(/\s/g, '').trim();
        // 值未变化则不触发
        if (start === origStart && end === origEnd) return;
        // 格式校验
        if (start && !/^\d{4}-\d{2}-\d{2}$/.test(start)) {
            showAlert({ title: '提示', text: '开始日期格式应为 YYYY-MM-DD', type: 'warning' });
            if (startEl) startEl.textContent = origStart;
            return;
        }
        if (end && !/^\d{4}-\d{2}-\d{2}$/.test(end)) {
            showAlert({ title: '提示', text: '结束日期格式应为 YYYY-MM-DD', type: 'warning' });
            if (endEl) endEl.textContent = origEnd;
            return;
        }
        fetch('/capital', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ start_date: start, end_date: end }),
        }).then(() => {
            window.location.reload();
        }).catch(() => {
            window.location.reload();
        });
    }

    // 失焦时触发筛选
    [startEl, endEl].forEach(el => {
        if (!el) return;
        el.addEventListener('blur', doFilter);
        // 回车也触发
        el.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                el.blur();
            }
        });
    });
}

// ===================== 资金调整 Modal =====================
export function initAdjustModal() {
    // +/- 按钮打开 Modal
    document.querySelectorAll('.capital-adjust-btn').forEach(btn => {
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
        confirmBtn.addEventListener('click', () => adjustCapital(currentAdjustAction));
    }
}

function openAdjustModal(action) {
    currentAdjustAction = action;
    const titleEl = document.getElementById('adjustModalTitle');
    if (titleEl) titleEl.textContent = action === 'deposit' ? '存入' : '取出';
    // 清空输入
    const dateEl = document.getElementById('modalAdjustDate');
    const amountEl = document.getElementById('modalAdjustAmount');
    const remarkEl = document.getElementById('modalAdjustRemark');
    if (dateEl) dateEl.value = '';
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
export function adjustCapital(action) {
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
            updateCard('capitalTotal', res.total);
            updateCard('capitalCash', res.cash);
            updateCard('capitalStock', res.stock);
            updateCard('capitalAvailable', res.available);
            showAlert({ title: '成功', text: `${actionText}成功`, type: 'success' });
            // 自动刷新页面（图表 + 记录表格同时更新）
            setTimeout(() => { window.location.reload(); }, 600);
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
