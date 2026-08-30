import { postRequest, Highcharts, pageConfig, initPageElements, priceDecimal, setPriceDecimal, hideChartPlaceholder, showChartError } from './func.js';

// ========== 分时图全局状态变量 ==========
export let trendChart = null;
let trendTimer = null;
let trendInterval = 20000;
let trendIndex = 0;
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
    
    const event = new CustomEvent('chartLoaded', { 
        detail: { site: pageConfig.site, view: pageConfig.view } 
    });
    window.dispatchEvent(event);
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
    if (!data) return false;

    preClosePrice = data.pc;
    setPriceDecimal(data.deci);
    tickMax = data.tick_max;
    tickMin = data.tick_min;
    tickItv = data.tick_itv;

    if (step === '0' || data.reset) {
        // 全量替换数据
        ohlcData = data.ohlc;
        volumeData = data.volume;
        // 若为增量阶段触发的重置（交易日切换），直接更新图表数据
        if (step === '1' && trendChart) {
            updateChartData(ohlcData, volumeData, tickMin, tickMax, tickItv);
        }
    } else {
        // 增量更新：保存新数据，按时间戳合并
        ohlcNewData = data.ohlc;
        volumeNewData = data.volume;
        updateTrendChart(); // 内部按时间戳更新
    }

    return ohlcData.some(item => item[1] !== null && item[1] !== undefined);
}

function updateChartData(ohlc, volume, min, max, itv) {
    if (!trendChart) return;
    trendChart.update({
        series: [
            { data: ohlc, connectNulls: true },
            { data: volume }
        ],
        yAxis: [{
            min: min,
            max: max,
            tickItv: itv
        }]
    });
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
            { 
                type: 'spline', 
                data: ohlcData, 
                yAxis: 1, 
                lineColor: 'gray', 
                keys: ['x', 'y', 'percent', 'delta'],
                connectNulls: true   // 强制连接空值点 
            },
            { 
                type: 'column', 
                data: volumeData, 
                yAxis: 2, 
                color: 'gray' 
            }
        ]
    });
}

function updateTrendChart() {
    if (!trendChart) return;
    if (ohlcNewData.length === 0) return;

    // 按时间戳查找并更新已有数据
    for (let i = 0; i < ohlcNewData.length; i++) {
        const newPoint = ohlcNewData[i];
        const ts = newPoint[0];
        const idx = ohlcData.findIndex(item => item[0] === ts);
        if (idx !== -1) {
            ohlcData[idx] = newPoint;
            volumeData[idx] = volumeNewData[i];
        } else {
            console.warn('时间戳未找到，可能数据不一致:', ts);
        }
    }

    // 更新图表
    trendChart.update({
        series: [
            { data: ohlcData, connectNulls: true },
            { data: volumeData }
        ],
        yAxis: [{
            min: tickMin,
            max: tickMax,
            tickItv: tickItv
        }]
    });

    // 清空新数据缓存，避免重复处理
    ohlcNewData = [];
    volumeNewData = [];
}

/**
 * 渲染分时操作按钮
 */
export function renderTrendParamBar() {
    const paramBar = document.getElementById('trendParam');
    if (!paramBar) return;
    
    const plusBtn = document.getElementById('plusBtn');
    const exitBtn = document.getElementById('exitBtn');
    const editBtn = document.getElementById('editBtn');
    const dealBtn = document.getElementById('dealBtn');
    const divdBtn = document.getElementById('divdBtn');
    
    plusBtn.classList.toggle('d-none', !pageConfig.trend.plus);
    exitBtn.classList.toggle('d-none', !pageConfig.trend.exit);
    editBtn.classList.toggle('d-none', !pageConfig.trend.edit);
    dealBtn.classList.toggle('d-none', !pageConfig.trend.deal);
    divdBtn.classList.toggle('d-none', !pageConfig.trend.divd);

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