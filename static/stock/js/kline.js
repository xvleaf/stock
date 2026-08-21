import { request, Highcharts, pageConfig, priceDecimal, setPriceDecimal, hideChartPlaceholder, showChartError } from './func.js';

// K 线密度参数
const BREAKPOINT_FOR_KLINE = 1440;
const KLINE_DENSITY = {
    desktop: { max: 15, std: 10, min: 5 },
    mobile:  { max: 20, std: 13, min: 5  }
};

// ========== K线图全局状态变量 ==========
let klineChart = null;
let klineData = {};
let initIdx = null;

// ==================== K线图逻辑 ====================
export function initKlineChart() {    
    fetchKlineData().then(success => {
        if (!success) {
            showChartError('K线数据加载失败');
            return;
        }
        renderklineData();
        hideChartPlaceholder();
        renderKlineParamBar();
        initIdx = firstSatisfyIndex(klineData.volume, klineData.deadline)
        updateKlineMetrics(initIdx);
    });
}

/** 非股票类数据接口 cat 备用 */
async function fetchKlineData() {
    let code = pageConfig.code;
    let market = pageConfig.market;
    
    if(code && market) {        
        const data = await request.async('/chart/data', {
            // cat: pageConfig.cat,
            code: code,
            market: market,
            func: 'get-kline-data',
        });
        if (!data) return false;
        klineData = data;
        return true;
    }
}

