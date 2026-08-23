import { debounceLayout } from '../../base/js/base.js';
import { trendChart, initTrendChart, destroyTrendChart, renderTrendActionButtons, clearTrendTimer } from './trend.js';
import { klineChart, initKlineChart, destroyKlineChart, refreshKlineDensity } from './kline.js';

// ========== 全局依赖兼容层 ==========
export function getCsrfToken() {
    const cookie = document.cookie.split(';')
        .map(c => c.trim())
        .find(c => c.startsWith('csrftoken='));
    return cookie ? decodeURIComponent(cookie.split('=')[1]) : '';
}

export async function postRequest(url, data) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            console.error(`请求失败：${url}，状态码 ${response.status}`);
            return null;
        }
        return await response.json();
    } catch (err) {
        console.error('接口请求异常：', err);
        return null;
    }
}

// ---------- 行情刷新函数 ----------
export function refreshQuotes(url, tbody) {
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({}),
    })
        .then(res => res.json())
        .then(data => {
            if (!Array.isArray(data)) return;
            data.forEach(item => {
                const row = tbody.querySelector(`tr[data-code="${item.code}.${item.market}"]`);
                if (!row) return;
                const closeEl = document.getElementById(`close-${item.code}.${item.market}`);
                if (closeEl && item.close !== '--') closeEl.textContent = item.close.toFixed(item.deci);
                const changeEl = document.getElementById(`change-${item.code}.${item.market}`);
                if (changeEl && item.change !== '--') changeEl.textContent = item.change.toFixed(2);
            });
        })
        .catch(err => console.warn('行情刷新失败:', err));
}

export const layer = window.layer || {
    msg: () => {},
    confirm: (text, opts, okCb) => {
        if (confirm(String(text).replace(/<[^>]+>/g, ''))) okCb();
    },
    close: () => {}
};

// ========== 公共全局状态变量 ==========
export const Highcharts = window.Highcharts;
export const chartPageContainer = document.getElementById('chartPageContainer');
export let pageConfig = {};
export let priceDecimal = 2;
export function setPriceDecimal(val) {
    priceDecimal = Number(val) || 2;
}

/**
 * 页面入口初始化
 */
export function initChartPage(chartConfig) {
    pageConfig = chartConfig;
    loadChartPage();
    bindGlobalKeyboard();
    // 滚动收起交互
    initScrollFold(); 
    // 图表库检测
    if (!Highcharts || typeof Highcharts.stockChart !== 'function') {
        showChartError('图表库加载失败');
        return;
    }

    let resizeTimer = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            // 根据视图类型刷新图表
            if (pageConfig.view === 'kline') {
                refreshKlineDensity(); 
            } else if (pageConfig.view === 'trend') {
                // 分时图 reflow
                if (trendChart) {
                    trendChart.reflow();
                }
            }
        }, 200); // 防抖延迟
    });
}

export function showChartError(text) {
    const errText = document.getElementById('errorText');
    if (errText) {
        errText.textContent = text;
        errText.classList.remove('d-none');
    }
}

export function destroyChart() {
    if (klineChart) {
        destroyKlineChart();
    }
    
    if (trendChart) {        
        destroyTrendChart();
    }
}

async function loadChartPage(retryCount = 0, maxRetries = 3) {    
    const container = document.getElementById('chartPageContainer');   

    try {
        const response = await fetch(`/chart/view?view=${pageConfig.view}`);
        if (!response.ok) {
            showChartError(`加载失败：(${response.status})`);
        }
        
        const html = await response.text();
        
        // 如果内容为空，进行重试
        if (!html || html.trim() === '') {
            if (retryCount < maxRetries) {
                console.log(`数据为空，${retryCount + 1}秒后进行第 ${retryCount + 1} 次重试...`);
                await new Promise(resolve => setTimeout(resolve, (retryCount + 1) * 10000));
                return loadChartPage(retryCount + 1, maxRetries);
            } else {
                console.log(`尝试 ${maxRetries} 次后仍未收到数据`);
            }
        }

        destroyChart();

        // 成功接收到数据
        container.innerHTML = html;
        container.classList.remove('d-none');

        initPageElements();

        if (pageConfig.view === 'kline') {
            initKlineChart();
        } else {
            initTrendChart();
        }
    } catch (error) {
        showChartError(`图表加载失败：${error.message}`);
    }
}

