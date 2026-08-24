import { postRequest, Highcharts, pageConfig, initPageElements, priceDecimal, setPriceDecimal, hideChartPlaceholder, showChartError } from './func.js';

// ========== 分时图全局状态变量 ==========
export let trendChart = null;
let trendTimer = null;
let trendInterval = 20000;
let trendIndex = 0;
let trendIndexNew = 0;
let ohlcData = [];
let volumeData = [];
let ohlcNewData = [];
let volumeNewData = [];
let preClosePrice = 0;
let tickItv = 0;
let tickMax = 0;
let tickMin = 0;

// ==================== 初始化入口 ====================
export async function initTrendChart() {
    // 重置索引
    trendIndex = 0;
    trendIndexNew = 0;

    const hasData = await loadTrendData('0');
    if (hasData) {
        renderTrendChart();
        hideChartPlaceholder();
        renderTrendParamBar();
    } else {
        showChartError('数据加载失败');
        return;
    }

    // 清除旧的定时器
    if (trendTimer) {
        clearInterval(trendTimer);
        trendTimer = null;
    }

    // 启动定时轮询
    trendTimer = setInterval(async () => {
        const hasNew = await loadTrendData('1');
        if (hasNew && trendChart) {
            updateTrendChart();
        }
    }, trendInterval);
}

// ---- 销毁 trendChart 实例 ----
export function destroyTrendChart() {
    if (trendChart) {
        trendChart.destroy();
        trendChart = null;
    }
}

async function fetchTrendData(step) {
    try {
        const { code, market, cat } = pageConfig; // 解构赋值
        
        if (!code || !market) {
            console.warn('fetchChartData: 参数缺失 code 或 market');
            return false;
        }

        const requestData = {
            func: 'get-trend-data',
            code: code,
            market: market,
            cat: cat,
            step: step // step 为 0 为初始化数据，为 1 为增量数据更新
        };
        const data = await postRequest('/chart/data', requestData);
        return data ?? null;
    } catch (error) {
        console.error('分时数据请求失败:', error);
        return null;
    }
}

async function loadTrendData(step) {
    const data = await fetchTrendData(step);
    if (!data) {
        return false;
    }

    preClosePrice = data.pc;
    setPriceDecimal(data.deci);   
    tickMax = data.tick_max;
    tickMin = data.tick_min;
    tickItv = data.tick_itv;

    // 判断是否需要全量重置（初始化 或 后端标记 reset）
    if (step === '0' || data.reset) {
        ohlcData = data.ohlc;
        volumeData = data.volume;
        trendIndex = data.index;
        
        // 非初始化的重置（交易日切换）,需主动重绘图表
        if (step === '1' && trendChart) {
            renderTrendChart();
        }
    } else {
        // 正常增量更新
        ohlcNewData = data.ohlc;
        volumeNewData = data.volume;
        trendIndexNew = data.index;
    }

    // 返回是否存在有效数据（索引 > 0 表示至少有一个数据）
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
            tickItv: 30 * 60 * 1000   // 新增：每30分钟一个刻度
        },
        yAxis: [
            {
                height: '75%',
                min: tickMin,
                max: tickMax,
                tickItv: tickItv,
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
        yAxis: [{ min: tickMin, max: tickMax, tickItv: tickItv }]
    });
}

/**
 * 渲染分时操作按钮
 */
function renderTrendParamBar() {
    /**
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
    */
    const paramBar = document.getElementById('trendParam');
    if (!paramBar) return;
    initPageElements();
    
    // 显示参数栏
    paramBar.classList.remove('d-none');
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