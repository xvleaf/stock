import { trendChart, initTrendChart, destroyTrendChart, clearTrendTimer } from './trend.js';
import { klineChart, initKlineChart, destroyKlineChart, refreshKlineDensity } from './kline.js';
import { changeFreq as klineChangeFreq, toggleRight as klineToggleRight } from './kline.js';

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
    initScrollFold();

    // 监听浏览器后退/前进
    window.addEventListener('popstate', (event) => {
        if (event.state) {
            pageConfig.site = event.state.site;
            pageConfig.code = event.state.code;
            pageConfig.market = event.state.market;
            // 重新获取名称（可通过AJAX或从缓存，这里简单重新加载）
            // 为简化，我们请求后端获取名称再加载图表
            postRequest('/chart/view', {
                func: 'info', // 新增一个获取详情的功能
                site: pageConfig.site,
                code: pageConfig.code,
                market: pageConfig.market
            }).then(res => {
                if (res && res.name) {
                    pageConfig.name = res.name;
                    pageConfig.cat = res.cat || 'stock';
                    updatePageInfo(res);
                    loadChartPage('view', pageConfig.view);
                }
            });
        }
    });

    // resize 防抖
    let resizeTimer = null;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (pageConfig.view === 'kline') refreshKlineDensity();
            else if (pageConfig.view === 'trend' && trendChart) trendChart.reflow();
        }, 500);
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
            // 销毁旧图表
            destroyChart();
            clearTrendTimer();

            // 替换图表内容
            const container = document.getElementById('chartPageContainer');
            container.innerHTML = res.html;
            container.classList.remove('d-none');
            
            // 更新配置（保留名称、类别等）
            const newConfig = res.chart;

            if (pageConfig.name && !newConfig.name) newConfig.name = pageConfig.name;
            if (pageConfig.cat && !newConfig.cat) newConfig.cat = pageConfig.cat;
            setPageConfig(newConfig);

            // 立即应用全屏样式（从 localStorage 恢复）
            applyFullscreenState();

            // 等待下一帧确保样式已应用
            requestAnimationFrame(() => {
                // 再次强制回流（安全措施）
                const chartPage = document.getElementById('chartPage');
                if (chartPage) void chartPage.offsetHeight;

                if (pageConfig.view === 'kline') {
                    initKlineChart();
                } else {
                    initTrendChart();
                    // 仅当当前站点为 /focus/view 且图表加载完成时绑定
                    window.addEventListener('chartLoaded', (e) => {
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
            });
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


// 初始化页面所有UI元素
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
        console.log(pageConfig);
        if (pageConfig.mark.showMark) {
            const focusMark = document.getElementById('focusMark');
            const majorMark = document.getElementById('majorMark');
            const minorMark = document.getElementById('minorMark');
            const hideMark = document.getElementById('hideMark');

            if (pageConfig.mark.showFocus && focusMark) {
                const focusIcon = pageConfig.mark.focus === '1' ? 'tabler:current-location-filled': 'tabler:current-location';
                focusMark.innerHTML = `<iconify-icon icon="${focusIcon}" style="width:1em; height:1em;"></iconify-icon>`;
                focusMark.classList.remove('d-none');
                focusMark.onclick = focusAction;
            }
            if (majorMark) {
                const majorIcon = pageConfig.mark.status === '1' ? 'tabler:hexagon-number-1-filled': 'tabler:hexagon-number-1';
                majorMark.innerHTML = `<iconify-icon icon="${majorIcon}" style="width:1em; height:1em;"></iconify-icon>`;
                majorMark.classList.remove('d-none');
                majorMark.addEventListener('click', (event) => markAction('major', event));
            }
            if (minorMark) {
                const minorIcon = pageConfig.mark.status === '2' ? 'tabler:hexagon-number-2-filled': 'tabler:hexagon-number-2';
                minorMark.innerHTML = `<iconify-icon icon="${minorIcon}" style="width:1em; height:1em;"></iconify-icon>`;
                minorMark.classList.remove('d-none');
                minorMark.addEventListener('click', (event) => markAction('minor', event));
            }

            if (pageConfig.mark.showHide && hideMark) {
                const hideIcon = 'tabler:hexagon-minus';
                hideMark.innerHTML = `<iconify-icon icon="${hideIcon}" style="width:1em; height:1em;"></iconify-icon>`;
                hideMark.classList.remove('d-none');
                hideMark.onclick = hideAction;
            }
        }

        const backList = document.getElementById('backList');
        if (pageConfig.navi.backList && backList) {
            const backIcon = 'tabler:menu-2';
            backList.innerHTML = `<iconify-icon icon="${backIcon}" style="width:1em; height:1em;"></iconify-icon>`;
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
        // 如果焦点在输入框、文本域或可编辑元素中，不触发导航
        if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) {
            return;
        }

        const navi = pageConfig.navi || {};
        const isKline = pageConfig.view === 'kline';

        switch (e.key) {
            case 'ArrowUp':
                if (navi.showPilot && navi.pilotPrev) {
                    naviSwitch('pilot', 'prev');
                    e.preventDefault();
                }
                break;
            case 'ArrowDown':
                if (navi.showPilot && navi.pilotNext) {
                    naviSwitch('pilot', 'next');
                    e.preventDefault();
                }
                break;
            case 'ArrowLeft':
                if (navi.showNavi && navi.naviPrev) {
                    naviSwitch('navi', 'prev');
                    e.preventDefault();
                }
                break;
            case 'ArrowRight':
                if (navi.showNavi && navi.naviNext) {
                    naviSwitch('navi', 'next');
                    e.preventDefault();
                }
                break;
            case 'v':
                viewModeChange();
                e.preventDefault();
                break;
            case 'm':
                if (isKline && pageConfig.kline?.freq !== 'M') {
                    klineChangeFreq('M');
                    e.preventDefault();
                }
                break;
            case 'w':
                if (isKline && pageConfig.kline?.freq !== 'W') {
                    klineChangeFreq('W');
                    e.preventDefault();
                }
                break;
            case 'd':
                if (isKline && pageConfig.kline?.freq !== 'D') {
                    klineChangeFreq('D');
                    e.preventDefault();
                }
                break;
            case 'r':
                if (isKline) {
                    klineToggleRight();
                    e.preventDefault();
                }
                break;
            case 'f':
                toggleFullScreen();
                e.preventDefault();
                break;
            default:
                break;
        }
    });
}