/* 隐藏占位层，显示图表 */
export function hideChartPlaceholder() {
    const placeholderId = pageConfig.view === 'trend' ? 'trendPlaceholder' : 'klinePlaceholder';
    const placeholder = document.getElementById(placeholderId);
    if (placeholder) {
        placeholder.style.display = 'none';
    }
}

/**
 * 初始化页面所有UI元素
 */
function initPageElements() {
    const nameItem = document.getElementById('nameItem');
    const codeItem = document.getElementById('codeItem');
    const fullScreen = document.getElementById('fullScreen');
    const naviContainer = document.getElementById('naviContainer');

    if (nameItem) {
        nameItem.textContent = pageConfig.name;
        nameItem.onclick = viewModeChange;
    }
    if (codeItem) {
        codeItem.textContent = pageConfig.code;
        if (pageConfig.cat === "stock") {
            codeItem.classList.add("pointer")
            codeItem.onclick = jumpToLink;
        }
    }
    
    if (fullScreen) {
        fullScreen.onclick = toggleFullScreen;
    }

    if (pageConfig.navi.showNavi) {
        naviContainer.classList.remove('d-none');
        const naviPrevItem = document.getElementById('naviPrevItem');
        const naviNextItem = document.getElementById('naviNextItem');
        updateNavItemState('naviPrev', naviPrevItem);
        updateNavItemState('naviNext', naviNextItem);
        
        if (pageConfig.navi.showPilot) {            
            const pilotPrevItem = document.getElementById('pilotPrevItem');
            const pilotNextItem = document.getElementById('pilotNextItem');
            pilotPrevItem.classList.remove('d-none');
            pilotNextItem.classList.remove('d-none');
            updateNavItemState('pilotPrev', pilotPrevItem);
            updateNavItemState('pilotNext', pilotNextItem);
        }

        if (pageConfig.navi.backList) {
            const backList = document.getElementById('backList');
            backList.classList.remove('d-none');
            backList.onclick = backToList;
        }

        const indicator = document.getElementById('naviIndicator');
        if (indicator) {
            const idx = parseInt(pageConfig.navi.naviIndex) + 1;
            const total = parseInt(pageConfig.navi.naviCount);
            indicator.textContent = total > 1 ? `(${idx}/${total})` : '';
        }
    }
}

// ==================== 全局交互函数 ====================
function updateNavItemState(key, navItem) {
    const enabled = !!pageConfig.navi[key];

    // 更新样式（互斥切换）
    navItem.classList.toggle('pointer', enabled);
    navItem.classList.toggle('is-disabled', !enabled);

    function bindNavClick() {
        // 根据 navItem 确定 type 和 action
        let type, action;
        if (navItem === naviPrevItem) {
            type = 'navi';
            action = 'prev';
        } else if (navItem === naviNextItem) {
            type = 'navi';
            action = 'next';
        } else if (navItem === pilotPrevItem) {
            type = 'pilot';
            action = 'prev';
        } else {
            type = 'pilot';
            action = 'next';
        }
        naviSwitch(type, action);
    }

    navItem.onclick = enabled ? bindNavClick: null;
}

function bindGlobalKeyboard() {
    document.addEventListener('keydown', (e) => {
        const active = document.activeElement;
        if (active.isContentEditable) return;
        switch (e.key) {
            case 'ArrowUp':
                if (pageConfig.showPilot && pageConfig.pilotPrev) {
                    naviSwitch('pilot', 'prev');
                    e.preventDefault();
                }
                break;
            case 'ArrowDown':
                if (pageConfig.showPilot && pageConfig.pilotNext) {
                    naviSwitch('pilot', 'next');
                    e.preventDefault();
                }
                break;
            case 'ArrowLeft':
                if (pageConfig.navi && pageConfig.naviPrev) {
                    naviSwitch('navi', 'prev');
                    e.preventDefault();
                }
                break;
            case 'ArrowRight':
                if (pageConfig.navi && pageConfig.naviNext) {
                    naviSwitch('navi', 'next');
                    e.preventDefault();
                }
                break;
            case 'm': changeFreq('M'); break;
            case 'w': changeFreq('W'); break;
            case 'd': changeFreq('D'); break;
            case 'f': toggleFullscreen(); break;
            case 'r': toggleRight(); break;
        }
    });
}

