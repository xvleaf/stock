import { trendChart, initTrendChart, renderTrendParamBar, destroyTrendChart, clearTrendTimer } from './trend.js';
import { klineChart, initKlineChart, destroyKlineChart, refreshKlineDensity } from './kline.js';

// ========== 公共全局状态变量 ==========
let isFullscreen = false;   // 记录当前是否处于伪全屏状态
export const Highcharts = window.Highcharts;
export const chartPageContainer = document.getElementById('chartPageContainer');
export let pageConfig = {};
export let priceDecimal = 2;

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

export function setPriceDecimal(val) {
    priceDecimal = Number(val) || 2;
}

export function setPageConfig(config) {
    pageConfig = config;
}

/** 页面入口初始化 */
export function initChartPage() {
    loadChartPage('view', pageConfig.view);
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
        }, 500); // 防抖延迟
    });
}

/** 加载图表页面 */
export async function loadChartPage(func, value) {
    try {            
        const res = await postRequest('/chart/view', {
            func: func,
            value: value,
            site: pageConfig.site,
            code: pageConfig.code,
            name: pageConfig.name,
            market: pageConfig.market,
            cat: pageConfig.cat
        });

        if (res && res.html) {
            destroyChart();
            clearTrendTimer();

            const container = document.getElementById('chartPageContainer');
            container.innerHTML = res.html;
            container.classList.remove('d-none');
            setPageConfig(res.chart);

            // 根据视图初始化图表
            if (pageConfig.view === 'kline') {
                initKlineChart();
            } else {
                initTrendChart();
                
                // 监听 chartLoaded 事件
                window.addEventListener('chartLoaded', (e) => {
                    // 仅当当前站点为 /focus/view 且图表加载完成时绑定
                    if (e.detail && e.detail.site === '/focus/view') {
                        const editBtn = document.getElementById('editBtn');
                        if (!editBtn || editBtn.dataset.bound) return;  
                        editBtn.dataset.bound = 'true';
                        editBtn.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const saveBtn = document.getElementById('saveBtn');
                            const isEditing = !saveBtn?.classList.contains('d-none');
                            editAction(!isEditing);
                        });
                    }
                });
            }        
            // 恢复全屏状态（如果之前是全屏）
            restoreFullscreen();
        }
    } catch (error) {
        console.error('图表加载失败:', error);
        showChartError(`图表加载失败：${error.message}`);
    }
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

/* 隐藏占位层，显示图表 */
export function hideChartPlaceholder() {
    const placeholderId = 'chartPlaceholder';
    const placeholder = document.getElementById(placeholderId);
    if (placeholder) {
        placeholder.style.display = 'none';
    }
}

/**
 * 初始化页面所有UI元素
 */