function toggleFullScreen() {
    const chartPage = document.getElementById('chartPage');
    if (!chartPage) return;

    const newState = !chartPage.classList.contains('pseudo-fullscreen');
    localStorage.setItem('chartFullscreen', newState ? 'true' : 'false');
    applyFullscreenState();

    // 等待一帧，确保 CSS 尺寸生效
    requestAnimationFrame(() => {
        // 强制回流，确保布局更新
        void chartPage.offsetHeight;

        if (pageConfig.view === 'kline') {
            // 重新计算 K 线密度并刷新图表
            refreshKlineDensity();
        } else if (pageConfig.view === 'trend') {
            if (trendChart && typeof trendChart.reflow === 'function') {
                trendChart.reflow();
            }
        }
    });
}


function applyFullscreenState() {
    const stored = localStorage.getItem('chartFullscreen');
    const shouldFullscreen = stored === 'true';
    const chartPage = document.getElementById('chartPage');
    const fullscreenBtn = document.getElementById('fullScreen');

    if (chartPage) {
        chartPage.classList.toggle('pseudo-fullscreen', shouldFullscreen);
        document.body.classList.toggle('pseudo-fullscreen-open', shouldFullscreen);
        void chartPage.offsetHeight;
    }

    // 控制 trendParam 的显示模式
    const trendParam = document.getElementById('trendParam');
    if (trendParam) {
        trendParam.classList.toggle('fullscreen-mode', shouldFullscreen);
    }

    if (fullscreenBtn) {
        fullscreenBtn.innerHTML = shouldFullscreen
            ? '<iconify-icon icon="tabler:maximize-off" style="width:1em; height:1em;"></iconify-icon>'
            : '<iconify-icon icon="tabler:maximize" style="width:1em; height:1em;"></iconify-icon>';
    }

                
    isFullscreen = shouldFullscreen;
}


function naviSwitch(type, action) {
    postRequest('/chart/view', {
        func: type,
        value: action,
        site: pageConfig.site,
        code: pageConfig.code,
        market: pageConfig.market,
        cat: pageConfig.cat
    }).then(res => {
        if (res && res.code) {
            // 更新 pageConfig
            pageConfig.site = res.site || pageConfig.site;
            pageConfig.code = res.code;
            pageConfig.market = res.market;
            pageConfig.name = res.name || '';
            pageConfig.cat = res.cat || 'stock';

            // 更新浏览器地址栏
            const newUrl = `${pageConfig.site}/${pageConfig.market}/${pageConfig.code}`;
            history.pushState({ site: pageConfig.site, code: pageConfig.code, market: pageConfig.market }, '', newUrl);

            // 更新表单和标题（传入完整数据）
            updateFormData(res);

            // 重新加载图表（只更新图表容器）
            loadChartPage('view', pageConfig.view);
        }
    });
}