function toggleFullScreen() {
    const chartPage = document.getElementById('chartPage');    
    const fullscreenBtn = document.getElementById('fullScreen');
    const isFull = chartPage.classList.contains('pseudo-fullscreen');

    if (isFull) {
        // 退出伪全屏
        chartPage.classList.remove('pseudo-fullscreen');
        document.body.classList.remove('pseudo-fullscreen-open');
        fullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
    } else {
        // 进入伪全屏
        chartPage.classList.add('pseudo-fullscreen');
        document.body.classList.add('pseudo-fullscreen-open');
        fullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>' 
    }
    
    // 延迟执行，等待 DOM 布局稳定
    setTimeout(() => {
        // 先尝试用 reflow 自适应
        if (klineChart && typeof klineChart.reflow === 'function') {
            klineChart.reflow();
        }
        // 如果视图是 K 线，则重新计算密度并重建图表
        if (pageConfig.view === 'kline') {
            refreshKlineDensity();
        }
    }, 200); // 适当增加延迟，确保容器尺寸已更新
};

function naviSwitch(type, action) {
    postRequest(`/${pageConfig.site}`, {
        func: type,
        value: action,
        code: pageConfig.code,
        market: pageConfig.market,
        // cat: pageConfig.cat
    }).then(res => {
        if (res) {
            saveScrollPosition();
            window.location.href = `/${pageConfig.site}/${res.market}/${res.code}`;
        }
    });
};

function viewModeChange() {
    pageConfig.view = pageConfig.view === 'kline' ? 'trend' : 'kline';
    reloadChartView('view', pageConfig.view); 
};

function jumpToLink() {
    /** 
    localStorage.setItem('link_code', `${cat},${market},${code}`);
    const url = cat === 'stock'
        ? `/link/sector/list?code=${market}.${code}`
        : `/link/stock/list?code=${code}`;
    window.location.href = url;
    */
   console.log(pageConfig.code);
};

function backToList() {
    const routeMap = {
        'focus/view': '/focus/list',
        'trans/view': '/trans/list',
        'review/focus/view': '/review/focus/list',
        'review/trans/view': '/review/trans/list'
    };
    window.location.href = routeMap[pageConfig.site] || '/focus/list';
};

window.exitAction = function (marketCode) {
    const msg = pageConfig.site === 'focus/view' ? '确定要结束关注吗？' : '确定要取消添加吗？';
    layer.confirm(msg, {
        title: '确认', btnAlign: 'c', btn: ['确定', '取消'], shade: 0.5
    }, function () {
        if (pageConfig.site === 'focus/view') {
            postRequest(`/focus/edit/${marketCode}`, { func: 'end' }).then(res => {
                if (res.msg === 'done') window.location.href = '/focus/list';
            });
        } else {
            window.location.href = '/focus/list';
        }
    });
};

window.editAction = function (marketCode) {
    const routeMap = {
        'focus/view': `/focus/edit/${marketCode}`,
        'focus/plus': `/focus/view/${marketCode}`,
        'trans/view': `/trans/divd/${marketCode}`
    };
    const url = routeMap[pageConfig.site] || `/focus/plus?code=${marketCode}`;
    window.location.href = url;
};

window.dealAction = function (marketCode) {
    window.location.href = `/trans/deal/${marketCode}`;
};

// ==================== 内部工具函数 ====================
export function reloadChartView(func, value) {
    clearTrendTimer();
    postRequest('/chart/view', {
        func: func,
        value: value,
        code: pageConfig.code,
        market: pageConfig.market,
        // cat: pageConfig.cat
    }).then(html => {
        document.getElementById('chartPageContainer').innerHTML = html;
        loadChartPage();
    });
}

function saveScrollPosition() {
    const scrollTop = document.querySelector('.base-root')?.scrollTop || 0;
    localStorage.setItem('chart_scroll', scrollTop);
}

// 滚动防抖
function debounce(fn, delay = 16) {
    let timer = null;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// 滚动监听：上滑隐藏，下滑显示
let lastScrollTop = 0;
function initScrollFold() {
    const trendCanvas = document.querySelector('.chart-trend-canvas');
    const klineParam = document.querySelector('.chart-param');
    
    const handleScroll = debounce(() => {
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const isFold = scrollTop > lastScrollTop && scrollTop > 60;
        // 同步切换收起状态
        trendCanvas?.classList.toggle('is-fold', isFold);
        klineParam?.classList.toggle('is-fold', isFold);
        // 图表自适应重绘（可选，高度变化后让Highcharts重新适配）
        if (window.Highcharts) {
            const chart = Highcharts.charts.find(c => c);
            chart?.reflow();
        }
        lastScrollTop = scrollTop <= 0 ? 0 : scrollTop;
    });
    window.addEventListener('scroll', handleScroll, { passive: true });
}