export function initPageElements() {
    const nameItem = document.getElementById('nameItem');
    const codeItem = document.getElementById('codeItem');
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
    
    const fullScreen = document.getElementById('fullScreen');
    if (fullScreen) {
        fullScreen.onclick = toggleFullScreen;
    }

    if (pageConfig.navi.showNavi) {
        naviContainer.classList.remove('d-none');
        const naviPrevItem = document.getElementById('naviPrevItem');
        const naviNextItem = document.getElementById('naviNextItem');
        initNavItemState('naviPrev', naviPrevItem);
        initNavItemState('naviNext', naviNextItem);
        
        if (pageConfig.navi.showPilot) {            
            const pilotPrevItem = document.getElementById('pilotPrevItem');
            const pilotNextItem = document.getElementById('pilotNextItem');
            pilotPrevItem.classList.remove('d-none');
            pilotNextItem.classList.remove('d-none');
            initNavItemState('pilotPrev', pilotPrevItem);
            initNavItemState('pilotNext', pilotNextItem);
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

function initNavItemState(key, navItem) {
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
    if (!chartPage) return;

    const isFull = chartPage.classList.contains('pseudo-fullscreen');

    if (isFull) {
        // 退出伪全屏
        chartPage.classList.remove('pseudo-fullscreen');
        document.body.classList.remove('pseudo-fullscreen-open');
        if (fullscreenBtn) fullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
        isFullscreen = false;
    } else {
        // 进入伪全屏
        chartPage.classList.add('pseudo-fullscreen');
        document.body.classList.add('pseudo-fullscreen-open');
        if (fullscreenBtn) fullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>';
        isFullscreen = true;
    }
    
    // 延迟执行图表自适应
    setTimeout(() => {
        if (pageConfig.view === 'kline') {
            if (klineChart && typeof klineChart.reflow === 'function') {
                klineChart.reflow();
            }
            // 刷新密度
            refreshKlineDensity();
        } else if (pageConfig.view === 'trend') {
            if (trendChart && typeof trendChart.reflow === 'function') {
                trendChart.reflow();
            }
        }
    }, 500);
}

function restoreFullscreen() {
    if (!isFullscreen) return;
    const chartPage = document.getElementById('chartPage');
    const fullscreenBtn = document.getElementById('fullScreen');
    if (!chartPage) return;

    // 应用全屏类
    chartPage.classList.add('pseudo-fullscreen');
    document.body.classList.add('pseudo-fullscreen-open');

    // 更新按钮图标
    if (fullscreenBtn) {
        fullscreenBtn.innerHTML = '<i class="fas fa-compress"></i>';
    }

    // 重新触发图表自适应
    setTimeout(() => {
        if (pageConfig.view === 'kline') {
            if (klineChart && typeof klineChart.reflow === 'function') {
                klineChart.reflow();
            }
            // 刷新密度
            refreshKlineDensity();
        } else if (pageConfig.view === 'trend') {
            if (trendChart && typeof trendChart.reflow === 'function') {
                trendChart.reflow();
            }
        }
    }, 500);
}

function naviSwitch(type, action) {
    postRequest(`/chart/view`, {
        func: type,
        value: action,
        site: pageConfig.site,
        code: pageConfig.code,
        market: pageConfig.market,
        cat: pageConfig.cat
    }).then(res => {
        if (res) {
            saveScrollPosition();
            window.location.href = `${res.site}/${res.market}/${res.code}`;
        }
    });
};

function viewModeChange() {
    pageConfig.view = pageConfig.view === 'kline' ? 'trend' : 'kline';
    loadChartPage('view', pageConfig.view); 
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
        '/': '/focus/list',
        '/trans/view': '/trans/list',
        '/review/focus/view': '/review/focus/list',
        '/review/trans/view': '/review/trans/list'
    };
    window.location.href = routeMap[pageConfig.site] || '/focus/list';
};

export function editAction(enable) {
    const form = document.getElementById('focusForm');
    const editFieldIds = [
        'id_focus_date', 
        'id_plan_price', 
        'id_plan_qty', 
        'id_target_price', 
        'id_stop_price',
        'id_comments'
    ];
    const inputs = form.querySelectorAll('input, textarea');
    const trendParam = document.getElementById('trendParam');
    const saveBtn = document.getElementById('saveBtn');
    const cancelBtn = document.getElementById('cancelEditBtn');

    inputs.forEach(input => {
        if (editFieldIds.includes(input.id)) {
            input.readOnly = !enable;
            // 进入编辑模式时，将日期设为今天
            if (enable && input.id === 'id_focus_date') {
                const today = new Date().toISOString().split('T')[0];
                input.value = today;
            }
        } else {
            input.readOnly = true;
        }
    }); 

    trendParam?.classList.toggle('d-none', enable);
    saveBtn?.classList.toggle('d-none', !enable);
    cancelBtn?.classList.toggle('d-none', !enable);  
    cancelBtn?.addEventListener('click', () => window.location.reload());
}

window.exitAction = function (marketCode) {
    const msg = pageConfig.site === '/focus/view' ? '确定要结束关注吗？' : '确定要取消添加吗？';
    layer.confirm(msg, {
        title: '确认', btnAlign: 'c', btn: ['确定', '取消'], shade: 0.5
    }, function () {
        if (pageConfig.site === '/focus/view') {
            postRequest(`/focus/edit/${marketCode}`, { func: 'end' }).then(res => {
                if (res.msg === 'done') window.location.href = '/focus/list';
            });
        } else {
            window.location.href = '/focus/list';
        }
    });
};

window.dealAction = function (marketCode) {
    window.location.href = `/trans/deal/${marketCode}`;
};

// ==================== 内部工具函数 ====================

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