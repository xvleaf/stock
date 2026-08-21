import { request, Highcharts, pageConfig, priceDecimal, setPriceDecimal, hideChartPlaceholder, showChartError } from './func.js';

// ========== 分时图全局状态变量 ==========
let trendTimer = null;
let trendChart = null;
let trendIndex = 0;
let trendIndexNew = 0;
let ohlcData = [];
let volumeData = [];
let ohlcNewData = [];
let volumeNewData = [];
let preClosePrice = 0;
let tickInterval = 0;
let tickMax = 0;
let tickMin = 0;

// ==================== 分时图逻辑 ====================
export async function initTrendChart() {
    trendIndex = 0;
    trendIndexNew = 0;
    await Promise.all([
        fetchTrendData(true)
    ]);
    if (ohlcData.length > 0) {
        renderTrendChart();
        hideChartPlaceholder();
    } else {
        showChartError('数据加载失败');
    }
    trendTimer = setInterval(async () => {
        const hasNew = await fetchTrendData(false);
        if (hasNew && trendChart) updateTrendChart();
    }, pageConfig.interval);
}

/**
async function fetchMarketQuote() {
    const data = await request.async('/chart/data', {
        site: pageConfig.site,
        cat: pageConfig.cat,
        code: pageConfig.marketCode,
        func: 'quote'
    });
    if (!data) return;
    const market = data.market;
    document.getElementById('marketName').textContent = market.n || '--';
    document.getElementById('marketPrice').textContent = 
        market.c !== '-' ? Number(market.c).toFixed(2) : '--';
    document.getElementById('marketChange').textContent = 
        market.p !== '-' ? market.p + '%' : '--';
}
 */

async function fetchTrendData(isInitial) {
    const data = await request.async('/chart/data', {
        site: pageConfig.site,
        cat: pageConfig.cat,
        code: pageConfig.marketCode,
        func: 'trend',
        init: isInitial ? '0' : '1'
    });
    if (!data) return false;

    // 更新公共轴参数
    preClosePrice = data.pc;
    setPriceDecimal(data.deci);
    tickInterval = data.tick_itv;
    tickMax = data.tick_max;
    tickMin = data.tick_min;

    // 初始化 或 后端标记交易日切换：全量替换数据并重绘
    if (isInitial || data.reset) {
        ohlcData = data.ohlc;
        volumeData = data.volume;
        trendIndex = data.index;
        
        // 非初始化的重置（交易日自动切换），主动重绘图表
        if (!isInitial && trendChart) {
            renderTrendChart();
        }
    } else {
        // 正常日内增量更新
        ohlcNewData = data.ohlc;
        volumeNewData = data.volume;
        trendIndexNew = data.index;
    }

    return trendIndex > 0;
}

