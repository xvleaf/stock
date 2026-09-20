import { postRequest, updateFormData, initScrollFold, showChartError, showConfirm, showAlert, showFormModal } from './func.js';
import { trendChart, initTrendChart, destroyTrendChart, clearTrendTimer } from './trend.js';
import { klineChart, initKlineChart, destroyKlineChart, refreshKlineDensity, getCurrentEma } from './kline.js';
import { changeFreq as klineChangeFreq, toggleRight as klineToggleRight } from './kline.js';

export const Highcharts = window.Highcharts;
export const chartPageContainer = document.getElementById('chartPageContainer');
export let pageConfig = {};
export function setPageConfig(config) {pageConfig = config;}
let resizeTimer = null;

export function initChartPage() {
    loadChartPage('view', pageConfig.view);
    bindGlobalKeyboard();
    initScrollFold();

    // 点击图表区域时，若 k,d 等 contenteditable 输入框有焦点，主动失焦以触发参数更新
    document.addEventListener('click', (e) => {
        const active = document.activeElement;
        if (active && active.classList.contains('param-input') && !e.target.closest('.param-input')) {
            active.blur();
        }
    });

    // 监听浏览器后退/前进
    window.addEventListener('popstate', (event) => {
        if (event.state) {            
            pageConfig.site = event.state.site;
            pageConfig.code = event.state.code;
            pageConfig.name = event.state.name;
            pageConfig.market = event.state.market;
            pageConfig.cat = event.state.cat;
            // 重新加载图表（保持当前视图类型）
            loadChartPage('view', pageConfig.view);
        }
    });

    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (pageConfig.view === 'kline') {
                if (klineChart) {
                    refreshKlineDensity();
                }
            } else if (pageConfig.view === 'trend') {
                if (trendChart) {
                    trendChart.reflow();
                }
            }
        }, 500);
    });
}

/**
 * 共用的图表页面渲染函数：销毁旧图表、替换内容、更新配置、初始化图表和导航按钮
 * loadChartPage 和 naviSwitch 都调用此函数，消除重复代码
 */
function _renderChartPage(res) {
    destroyChart();
    clearTrendTimer();

    const container = document.getElementById('chartPageContainer');
    container.innerHTML = res.html;
    container.classList.remove('d-none');

    const newConfig = res.chart;
    setPageConfig(newConfig);

    applyFullscreenState();

    requestAnimationFrame(() => {
        const chartPage = document.getElementById('chartPage');
        if (chartPage) void chartPage.offsetHeight;

        if (pageConfig.view === 'kline') {
            initKlineChart();
        } else {
            initTrendChart();
            // focus/view 特有的编辑按钮绑定（仅绑定一次）
            if (!window._chartLoadedBound) {
                window._chartLoadedBound = true;
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
            if (pageConfig.site === '/focus/view') {
                exitEventListen();
            }
        }

        // 重新初始化页面元素（导航按钮事件绑定等）
        initPageElements();
    });
}

/**
 * 共用的股票操作请求函数：发送 POST 到当前股票的 view URL
 * focusAction、markAction、hideAction 等都调用此函数，消除重复的 URL 构建和 postRequest 调用
 */
function stockAction(func, extraData = {}) {
    const url = `${pageConfig.site}/${pageConfig.market}/${pageConfig.code}`;
    return postRequest(url, { 'func': func, ...extraData });
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
            // 共用渲染函数：销毁旧图表、替换内容、更新配置、初始化图表和导航按钮
            _renderChartPage(res);

            // 若加载的股票不在导航列表中（已被 hide 或不存在），自动返回来源列表
            // 覆盖场景：hide 后浏览器返回按钮(popstate)回退到已 hide 股票、直接 URL 访问已 hide 股票等
            if (pageConfig.navi && pageConfig.navi.showNavi === false && pageConfig.backUrl) {
                backToList();
                return;
            }

            // 若浏览器地址栏与当前股票不一致，同步历史记录（hide 后 loadChartPage 切换股票时需要）
            const expectedPath = `${pageConfig.site}/${pageConfig.market}/${pageConfig.code}`;
            if (window.location.pathname !== expectedPath) {
                history.pushState({
                    site: pageConfig.site,
                    code: pageConfig.code,
                    market: pageConfig.market,
                    name: pageConfig.name,
                    cat: pageConfig.cat
                }, '', expectedPath);
            }
        }
    } catch (error) {
        console.error('图表加载失败:', error);
        showChartError(`图表加载失败：${error.message}`);
    }
}


