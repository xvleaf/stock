// 表格专属DOM
let originalThead = null;
let fixedHeaderWrap = null;
let fixedHeaderRow = null;
let tableScrollWrap = null;
// 导入base导出方法
import {
    RESIZE_DELAY_LAYOUT,
    isMainNavHidden,
    getMainNavHeight
} from '../../base/js/base.js';
let tableScrollTicking = false;          // 表格横向滚动事件节流标记
let windowScrollTicking = false;         // 窗口纵向滚动事件节流标记
let tableResizeTimer = null;             // 表格独立 resize 防抖定时器
let tableScrollListener = null;          // 保存滚动监听函数引用，便于清理
let tableResizeListener = null;          // 保存 resize 监听函数引用
let tableWindowScrollListener = null;    // 保存窗口滚动监听函数引用
let navEventAbortController = null;      // 用于清理事件监听
let isTableInited = false;
let tableCleanupFn = null;
let beforeUnloadCleanup = null;          // 消除隐式全局变量

/** 克隆表头样式到悬浮表头 */
export function syncTableHeaderCellStyle() {
    if (!originalThead || !fixedHeaderRow || !fixedHeaderWrap) return;
    const sourceThList = originalThead.querySelectorAll('tr th');
    if (sourceThList.length === 0) {
        fixedHeaderWrap.style.display = 'none';
        return;
    }
    let targetCells = fixedHeaderRow.querySelectorAll('div');
    if (sourceThList.length !== targetCells.length) {
        fixedHeaderRow.innerHTML = '';
        sourceThList.forEach(th => {
            const cell = document.createElement('div');
            cell.textContent = th.textContent.trim();
            cell.className = th.className;
            fixedHeaderRow.appendChild(cell);
        });
        targetCells = fixedHeaderRow.querySelectorAll('div');
    }
    sourceThList.forEach((th, idx) => {
        const cell = targetCells[idx];
        if (!cell) return;
        const thStyle = getComputedStyle(th);
        const realWidth = th.getBoundingClientRect().width; // 保留浮点精度，降低子像素偏差
        cell.style.width = `${realWidth}px`;
        cell.style.minWidth = `${realWidth}px`;
        cell.style.maxWidth = `${realWidth}px`;
        cell.style.padding =
            `${thStyle.paddingTop} ${thStyle.paddingRight} ${thStyle.paddingBottom} ${thStyle.paddingLeft}`;
        cell.style.fontSize = thStyle.fontSize;
        cell.style.fontWeight = thStyle.fontWeight;
        cell.style.lineHeight = thStyle.lineHeight;
        cell.style.color = thStyle.color;
        cell.style.whiteSpace = thStyle.whiteSpace;
        cell.style.textAlign = thStyle.textAlign;
        cell.style.verticalAlign = 'middle';
        cell.style.boxSizing = thStyle.boxSizing;
        cell.style.border = thStyle.border;
    });

    // 修正：新增纵向滚动条宽度补偿，解决表格纵向滚动时表头列错位问题
    if (tableScrollWrap) {
        const scrollBarWidth = tableScrollWrap.offsetWidth - tableScrollWrap.clientWidth;
        fixedHeaderRow.style.paddingRight = `${scrollBarWidth}px`;
    }
}
/** 悬浮表头top定位 */
function updateFixedHeaderPosition() {
    if (!fixedHeaderWrap) return;
    const navHidden = isMainNavHidden();
    if (navHidden) {
        fixedHeaderWrap.style.top = '0px';
    } else {
        fixedHeaderWrap.style.top = `calc(var(--nav-height) + var(--gap-height))`;
    }
}
/** 同步悬浮表头显示/横向偏移 */
function syncFixedHeaderScrollState() {
    if (!originalThead || !fixedHeaderWrap || !fixedHeaderRow || !tableScrollWrap) return;
    const rect = originalThead.getBoundingClientRect();
    
    // 动态计算表头显示阈值，匹配导航栏高度与间隙，消除显示断层
    const navHidden = isMainNavHidden();
    const navHeight = getMainNavHeight();
    // 从CSS变量读取间隙高度，自动适配响应式断点变化
    const gapHeight = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--gap-height')) || 0;
    const showThreshold = navHidden ? 0 : (navHeight + gapHeight);
    // 原表头顶部滚入导航/间隙区域时即显示固定表头
    fixedHeaderWrap.style.display = rect.top < showThreshold ? 'block' : 'none';

    const maxX = tableScrollWrap.scrollWidth - tableScrollWrap.clientWidth;
    const validX = maxX > 0 ? Math.min(tableScrollWrap.scrollLeft, maxX) : 0;
    fixedHeaderRow.style.transform = `translateX(${-validX}px)`;
}
/* 表格滚动复合更新 */
function tableFullScrollSync() {
    if (!tableScrollTicking) {
        requestAnimationFrame(() => {
            syncFixedHeaderScrollState();
            tableScrollTicking = false;
        });
        tableScrollTicking = true;
    }
}
/** 独立的表格 resize 防抖函数，避免与 base.js 的 debounceLayout 冲突 */
function debounceTableResize(cb, delay) {
    clearTimeout(tableResizeTimer);
    tableResizeTimer = setTimeout(cb, delay);
}
// 表格数据动态变化后，列宽可能改变，外部可调用此函数手动同步表头
export function refreshTableHeader() {
    // 先同步表头文字宽度
    syncTableHeaderCellStyle();
    // 计算悬浮表头距离顶部高度
    updateFixedHeaderPosition();
    // 页面初始化立刻执行一次滚动同步，刚进页面滚动未触发时也能正常判断是否显示表头
    syncFixedHeaderScrollState();
}
/** 表格初始化 - 返回清理函数 */
export function tableHeaderInit() {
    // 如果已经初始化，先清理旧实例，避免累积
    if (isTableInited && typeof tableCleanupFn === 'function') {
        tableCleanupFn(); 
        isTableInited = false;
        tableCleanupFn = null;
    }
    originalThead = document.getElementById('originalThead');
    fixedHeaderWrap = document.getElementById('fixedHeader');
    fixedHeaderRow = document.getElementById('fixedHeaderRow');
    tableScrollWrap = document.getElementById('tableWrap');
    // 首次同步
    refreshTableHeader();
    // 定义滚动/缩放监听
    const scrollHandler = tableFullScrollSync;
    const resizeHandler = () => {
        debounceTableResize(() => {
            refreshTableHeader();
        }, RESIZE_DELAY_LAYOUT);
    };
    const windowScrollHandler = () => {
        if (!windowScrollTicking) {
            requestAnimationFrame(() => {
                syncFixedHeaderScrollState();
                updateFixedHeaderPosition();
                windowScrollTicking = false;
            });
            windowScrollTicking = true;
        }
    };
    // 绑定事件
    if (tableScrollWrap) {
        tableScrollWrap.addEventListener('scroll', scrollHandler, { passive: true });
        tableScrollListener = scrollHandler;
    }
    window.addEventListener('resize', resizeHandler, { passive: true });
    tableResizeListener = resizeHandler;
    window.addEventListener('scroll', windowScrollHandler, { passive: true });
    tableWindowScrollListener = windowScrollHandler;
    // 导航事件监听
    const navEventCallback = () => {
        updateFixedHeaderPosition();
        syncFixedHeaderScrollState();
    };
    navEventAbortController = new AbortController();
    window.addEventListener('navVisibilityChanged', navEventCallback, { signal: navEventAbortController.signal });
    // 清理函数
    const cleanup = function cleanup() {
        // 移除表格滚动监听
        if (tableScrollWrap && tableScrollListener) {
            tableScrollWrap.removeEventListener('scroll', tableScrollListener);
            tableScrollListener = null;
        }
        // 移除 resize 监听
        if (tableResizeListener) {
            window.removeEventListener('resize', tableResizeListener);
            tableResizeListener = null;
        }
        // 移除窗口滚动监听
        if (tableWindowScrollListener) {
            window.removeEventListener('scroll', tableWindowScrollListener);
            tableWindowScrollListener = null;
        }
        // 移除导航事件监听
        if (navEventAbortController) {
            navEventAbortController.abort();
            navEventAbortController = null;
        }
        // 清除定时器
        clearTimeout(tableResizeTimer);
        tableResizeTimer = null;
        tableScrollTicking = false;
        windowScrollTicking = false;
        // 隐藏固定表头
        if (fixedHeaderWrap) fixedHeaderWrap.style.display = 'none';
        // 重置状态
        isTableInited = false;
        tableCleanupFn = null;
        // 移除 beforeunload 监听
        if (beforeUnloadCleanup) {
            window.removeEventListener('beforeunload', beforeUnloadCleanup);
            beforeUnloadCleanup = null;
        }
    };
    // 保存清理函数引用
    tableCleanupFn = cleanup;
    isTableInited = true;
    // 注册 beforeunload 事件（页面卸载时自动清理）
    const onBeforeUnload = function() {
        if (typeof tableCleanupFn === 'function') {
            tableCleanupFn();
        }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    beforeUnloadCleanup = onBeforeUnload;
    // 返回清理函数（供外部手动调用）
    return cleanup;
}