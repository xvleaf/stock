import { postRequest, updateFormData, initScrollFold, showChartError } from './func.js';
import { trendChart, initTrendChart, destroyTrendChart, clearTrendTimer } from './trend.js';
import { klineChart, initKlineChart, destroyKlineChart, refreshKlineDensity } from './kline.js';
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
            });
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
    const codeAct = pageConfig.cat == 'stock' || pageConfig.cat === 'SI' ? true : false;

    if (nameItem) {
        nameItem.textContent = pageConfig.name;
        if (nameAct) {
            nameItem.onclick = viewModeChange;
            nameItem.classList.add("pointer")
        }
    }
    if (codeItem) {
        codeItem.textContent = pageConfig.code;
        if (codeAct) {
            codeItem.classList.add("pointer")
            codeItem.onclick = jumpToLink;
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
            history.pushState({ 
                site: pageConfig.site, 
                code: pageConfig.code, 
                market: pageConfig.market,
                name: pageConfig.name,
                cat: pageConfig.cat
            }, '', newUrl);
            
            // 更新表单和标题（传入完整数据）
            updateFormData(res);

            // 如果响应包含 html，直接渲染
            if (res.html) {
                // 销毁旧图表和定时器
                destroyChart();
                clearTrendTimer();

                // 替换图表内容
                const container = document.getElementById('chartPageContainer');
                container.innerHTML = res.html;
                container.classList.remove('d-none');

                // 更新配置（合并新的 chart 配置）
                const newConfig = res.chart;
                setPageConfig(newConfig);

                // 应用全屏状态
                applyFullscreenState();

                // 等待下一帧初始化图表
                requestAnimationFrame(() => {
                    const chartPage = document.getElementById('chartPage');
                    if (chartPage) void chartPage.offsetHeight;

                    if (pageConfig.view === 'kline') {
                        initKlineChart();
                    } else {
                        initTrendChart();
                    }
                    // 重新初始化页面元素（导航按钮等）
                    initPageElements();
                });
                return;
            }
        }
    });
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
    // 一个漂亮的确认对话框
    Swal.fire({
    title: '确定要删除吗？',
    text: '此操作不可撤销！',
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#3085d6',
    cancelButtonColor: '#d33',
    confirmButtonText: '确认删除'
    }).then((result) => {
    if (result.isConfirmed) {
        console.log(pageConfig.cat);
        Swal.fire('已删除!', '文件已成功删除。', 'success');
    }
    });


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
            if (res.status !== 'success') {
                console.log(res.message);
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

    /**
    const url = `${pageConfig.site}/${pageConfig.market}/${pageConfig.code}`;
    postRequest(url, {
        'func': 'hide'
    }).then(res => {
        if (res) {
            if (res.status === 'success') {
                naviSwitch('navi', 'next');
            }
        }
    }); */
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
        
        Swal.fire({
            title: '关闭股票',
            width: 420,
            customClass: {
                popup: 'sweet-popup', 
                title: 'sweet-title'
            },
            html: `
                <div style="text-align: left;">
                    <label for="swal-close-date" class="form-label fs-6" style="font-weight:200;">时间：</label>
                    <input type="date" id="swal-close-date" class="form-control fs-6" value="${today}">

                    <label for="swal-close-comment" class="form-label fs-6" style="font-weight:200; margin-top:2px;">备注：</label>
                    <textarea id="swal-close-comment" class="form-control fs-6" style="resize: none;" rows="2"></textarea>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: '确认',
            cancelButtonText: '取消',
            confirmButtonColor: '#0d6efd',
            // cancelButtonColor: '#6c757d',
            preConfirm: () => {
                const closeDate = document.getElementById('swal-close-date').value;
                const comment = document.getElementById('swal-close-comment').value.trim();
                
                // 返回一个对象，在 then 中可接收
                return { closeDate, comment };
            }
        }).then((result) => {
            if (result.isConfirmed) {
                const { closeDate, comment } = result.value;
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