function renderTrendChart() {
    const container = document.getElementById('chartContainer');
    const priceLen = preClosePrice.toFixed(priceDecimal).length;
    const paddingLeft = priceLen >= 5 ? 45 : 30;
    Highcharts.setOptions({
        global: { useUTC: false, timezone: 'Asia/Shanghai' }
    });
    trendChart = Highcharts.stockChart(container, {
        chart: { spacing: [0, 0, 0, 0], borderWidth: 0 },
        navigator: { enabled: false },
        scrollbar: { enabled: false },
        exporting: { enabled: false },
        credits: { enabled: false },
        rangeSelector: { enabled: false },
        plotOptions: {
            series: {
                animation: false,
                dataGrouping: { enabled: false },
                states: { hover: { enabled: false } }
            }
        },
        xAxis: {
            type: 'datetime',
            ordinal: true,
            connectNulls: true,
            tickInterval: 30 * 60 * 1000   // 新增：每30分钟一个刻度
        },
        yAxis: [
            {
                height: '75%',
                min: tickMin,
                max: tickMax,
                tickInterval: tickInterval,
                labels: {
                    x: -2,
                    formatter: function () {
                        const percent = ((this.value - preClosePrice) / preClosePrice * 100).toFixed(1);
                        const isUp = percent > 0;
                        const color = isUp ? 'purple' : 'gray';
                        const sign = isUp ? '+' : '';
                        return `<span style="color:${color}">${sign}${percent}</span>`;
                    }
                }
            },
            {
                height: '75%',
                linkedTo: 0,
                opposite: false,
                labels: {
                    x: paddingLeft,
                    formatter: function () {
                        return this.value.toFixed(priceDecimal);
                    }
                }
            },
            { top: '75%', height: '25%', offset: 0, labels: { x: -2 } }
        ],
        tooltip: {
            shared: true,
            split: true,
            animation: false,
            useHTML: true,
            formatter: function () {
                const point = this.points[0];
                const time = new Date(point.x);
                const hour = String(time.getHours()).padStart(2, '0');
                const minute = String(time.getMinutes()).padStart(2, '0');
                return `
                    <b>${hour}:${minute}</b>
                    <table>
                        <tr><td>成交价 ${point.y.toFixed(priceDecimal)}</td></tr>
                        <tr><td>涨跌额 ${point.point.delta.toFixed(priceDecimal)}</td></tr>
                        <tr><td>涨跌幅 ${point.point.percent.toFixed(2)}%</td></tr>
                        <tr><td>成交量 ${this.points[1].y}</td></tr>
                    </table>
                `;
            }
        },
        series: [
            { type: 'spline', data: ohlcData, yAxis: 1, lineColor: 'gray', keys: ['x', 'y', 'percent', 'delta'] },
            { type: 'column', data: volumeData, yAxis: 2, color: 'gray' }
        ]
    });
}

function updateTrendChart() {
    if (trendIndexNew <= 0 || !trendChart) return;
    for (let i = 0; i < ohlcNewData.length; i++) {
        if (trendIndex < ohlcData.length) {
            ohlcData[trendIndex] = ohlcNewData[i];
            volumeData[trendIndex] = volumeNewData[i];
        } else {
            ohlcData.push(ohlcNewData[i]);
            volumeData.push(volumeNewData[i]);
        }
        trendIndex++;
    }
    trendIndexNew = trendIndex;
    trendChart.update({
        series: [{ data: ohlcData }, { data: volumeData }],
        yAxis: [{ min: tickMin, max: tickMax, tickInterval: tickInterval }]
    });
}

/**
 * 渲染分时操作按钮
 */
export function renderTrendActionButtons() {
    const act = pageConfig.trendAct;
    const exitBtn = document.getElementById('btnExit');
    const editBtn = document.getElementById('btnEdit');
    const dealBtn = document.getElementById('btnDeal');
    if (!act || act === 'None') {
        exitBtn.style.visibility = 'hidden';
        editBtn.style.visibility = 'hidden';
        dealBtn.style.visibility = 'hidden';
        return;
    }
    if (act.exit === 'exit') exitBtn.innerHTML = '<i class="fas fa-xmark"></i>';
    else if (act.exit === 'end') exitBtn.innerHTML = '<i class="fas fa-trash-can"></i>';
    else exitBtn.style.visibility = 'hidden';
    if (act.edit === 'edit') editBtn.innerHTML = '<i class="fas fa-pen-to-square"></i>';
    else if (act.edit === 'plus') editBtn.innerHTML = '<i class="fas fa-plus"></i>';
    else if (act.edit === 'divd') editBtn.innerHTML = '<i class="fas fa-coins"></i>';
    else editBtn.style.visibility = 'hidden';
    if (act.deal === 'deal') dealBtn.innerHTML = '<i class="fas fa-cart-shopping"></i>';
    else dealBtn.style.visibility = 'hidden';
}

/**
 * 清除分时定时器
 */
export function clearTrendTimer() {
    if (trendTimer) {
        clearInterval(trendTimer);
        trendTimer = null;
    }
}