export function destroyChart() {
    if (klineChart) {
        destroyKlineChart();
    }
    if (trendChart) {
        destroyTrendChart();
    }
    clearTrendTimer();
    if (resizeTimer) {
        clearTimeout(resizeTimer);
        resizeTimer = null;
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
    const nameAct = pageConfig.cat == 'stock' ? true : false;

    if (nameItem) {
        nameItem.textContent = pageConfig.name;
        if (nameAct) {
            nameItem.onclick = viewModeChange;
            nameItem.classList.add("pointer")
        }
    }
    if (codeItem) {
        codeItem.textContent = pageConfig.code;
        // 板块 view：点击 code 进入该板块的股票清单
        if (pageConfig.site === '/sector/view') {
            codeItem.classList.add('pointer');
            codeItem.onclick = () => {
                window.location.href = `/stocks/list/${pageConfig.market}/${pageConfig.code}`;
            };
        }
    }
    
    const fullScreen = document.getElementById('fullScreen');
    if (fullScreen) {
        fullScreen.onclick = toggleFullScreen;
    }

    if (pageConfig.navi.showNavi) {
        const naviContainer = document.getElementById('naviContainer');
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

        if (pageConfig.mark.showMark) {
            renderMarkButtons();
        }

        const backList = document.getElementById('backList');
        if (pageConfig.navi.backList && backList) {
            backList.innerHTML = '<iconify-icon icon="tabler:menu-2" style="width:1em;height:1em;"></iconify-icon>';
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

// 本地重绘标记按钮（不发请求）
function renderMarkButtons() {
    const mk = pageConfig.mark || {};
    const focusMark = document.getElementById('focusMark');
    const majorMark = document.getElementById('majorMark');
    const minorMark = document.getElementById('minorMark');
    const hideMark = document.getElementById('hideMark');

    if (mk.showFocus && focusMark) {
        const on = mk.focus === 1 || mk.focus === '1';
        const icon = on ? 'tabler:current-location-filled' : 'tabler:current-location';
        focusMark.innerHTML = `<iconify-icon icon="${icon}" style="width:1em;height:1em;"></iconify-icon>`;
        focusMark.classList.remove('d-none');
        focusMark.onclick = focusAction;
    }
    if (majorMark) {
        const on = mk.status === '1';
        const icon = on ? 'tabler:hexagon-number-1-filled' : 'tabler:hexagon-number-1';
        majorMark.innerHTML = `<iconify-icon icon="${icon}" style="width:1em;height:1em;"></iconify-icon>`;
        majorMark.classList.remove('d-none');
        majorMark.onclick = () => markAction('major');
    }
    if (minorMark) {
        const on = mk.status === '2';
        const icon = on ? 'tabler:hexagon-number-2-filled' : 'tabler:hexagon-number-2';
        minorMark.innerHTML = `<iconify-icon icon="${icon}" style="width:1em;height:1em;"></iconify-icon>`;
        minorMark.classList.remove('d-none');
        minorMark.onclick = () => markAction('minor');
    }
    if (mk.showHide && hideMark) {
        hideMark.innerHTML = '<iconify-icon icon="tabler:hexagon-minus" style="width:1em;height:1em;"></iconify-icon>';
        hideMark.classList.remove('d-none');
        hideMark.onclick = hideAction;
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
            case '1':
                if (pageConfig.mark && pageConfig.mark.showMark) {
                    markAction('major');
                    e.preventDefault();
                }
                break;
            case '2':
                if (pageConfig.mark && pageConfig.mark.showMark) {
                    markAction('minor');
                    e.preventDefault();
                }
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
}

function naviSwitch(type, action) {
    return postRequest('/chart/view', {
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
            history.pushState({ 
                site: pageConfig.site, 
                code: pageConfig.code, 
                market: pageConfig.market,
                name: pageConfig.name,
                cat: pageConfig.cat
            }, '', newUrl);
            
            // 更新表单和标题（传入完整数据）
            updateFormData(res);

            // 如果响应包含 html，直接渲染（共用渲染函数）
            if (res.html) {
                _renderChartPage(res);
                return true;
            }
        }
        return false;
    });
}

function viewModeChange() {
    pageConfig.view = pageConfig.view === 'kline' ? 'trend' : 'kline';
    loadChartPage('view', pageConfig.view); 
};

function backToList() {
    // 优先用后端传入的来源列表页（记住进入 view 前的列表）
    if (pageConfig.backUrl) {
        window.location.href = pageConfig.backUrl;
        return;
    }
    const routeMap = {
        '/sector/view': '/sector/list',
        '/': '/focus/list',
        '/trans/view': '/trans/list',
        '/review/focus/view': '/review/focus/list',
        '/review/trans/view': '/review/trans/list',
        '/filter/view': '/filter/list',
        '/stocks/view': '/sector/list',
        '/refer/view': '/refer/list'
    };
    window.location.href = routeMap[pageConfig.site] || '/focus/list';
};

function focusAction() {
    const currentlyFocused = pageConfig.mark && (pageConfig.mark.focus === 1 || pageConfig.mark.focus === '1');
    const confirmText = currentlyFocused ? '确定要取消关注该股票吗？' : '确定要关注该股票吗？';
    showConfirm({
        title: currentlyFocused ? '取消关注' : '关注',
        text: confirmText,
        confirmText: '确定',
        cancelText: '取消',
    }).then((confirmed) => {
        if (!confirmed) return;
        const extraData = {};
        if (!currentlyFocused) {
            const ema = getCurrentEma();
            if (ema == null) {
                showAlert({ title: '错误', text: '未取到当前EMA值', type: 'error' });
                return;
            }
            extraData.ema_price = ema;
        }
        stockAction('focus', extraData).then(res => {
            if (res && res.status === 'success') {
                pageConfig.mark.focus = res.focus;
                renderMarkButtons();
                if (!currentlyFocused && res.plan) {
                    showAlert({ title: '已关注', text: `计划价 ${res.plan}，目标 ${res.target}，止损 ${res.stop}，数量 ${res.qty}`, type: 'success' });
                } else if (currentlyFocused) {
                    showAlert({ title: '已取消关注', text: res.message || '该股票已从关注列表中移除', type: 'info' });
                }
            }
        });
    });
}

function markAction(func) {
    stockAction(func).then(res => {
        if (!res || res.status !== 'success') {
            return;
        }
        // 本地更新标记态，直接重绘按钮，不再发第二次请求
        pageConfig.mark.status = (func === 'major') ? res.major : res.minor;
        renderMarkButtons();
    });
}

function hideAction() {
    showConfirm({
        title: '隐藏',
        text: '确定要隐藏该股票吗？',
        confirmText: '确定',
        cancelText: '取消',
    }).then((confirmed) => {
        if (!confirmed) return;
        stockAction('hide').then(res => {
            if (!res || res.status !== 'success') return;
            // hide 后不刷新页面：后端已在剔除前算好下一只（最后一只则前一只）
            // 直接用 loadChartPage 加载该股票，行为与点击 next 一致（AJAX 不刷新）
            const target = res.next || res.prev;
            if (target) {
                pageConfig.code = target.code;
                pageConfig.market = target.market;
                if (target.name) pageConfig.name = target.name;
                loadChartPage('view', pageConfig.view);
            } else {
                backToList(); // 列表为空
            }
        });
    });
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

function exitEventListen() {
    document.getElementById('exitBtn').addEventListener('click', function(e) {
        e.preventDefault();

        // 获取当前日期作为默认值（格式 YYYY-MM-DD）
        const today = new Date().toISOString().slice(0, 10);

        const formHtml = `
            <div class="text-start">
                <label for="bs-close-date" class="form-label mb-1">时间：</label>
                <input type="date" id="bs-close-date" class="form-control form-control-sm" value="${today}">
                <label for="bs-close-comment" class="form-label mb-1 mt-2">备注：</label>
                <textarea id="bs-close-comment" class="form-control form-control-sm" style="resize: none;" rows="2"></textarea>
            </div>`;

        showFormModal({
            title: '关闭股票',
            formHtml,
            confirmText: '确认',
            cancelText: '取消',
            onConfirm: (modalEl) => {
                const closeDate = modalEl.querySelector('#bs-close-date').value;
                const comment = modalEl.querySelector('#bs-close-comment').value.trim();
                return { closeDate, comment };
            },
        }).then((result) => {
            if (result) {
                const { closeDate, comment } = result;
                exitAction({
                    reason: 'manual',
                    comments: comment,
                    close_date: closeDate
                });
            }
        });
    });
}

function exitAction(data) {
    const url = `/focus/close/${pageConfig.market}/${pageConfig.code}`;
    const modal = bootstrap.Modal.getInstance(document.getElementById('closeConfirmModal'));
    postRequest(url, data)
    .then(data => {
        if (data.status === 'success') {
            document.getElementById('exitBtn').focus();
            if (modal) modal.hide();
            window.location.href = '/focus/list';
        } else {
            showChartError('关闭失败：' + (data.message || '未知错误'));
        }
    })
    .catch(error => {
        showChartError('请求失败：' + error);
    });
};

window.dealAction = function (marketCode) {
    window.location.href = `/trans/deal/${marketCode}`;
};
