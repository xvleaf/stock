import { Highcharts, initPageElements, hideChartPlaceholder, loadChartPage, pageConfig, setPageConfig } from './chart.js';
import { postRequest, priceDecimal, setPriceDecimal,showChartError } from './utils.js';

// ========== K线图全局状态变量 ==========
export let klineChart = null;
let klineData = {};

// ==================== K线图逻辑 ====================
export function initKlineChart() {    
    // 全局配置隐藏图表时，不加载数据、不渲染
    if (window.UI_CONFIG && window.UI_CONFIG.stock_chart_visible === false) {
        return;
    }
    fetchKlineData('get-kline-data')
        .then(data => {
            if (!data) {
                showChartError('K线数据加载失败');
                return;
            }

            klineData = data;
            renderklineData();
            hideChartPlaceholder();
            renderKlineParamBar();
            
            const initIdx = firstSatisfyIndex(klineData.volume, klineData.deadline);
            renderKlineMetrics(initIdx);
        })
        .catch(error => {
            console.error('initKlineChart 初始化异常:', error);
            showChartError('K线数据加载失败');
        });
}

// ---- 销毁 klineChart 实例 ----
export function destroyKlineChart() {
    if (klineChart) {
        klineChart.destroy();
        klineChart = null;
    }    
    // 清空数据，防止后续 refreshKlineDensity 误判
    klineData = {};
}

// 返回当前视图最后一根K线对应的 EMA 中轨值（av），无数据返回 null
export function getCurrentEma() {
    const av = klineData && klineData.av;
    if (!av || !av.length) return null;
    for (let i = av.length - 1; i >= 0; i--) {
        const p = av[i];
        if (p == null) continue;
        // Highstock 点为 [时间戳, 值] 二元数组，取数值位
        return Array.isArray(p) ? p[1] : p;
    }
    return null;
}

export function refreshKlineDensity() {
    if (!klineData || Object.keys(klineData).length === 0) {
        return;
    }
    if (klineChart) {
        klineChart.destroy();
        klineChart = null;
    }
    // 重新调用渲染
    renderklineData();
}