function renderklineData() {    
    const { ohlc, volume, tp, fl, up, av, lw, ma, mv, deal, deadline: rawDeadline, deci, freq } = klineData;
    
    // 前端计算显示区间，宽度与原请求参数保持一致
    const showResult = calcShowValues(
        [...ohlc], [...volume], freq, rawDeadline
    );
    const { show_min, show_std, show_max, deadline } = showResult;    
    const finalOhlc = showResult.ohlc;
    const finalVolume = showResult.volume;
    setPriceDecimal(deci);
    Highcharts.setOptions({
        lang: { rangeSelectorZoom: '' },
        global: { useUTC: false, timezone: 'Asia/Shanghai' }
    });
    klineChart = Highcharts.stockChart('chartContainer', {
        chart: {
            spacing: [0, 5, 0, 5],
            borderWidth: 0,
            plotBorderColor: '#cfd1ee',
            plotBorderWidth: 1,
            events: { render: function () { syncVolumeColor(this); } }
        },
        navigator: { enabled: false },
        scrollbar: { enabled: false },
        exporting: { enabled: false },
        credits: { enabled: false },
        rangeSelector: {
            inputEnabled: false,
            buttonSpacing: 2,
            buttonPosition: { align: 'left', x: 0, y: 35 },
            buttons: [
                { type: 'day', count: show_min, text: ' + ' },
                { type: 'day', count: show_std, text: ' · ' },
                { type: 'day', count: show_max, text: ' − ' }
            ],
            selected: 1
        },
        plotOptions: {
            series: {
                animation: false,
                dataGrouping: { enabled: false },
                states: { hover: { enabled: false }, inactive: { enabled: false } }
            }
        },
        xAxis: {
            type: 'date',
            ordinal: true,
            max: deadline,
            dateTimeLabelFormats: {
                day: '%m-%d', week: '%m-%d', month: '%y-%m', year: '%Y'
            }
        },
        yAxis: [
            { height: '80%', resize: { enabled: true }, labels: { align: 'right', x: -3 } },
            { top: '80%', height: '20%', offset: 0, labels: { align: 'right', x: -3 } }
        ],
        tooltip: {
            shared: true,
            split: true,
            animation: false,
            useHTML: true,
            formatter: function () {
                const point = this.points[0].point;
                updateKlineMetrics(point.index);
                const date = new Date(point.x);
                const dateStr = `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
                return `
                    <b>${dateStr}</b>
                    <table>
                        <tr><td>收盘 ${point.close.toFixed(priceDecimal)}</td>
                            <td style="padding-left:10px">开盘 ${point.open.toFixed(priceDecimal)}</td></tr>
                        <tr><td>最高 ${point.high.toFixed(priceDecimal)}</td>
                            <td style="padding-left:10px">最低 ${point.low.toFixed(priceDecimal)}</td></tr>
                        <tr><td>涨幅 ${klineData.ohlc[point.index][5]}%</td>
                            <td style="padding-left:10px">成交 ${(klineData.volume[point.index][1] / 10000).toFixed(0)}W</td></tr>
                    </table>
                `;
            }
        },
        series: [
            // 主图：K线本体
            { type: 'candlestick', data: finalOhlc, keys: ['x', 'open', 'high', 'low', 'close'], yAxis: 0, color: 'gray', lineColor: 'gray', upColor: 'white', upLineColor: 'purple' },
            // 副图：成交量
            { type: 'column', data: finalVolume, yAxis: 1, enableMouseTracking: false },
            // 外轨 tp/fl（灰色）
            { type: 'spline', data: tp, yAxis: 0, enableMouseTracking: false, color: '#c0c0c0', lineWidth: 1 },
            { type: 'spline', data: fl, yAxis: 0, enableMouseTracking: false, color: '#c0c0c0', lineWidth: 1 },
            // 中轨 av（黑色）
            { type: 'spline', data: av, yAxis: 0, color: '#000', lineWidth: 1, enableMouseTracking: false },
            // 内轨 up/lw（青色）
            { type: 'spline', data: up, yAxis: 0, color: '#1aadce', lineWidth: 1, enableMouseTracking: false },
            { type: 'spline', data: lw, yAxis: 0, color: '#1aadce', lineWidth: 1, enableMouseTracking: false },
            // MA20 均线（橙色）
            { type: 'spline', data: ma, yAxis: 0, color: 'orange', lineWidth: 1, enableMouseTracking: false },
            // 成交量均线（黑色，副图）
            { type: 'spline', data: mv, yAxis: 1, color: '#000', lineWidth: 1, enableMouseTracking: false },
            // 交易信号：买入
            { type: 'scatter', data: deal.long, yAxis: 0, color: 'red', enableMouseTracking: false, marker: { symbol: 'triangle', radius: 4 } },
            // 交易信号：卖出
            { type: 'scatter', data: deal.short, yAxis: 0, color: 'green', enableMouseTracking: false, marker: { symbol: 'triangle-down', radius: 4 } },
            // 交易信号：双向
            { type: 'scatter', data: deal.dual, yAxis: 0, color: 'orange', enableMouseTracking: false, marker: { symbol: 'diamond', radius: 4 } },
            // 交易信号：分红
            { type: 'scatter', data: deal.divd, yAxis: 0, color: 'blue', enableMouseTracking: false, marker: { symbol: 'diamond', radius: 4 } }
        ]
    });
}

function syncVolumeColor(chart) {
    const ohlcSeries = chart.series[0];
    const volumeSeries = chart.series[1];
    if (!ohlcSeries || !volumeSeries) return;
    ohlcSeries.points.forEach((point, index) => {
        const volPoint = volumeSeries.points[index];
        if (!volPoint || !volPoint.graphic || !volPoint.graphic.element) return;
        const color = point.close >= point.open ? 'purple' : 'gray';
        volPoint.graphic.element.setAttribute('fill', color);
    });
}
function renderKlineParamBar() {
    const paramBar = document.getElementById('klineParam');
    if (!paramBar) return;

    // 批量获取元素（减少 DOM 查询）
    const elements = {
        k: document.getElementById('kValueItem'),
        d: document.getElementById('dValueItem'),
        right: document.getElementById('changeRightItem'),
        freqDay: document.getElementById('changeFreqDay'),
        freqWeek: document.getElementById('changeFreqWeek'),
        freqMonth: document.getElementById('changeFreqMonth')
    };

    // 更新 K/D 值
    if (elements.k) elements.k.textContent = klineData.k ?? '--';
    if (elements.d) elements.d.textContent = klineData.d ?? '--';

    // 更新复权按钮（使用配置对象）
    if (elements.right) {
        const isQFQ = klineData.right === 'qfq';
        elements.right.innerHTML = isQFQ
            ? '<i class="metric-dark fas fa-repeat"></i>'
            : '<i class="metric-grey fas fa-ban"></i>';
    }

    // 更新频率按钮（使用配置数组）
    const freqMap = [
        { el: elements.freqDay, value: 'D', icon: 'fa-sun' },
        { el: elements.freqWeek, value: 'W', icon: 'fa-star-of-life' },
        { el: elements.freqMonth, value: 'M', icon: 'fa-moon' }
    ];

    const currentFreq = klineData.freq;
    freqMap.forEach(({ el, value, icon }) => {
        if (!el) return;
        const isActive = currentFreq === value;
        const colorClass = isActive ? 'metric-dark' : 'metric-grey';
        el.innerHTML = `<i class="${colorClass} fas ${icon}"></i>`;
    });

    // 显示参数栏
    paramBar.classList.remove('d-none');
}

function updateKlineMetrics(index) {
    const ohlc = klineData.ohlc;
    // 基础数据不存在或索引越界，直接退出
    if (!ohlc || index < 0 || index >= ohlc.length) return;
    const { ma, mv, tp, up, av, lw, fl } = klineData;
    // 封装安全取值：数组存在 + 索引合法 + 值存在
    const getVal = (arr, idx) => arr && idx < arr.length ? arr[idx][1] : undefined;
    // 安全设置元素文本
    const setText = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };

    // 收盘价、涨跌幅来自基础数据
    setText('klineClose', ohlc[index][4] ?? '--');
    setText('klinePercent', (ohlc[index][5] ?? '--') + '%');
    setText('klineMa', getVal(ma, index) ?? '--');
    setText('klineMv', getVal(mv, index) ? (getVal(mv, index) / 10000).toFixed(0) + 'W' : '--');
    setText('klineTp', getVal(tp, index) ?? '--');
    setText('klineUp', getVal(up, index) ?? '--');
    setText('klineAv', getVal(av, index) ?? '--');
    setText('klineLw', getVal(lw, index) ?? '--');
    setText('klineFl', getVal(fl, index) ?? '--');
}

/**
 * 二分查找左匹配，找数组中第0列第一个 >= target 的索引，找不到返回数组长度
 */
function firstSatisfyIndex(arr, target) {
    let left = 0;
    let right = arr.length;
    while (left < right) {
        const mid = Math.floor((left + right) / 2);
        if (arr[mid][0] >= target) {
            right = mid;
        } else {
            left = mid + 1;
        }
    }
    return left < arr.length ? left : arr.length - 1;
}

/**
 * @param {Array} ohlc K线数据
 * @param {Array} volume 成交量数据
 * @param {String} freq 周期 D/W/M
 * @param {Number} deadline 截止时间戳，-1 表示取最后一根
 * @returns {Object} { show_std, show_max, show_min, ohlc, volume, deadline }
 */
function calcShowValues(ohlc, volume, freq, deadline = -1) {
    const width = window.innerWidth;
    const count = volume.length;
    // 周期对应的毫秒增量
    const dayMs = 86400000;
    const increment = freq === 'W' ? dayMs * 7 
                    : freq === 'M' ? dayMs * 30 
                    : dayMs;
    // 根据宽度断点选择对应密度配置
    const density = width >= BREAKPOINT_FOR_KLINE ? KLINE_DENSITY.desktop : KLINE_DENSITY.mobile;
    // 计算各档位显示的K线根数
    const countStd = Math.round(width * density.std / 100);
    const countMax = Math.round(width * density.max / 100);
    const countMin = Math.round(width * density.min / 100);
    let indexDdl;
    // K线数量不足时，在末尾补空白占位
    if (count < countStd) {
        const missing = countStd - count;
        const lastTs = volume[count - 1][0];
        for (let i = 1; i <= missing; i++) {
            const ts = lastTs + i * increment;
            // 用 null 占位，Highcharts 不会渲染价格为 0 的假K线
            ohlc.push([ts, null, null, null, null, null]);
            volume.push([ts, 0]);
        }
        indexDdl = volume.length - 1;
    } else {
        indexDdl = deadline === -1 
            ? volume.length - 1 
            : firstSatisfyIndex(volume, deadline);
    }
    // 计算各档位的边界索引
    const indexStd = Math.min(Math.max(indexDdl, countStd - 1), volume.length - 1);
    const indexMax = Math.min(Math.max(indexDdl, countMax - 1), volume.length - 1);
    const indexMin = Math.min(Math.max(indexDdl, countMin - 1), volume.length - 1);
    // 计算各档位对应的自然天数跨度
    const showStd = Math.floor((volume[indexStd][0] - volume[Math.max(indexStd - countStd + 1, 0)][0]) / dayMs);
    const showMax = Math.floor((volume[indexMax][0] - volume[Math.max(indexMax - countMax + 1, 0)][0]) / dayMs);
    const showMin = Math.floor((volume[indexMin][0] - volume[Math.max(indexMin - countMin + 1, 0)][0]) / dayMs);
    const finalDeadline = volume[indexStd][0];
    return { show_std: showStd, show_max: showMax, show_min: showMin, ohlc, volume, deadline: finalDeadline };
}