function updateFormData(data) {
    // 更新顶部名称和代码
    const nameItem = document.getElementById('nameItem');
    const codeItem = document.getElementById('codeItem');
    if (nameItem) nameItem.textContent = data.name || '';
    if (codeItem) codeItem.textContent = data.code || '';

    // 更新表单字段（所有可编辑字段）
    const fieldMap = {
        'id_code_input': 'code',
        'id_name_input': 'name',
        'id_focus_date': 'focus_date',
        'id_plan_price': 'plan_price',
        'id_plan_qty': 'plan_qty',
        'id_target_price': 'target_price',
        'id_stop_price': 'stop_price',
        'id_allowed_qty': 'allowed_qty',
        'id_win_ratio': 'win_ratio',
        'id_comments': 'comments',
    };

    for (const [id, key] of Object.entries(fieldMap)) {
        const el = document.getElementById(id);
        if (el && data[key] !== undefined) {
            el.value = data[key];
        }
    }

    // 市场选择/只读
    const marketSelect = document.querySelector('[name="market_choice"]');
    if (marketSelect) {
        if (marketSelect.tagName === 'SELECT') {
            marketSelect.value = data.market || 'SH';
        } else {
            marketSelect.value = data.market_display || '';
        }
    }
    const marketReadonly = document.getElementById('id_market_choice');
    if (marketReadonly && marketReadonly.readOnly) {
        marketReadonly.value = data.market_display || '';
    }

    // 类别选择/只读
    const catSelect = document.querySelector('[name="cat_choice"]');
    if (catSelect) {
        if (catSelect.tagName === 'SELECT') {
            catSelect.value = data.cat || 'stock';
        } else {
            catSelect.value = data.cat_display || '';
        }
    }
    const catReadonly = document.getElementById('id_cat_choice');
    if (catReadonly && catReadonly.readOnly) {
        catReadonly.value = data.cat_display || '';
    }

    // 交易方向（intent）
    const intentSelect = document.querySelector('[name="intent_choice"]');
    if (intentSelect) {
        if (intentSelect.tagName === 'SELECT') {
            intentSelect.value = data.intent || 'B';
        } else {
            // 只读模式，显示中文
            const intentDisplay = data.intent === 'B' ? '买入' : '卖出';
            intentSelect.value = intentDisplay;
        }
    }
    const intentReadonly = document.getElementById('id_intent_choice');
    if (intentReadonly && intentReadonly.readOnly) {
        const intentDisplay = data.intent === 'B' ? '买入' : '卖出';
        intentReadonly.value = intentDisplay;
    }
}


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
        '/sector/view': '/sector/list',
        '/': '/focus/list',
        '/trans/view': '/trans/list',
        '/review/focus/view': '/review/focus/list',
        '/review/trans/view': '/review/trans/list'
    };
    window.location.href = routeMap[pageConfig.site] || '/focus/list';
};

function focusAction() {
    console.log('focus');
}

function markAction(func) {
    const url = `${pageConfig.site}/${pageConfig.market}/${pageConfig.code}`;
    postRequest(url, {
        'func': func
    }).then(res => {
        if (res) {
            if (res.msg !== 'done') {
                console.log(res.msg);
                return;
            }

            pageConfig.mark.status = func === 'major' ? res.major : res.minor;
                
            const majorMark = document.getElementById('majorMark');
            const minorMark = document.getElementById('minorMark');
            const majorIcon = pageConfig.mark.status === '1' ? 'tabler:hexagon-number-1-filled': 'tabler:hexagon-number-1';
            const minorIcon = pageConfig.mark.status === '2' ? 'tabler:hexagon-number-2-filled': 'tabler:hexagon-number-2';
            majorMark.innerHTML = `<iconify-icon icon="${majorIcon}" style="width:1em; height:1em;"></iconify-icon>`;
            minorMark.innerHTML = `<iconify-icon icon="${minorIcon}" style="width:1em; height:1em;"></iconify-icon>`;
        }
    });





}

function hideAction() {
    console.log('hide');
}

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
    const handleScroll = debounce(() => {
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        // 图表自适应重绘（可选，高度变化后让Highcharts重新适配）
        if (window.Highcharts) {
            const chart = Highcharts.charts.find(c => c);
            chart?.reflow();
        }
        lastScrollTop = scrollTop <= 0 ? 0 : scrollTop;
    });
    window.addEventListener('scroll', handleScroll, { passive: true });
}