async function fetchKlineData(func) {
    const { site, code, market, cat } = pageConfig; // 解构赋值
    
    if (!code || !market) {
        console.warn('fetchChartData: 参数缺失 code 或 market');
        return false;
    }
    
    try {
        const data = await postRequest('/chart/data', {
            site,
            func,
            code,
            market,
            cat,
        });
        
        // 如果接口返回了数据（即使是空数组也视为成功，但 null/undefined 视为失败）
        return data ?? false; 
    } catch (error) {
        console.error('fetchChartData 请求异常:', error);
        return false;
    }
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

/**
 * 交易标记（点+线段+BSD图标 一体组合）HTML 覆盖层渲染。
 * 背景：Highcharts 10.3.3 的 useHTML 校验（warning #33）拒绝非白名单标签
 *   （iconify-icon 自定义标签 / 内联 svg / img 均被拒），dataLabels 无法显示图标。
 * 方案：每个交易标记生成一个绝对定位的 flex 容器（覆盖层内，z-index:2 < tooltip 3），
 *   内部纵向排列 圆点(6px)+线段(5px)+六边形图标(14px)，align-items:center →
 *   三者中心线天然共线，不再有两套渲染器的对齐问题。
 *   容器锚点 = 圆点中心 = 交易点像素 (px,py)，一次 Axis.toPixels() 定位。
 * 结构：
 *   买入（点在K线低点，图标在点下方）：点 → 线段 → 六边形B
 *   卖出/纯分红（点在K线高点，图标在点上方）：六边形S/D → 线段 → 点（镜像）
 *   同日卖出+分红：六边形D 紧挨 六边形S 上方（D蓝、S绿）→ 线段 → 点（不再用星号）
 * 颜色：买入红 #ef4444 / 卖出绿 #22c55e / 分红蓝 #3b82f6（点、线、图标同色）
 * 每次 chart render 事件触发（缩放/密度变化/resize 均触发），自动同步定位。
 */
function renderDealOverlay(chart, deal) {
    if (!chart || !deal) return;
    const container = chart.container;
    let overlay = container.querySelector('#deal-icon-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'deal-icon-overlay';
        overlay.style.cssText = 'position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:2;';
        container.appendChild(overlay);
    }
    overlay.innerHTML = '';
    // 组合内三个部件的 HTML（flex 纵向排列，align-items:center → 中心线天然共线）
    const dotHtml = function (color) {
        return '<div style="width:6px;height:6px;border-radius:50%;background:' + color + ';border:1px solid #fff;box-sizing:border-box;"></div>';
    };
    const lineHtml = function (color) {
        return '<div style="width:1px;height:5px;background:' + color + ';"></div>';
    };
    const iconHtml = function (icon, color) {
        return '<iconify-icon icon="' + icon + '" style="display:block;width:14px;height:14px;color:' + color + ';"></iconify-icon>';
    };
    // 三类标记；divd 需按是否同日卖出+分红走不同分支
    const groups = [
        { data: deal.buy,  icon: 'tabler:hexagon-letter-b', color: '#ef4444' },
        { data: deal.sell, icon: 'tabler:hexagon-letter-s', color: '#22c55e' },
        { data: deal.divd, icon: 'tabler:hexagon-letter-d', color: '#3b82f6' }
    ];
    groups.forEach(function (g) {
        if (!g.data || g.data.length === 0) return;
        g.data.forEach(function (d) {
            // 像素坐标（相对图表容器，含轴区域；与覆盖层 inset:0 对齐）
            const px = chart.xAxis[0].toPixels(d.x);
            const py = chart.yAxis[0].toPixels(d.y);
            if (px == null || py == null || isNaN(px) || isNaN(py)) return;
            let content, top;
            if (g.data === deal.buy) {
                // 买入：点在上（锚点=点中心=py），线段、B图标在点下方
                content = dotHtml(g.color) + lineHtml(g.color) + iconHtml(g.icon, g.color);
                top = py - 3;
            } else if (g.data === deal.divd && d.icon && d.icon.indexOf('asterisk') !== -1) {
                // 同日卖出+分红：D(蓝)紧挨S(绿)上方，点/线段用卖出绿；总高39，锚点=点中心
                content = iconHtml('tabler:hexagon-letter-d', '#3b82f6')
                    + iconHtml('tabler:hexagon-letter-s', '#22c55e')
                    + lineHtml('#22c55e')
                    + dotHtml('#22c55e');
                top = py - 36;
            } else {
                // 卖出 / 纯分红：图标在上，线段、点在下（锚点=点中心=py）
                content = iconHtml(g.icon, g.color) + lineHtml(g.color) + dotHtml(g.color);
                top = py - 22;
            }
            const el = document.createElement('div');
            el.style.cssText = 'position:absolute;left:' + px + 'px;top:' + top + 'px;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;';
            el.innerHTML = content;
            overlay.appendChild(el);
        });
    });
}

function renderklineData() {
    const { ohlc, volume, tp, fl, up, av, lw, ma, mv, deal, deadline: rawDeadline, deci, freq } = klineData;
    if (ohlc.length === 0) return;
    // 当前悬停的 candlestick 点（formatter 缓存，供 tooltip positioner 精确定位）
    let tipAnchor = null;
    // 前端计算显示区间，宽度与原请求参数保持一致
    const showResult = calcShowValues(
        [...ohlc], [...volume], freq, rawDeadline
    );
    const { show_min, show_std, show_max, deadline } = showResult;    
    const finalOhlc = showResult.ohlc;
    const finalVolume = showResult.volume;
    setPriceDecimal(deci);
    const mainRatio = window.UI_CONFIG ? window.UI_CONFIG.kline_main_ratio : 80;
    const subRatio = 100 - mainRatio;

    // 注入 tooltip 基础样式：
    // 背景/边框/圆角全部由 .kline-tip 自身承担，.highcharts-tooltip 容器透明无边框。
    // 【修改】已取消 tooltip 两侧小三角箭头：不再注入 .kline-tip::before 的
    // .kline-tip-left / .kline-tip-right 箭头 SVG 样式，同时移除仅服务于箭头
    // 绝对定位的 position:relative（.kline-tip 内为静态流内元素，无其他依赖）
    if (!document.getElementById('kline-tooltip-arrow-style')) {
        const st = document.createElement('style');
        st.id = 'kline-tooltip-arrow-style';
        st.textContent =
            '.highcharts-tooltip{overflow:visible!important;border:0!important;background:transparent!important;box-shadow:none!important;padding:0!important;}' +
            '.kline-tip{padding:10px 12px;background:#fff;border:1px solid #d9d9d9;border-radius:16px;}';
        document.head.appendChild(st);
    }

    Highcharts.setOptions({
        lang: { rangeSelectorZoom: '' },
        global: { useUTC: false, timezone: 'Asia/Shanghai' },
        accessibility: { enabled: false } // 禁用无障碍模块
    });
    
    klineChart = Highcharts.stockChart('chartContainer', {
        chart: {
            spacing: [0, 5, 0, 5],
            borderWidth: 0,
            plotBorderColor: '#cfd1ee',
            plotBorderWidth: 1,
            events: {
                render: function () {
                    // 任何重绘（reflow/resize/布局变化）后重置坐标缓存，
                    // 保证 pointer 的 chartPosition 始终与当前布局一致，
                    // 否则 tooltip 事件坐标换算偏移、悬停判定失败（tooltip 不显示）
                    this.pointer.chartPosition = undefined;
                    syncVolumeColor(this);
                    // 每次渲染/重绘后同步交易标记覆盖层（缩放、密度变化、resize 均触发 render）
                    renderDealOverlay(this, deal);
                }
            }
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
            { height: mainRatio + '%', resize: { enabled: true }, labels: { align: 'right', x: -3 } },
            { top: mainRatio + '%', height: subRatio + '%', offset: 0, labels: { align: 'right', x: -3 } }
        ],
        tooltip: {
            shared: true,
            split: false,
            animation: false,
            useHTML: true,
            outside: true, // 渲染到图表容器外：tooltip 可溢出绘制区（边缘蜡烛/三角），坐标用页面像素；层叠由覆盖层 z-index(2) < tooltip 容器(3) 保证
            shape: 'rect', // 主体由 .kline-tip 的 CSS 绘制；此处容器透明无边框
            borderWidth: 0, // 边框由 .kline-tip 承担
            backgroundColor: 'transparent', // 背景由 .kline-tip 承担
            shadow: false, // 阴影由 .kline-tip 自行控制
            padding: 0, // 内边距交给 .kline-tip 控制
            style: {
                fontSize: '13px'       // 全局字体大小
            },
            // tooltip 显示在当前K线的左侧或右侧（依据点在绘图区的位置），小三角指向该K线
            positioner: function (labelWidth, labelHeight, point) {
                const chart = this.chart;
                const plotLeft = chart.plotLeft, plotTop = chart.plotTop;
                const plotWidth = chart.plotWidth, plotHeight = chart.plotHeight;
                // 优先用 formatter 缓存的 candlestick 锚点（plotX/plotY 精确），未缓存时退回当前点
                let anchor = (tipAnchor && tipAnchor.series) ? tipAnchor : point;
                const plotX = anchor.plotX, plotY = anchor.plotY;
                // 用实际渲染的 tooltip 宽度修正 labelWidth（HTML 内容测量可能不准，导致右侧定位过远）
                let w = labelWidth;
                const tipEl = chart.tooltip && chart.tooltip.label && chart.tooltip.label.element;
                if (tipEl) {
                    const rw = tipEl.getBoundingClientRect().width;
                    if (rw > 0) w = rw;
                }
                const gap = 12;
                let vx; // 期望的 tooltip 位置（相对图表容器）
                // 点在左半区→提示框放右侧；点在右半区→放左侧
                if (plotX < plotWidth / 2) {
                    vx = plotLeft + plotX + gap;
                } else {
                    vx = plotLeft + plotX - w - gap;
                }
                // 垂直方向跟随K线并限制在绘图区内
                let vy = plotTop + (plotY || 0) - labelHeight / 2;
                vy = Math.max(plotTop, Math.min(vy, plotTop + plotHeight - labelHeight));
                // Highcharts outside:true 的位置链路（源码）：
                //   updatePosition: m.x += pointer.chartPosition.left - distance
                //   xSetter: label内部平移 distance；e.style.left = m.x（body 文档坐标）
                // 即 distance 在 updatePosition 减去、又在 xSetter 内部加回，互相抵消，
                // 最终 tooltip 视口位置 = positioner.x + 缓存chartPosition.left - 滚动偏移。
                // chartPosition 是首次测量即缓存的容器视口坐标，页面滚动/布局变化后可能过期、
                // 甚至为 0。因此用实时容器位置（getBoundingClientRect）反推返回值：
                //   positioner = 期望视口坐标 + 滚动偏移 - 缓存chartPosition
                // 使最终位置恒等于「期望视口坐标」，与缓存是否正确无关。
                const cRect = chart.container.getBoundingClientRect();
                const cp = chart.pointer && chart.pointer.chartPosition;
                const x = vx + cRect.left + (window.pageXOffset || 0) - ((cp && cp.left) || 0);
                const y = vy + cRect.top + (window.pageYOffset || 0) - ((cp && cp.top) || 0);
                return { x: x, y: y };
            },
            formatter: function () {
                // 防御性检查：某些情况下 this.points 可能不存在
                if (!this.points || this.points.length === 0) return '';
                // 找到K线系列（candlestick）的点，避免交易标记点导致报错
                const klinePointItem = this.points.find(p => p.series.type === 'candlestick');
                if (!klinePointItem) return '';
                const point = klinePointItem.point;
                tipAnchor = point; // 缓存当前K线锚点，供 positioner 精确定位
                renderKlineMetrics(point.index);
                const date = new Date(point.x);
                // 月份和日期补零，确保格式为 YYYY-MM-DD，与后端 d.date 一致
                const dateStr = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

                // 主动根据日期字符串查询交易标记（避免时间戳精度/时区不一致问题）
                let tradeHtml = '';
                const allTradeMarkers = [
                    { data: deal.buy, type: 'buy', color: '#ef4444', label: '买入' },
                    { data: deal.sell, type: 'sell', color: '#22c55e', label: '卖出' },
                    { data: deal.divd, type: 'divd', color: '#3b82f6', label: '分红' }
                ];
                const matchedMarkers = [];
                allTradeMarkers.forEach(tm => {
                    if (tm.data && tm.data.length > 0) {
                        // 用日期字符串比较，而非时间戳严格比较
                        const matched = tm.data.find(d => d.date === dateStr);
                        if (matched) {
                            matchedMarkers.push({ ...matched, _type: tm.type, _color: tm.color, _label: tm.label });
                        }
                    }
                });

                if (matchedMarkers.length > 0) {
                    tradeHtml = '<div style="border-top:1px solid #ddd;margin-top:6px;padding-top:6px;">';
                    matchedMarkers.forEach(p => {
                        const count = p.trades ? p.trades.length : 1;
                        tradeHtml += `<div style="font-weight:bold;color:${p._color};margin-bottom:4px;">${p._label}（共${count}笔）</div>`;

                        if (p.trades) {
                            p.trades.forEach(t => {
                                // 每笔交易显示实际交易日期（t.date）
                                if (p._type === 'buy') {
                                    tradeHtml += `<div>${t.date} 买入${t.qty}股@${Number(t.price).toFixed(klineData.deci)}元</div>`;
                                } else if (p._type === 'sell') {
                                    tradeHtml += `<div>${t.date} 卖出${t.qty}股@${Number(t.price).toFixed(klineData.deci)}元</div>`;
                                } else {
                                    // 分红格式：现金>0 显示"分红xx元，送股xx股"；现金=0 仅显示"送股xx股"
                                    const amountStr = Number(t.amount).toLocaleString('zh-CN', {minimumFractionDigits:2});
                                    const hasCash = Number(t.amount) > 0;
                                    const hasBonus = t.bonus_qty > 0;
                                    if (hasCash && hasBonus) {
                                        tradeHtml += `<div>${t.date} 分红${amountStr}元，送股${t.bonus_qty}股</div>`;
                                    } else if (hasCash) {
                                        tradeHtml += `<div>${t.date} 分红${amountStr}元</div>`;
                                    } else if (hasBonus) {
                                        tradeHtml += `<div>${t.date} 送股${t.bonus_qty}股</div>`;
                                    }
                                }
                            });
                        }

                        // 【修改】已取消交易标记的合计行（含其配套的虚线分隔线）：
                        // 仅保留每笔交易明细；「（共N笔）」标题所需的 count 变量仍保留使用
                    });
                    tradeHtml += '</div>';
                }

                return `
                    <div class="kline-tip">
                        <b>${dateStr}</b>
                        <table>
                            <tr>
                                <td>收盘 ${point.close.toFixed(priceDecimal)}</td>
                                <td style="padding-left:10px">开盘 ${point.open.toFixed(priceDecimal)}</td>
                            </tr>
                            <tr>
                                <td>最高 ${point.high.toFixed(priceDecimal)}</td>
                                <td style="padding-left:10px">最低 ${point.low.toFixed(priceDecimal)}</td>
                            </tr>
                            <tr>
                                <td>涨幅 ${klineData.ohlc[point.index][5]}%</td>
                                <td style="padding-left:10px">成交 ${(klineData.volume[point.index][1] / 10000).toFixed(0)}万</td>
                            </tr>
                        </table>
                        ${tradeHtml}
                    </div>
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
            { type: 'spline', data: mv, yAxis: 1, color: '#000', lineWidth: 1, enableMouseTracking: false }
            // 交易信号 buy/sell/divd 不再使用 scatter 系列：点+线段+图标由覆盖层 renderDealOverlay 一体渲染
        ]
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
    if (elements.k) {
        elements.k.textContent = klineData.k ?? '--';
        priceChannel('k', elements.k);
    }
    if (elements.d) {
        elements.d.textContent = klineData.d ?? '--';
        priceChannel('d', elements.d);
    }

    // 更新复权按钮（使用配置对象）
    if (elements.right) {
        const isQFQ = klineData.right === 'qfq'; 
        let icon = isQFQ?"tabler:repeat":"tabler:repeat-off"
        elements.right.onclick = toggleRight;
        elements.right.innerHTML = `<iconify-icon icon="${icon}" style="width:1em; height:1em;"></iconify-icon>`;
    }

    // 更新频率按钮（使用配置数组）
    const freqMap = [
        { el: elements.freqDay, value: 'D', icon: 'tabler:sun-filled' },
        { el: elements.freqWeek, value: 'W', icon: 'tabler:sparkles-2-filled' },
        { el: elements.freqMonth, value: 'M', icon: 'tabler:moon-filled' }
    ];

    const currentFreq = klineData.freq;
    freqMap.forEach(({ el, value, icon }) => {
        if (!el) return;
        
        const isActive = currentFreq === value;
        const colorClass = isActive ? '' : 'class="metric-grey"';
        el.addEventListener('click', (event) => changeFreq(value, event));
        el.classList.toggle('pointer', !isActive);
        el.classList.toggle('is-disabled', isActive);
        el.innerHTML = `<iconify-icon icon="${icon}" ${colorClass} style="width:1em; height:1em;"></iconify-icon>`;
    });

    // 初始化页面元素（按钮、导航等）
    initPageElements();

    // 显示参数栏
    paramBar.classList.remove('d-none');
}

function renderKlineMetrics(index) {
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

    const klineMetrics = document.getElementById('klineMetrics');
    if (klineMetrics) klineMetrics.classList.remove('d-none');
}

function priceChannel(key, el) {
    function getRawValue(element) {
        return element.textContent.trim();
    }

    function isValidNumber(str) {
        if (str === '') return false;
        const num = Number(str);
        // 只允许正数，'--' 会被转为 NaN
        return !isNaN(num) && num > 0;
    }

    // 获取初始内容，若非有效数字则强制设为 '-'
    let lastValidValue = getRawValue(el);
    if (!isValidNumber(lastValidValue)) {
        lastValidValue = '--';
        el.textContent = '--';
    }

    let blurTimer = null; // 定时器句柄

    el.addEventListener('blur', function() {
        // 清除之前的定时器，防止多次执行
        if (blurTimer) {
            clearTimeout(blurTimer);
            blurTimer = null;
        }

        // 延迟执行校验逻辑
        blurTimer = setTimeout(() => {
            const currentRaw = getRawValue(this);

            // 校验当前输入
            if (isValidNumber(currentRaw)) {
                // 有效数字：标准化（去除前导零）
                const normalized = Number(currentRaw).toString();
                this.textContent = normalized;

                // 判断是否发生了变化
                if (normalized !== lastValidValue) {                                    
                    let copyPageConfig = pageConfig;
                    copyPageConfig.kline[key] = normalized;
                    setPageConfig(copyPageConfig);
                    loadChartPage(key, normalized);
                    // 更新缓存为当前有效值
                    lastValidValue = normalized;
                }
            } else {
                // 无效输入：回退到上次有效值
                this.textContent = lastValidValue;
            }
            blurTimer = null; // 重置定时器句柄
        }, 500); // 延迟500毫秒
    });
}

export function toggleRight() {
    let copyPageConfig = pageConfig;
    let right = copyPageConfig.kline['right'];
    right = right === 'qfq' ? null : 'qfq';
    copyPageConfig.kline['right'] =right;
    setPageConfig(copyPageConfig);
    loadChartPage('right', right);
};

export function changeFreq(freq) {
    let copyPageConfig = pageConfig;
    copyPageConfig.kline['freq'] = freq;
    setPageConfig(copyPageConfig);
    loadChartPage('freq', freq);
};

//二分查找左匹配，找数组中第0列第一个 >= target 的索引，找不到返回数组长度
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

function calcShowValues(ohlc, volume, freq, deadline = -1) {
    // 使用父容器宽度，否则全屏时宽度不对
    const width = document.getElementById('chartContainer').clientWidth;
    const count = volume.length;
    // 周期对应的毫秒增量
    const dayMs = 86400000;
    const increment = freq === 'W' ? dayMs * 7 
                    : freq === 'M' ? dayMs * 30 
                    : dayMs;
    // 从 pageConfig 获取密度配置（不区分桌面/移动）
    const density = pageConfig.kline.density || { max: 20, std: 13, min: 5 };
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