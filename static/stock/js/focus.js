'use strict';
import { postRequest, refreshQuotes, chartPageContainer, initChartPage, destroyChart } from './func.js';

// ===================== focus-list 页面 =====================
export function initFocusList(interval) {
    const tbody = document.getElementById('stockBody');
    if (!tbody) return;

    let dragRow = null;          // 当前拖拽的行
    let isDragging = false;      // 是否处于拖拽模式（触摸专用）
    let longPressTimer = null;   // 长按定时器
    let touchStartY = 0;
    let refreshTimer = null; 

    // 工具函数
    function getRowFromTarget(target) {
        return target.closest?.('tr[data-code]') || null;
    }

    function clearDragState() {
        if (dragRow) {
            dragRow.classList.remove('dragging');
            dragRow = null;
        }
        tbody.querySelectorAll('tr.drag-over').forEach(tr => tr.classList.remove('drag-over'));
        isDragging = false;
        if (longPressTimer) {
            clearTimeout(longPressTimer);
            longPressTimer = null;
        }
    }

    function saveSortOrder() {
        const codes = Array.from(tbody.querySelectorAll('tr[data-code]'))
            .map(tr => tr.dataset.code.split('.')); // split 为[code, market]
        postRequest('/focus/list', { action: 'sort', codes })
            .then(() => console.log('排序已保存'))
            .catch(err => {
                console.warn('排序保存失败:', err);
            });
    }

    // 鼠标拖拽
    tbody.querySelectorAll('tr[data-code]').forEach(tr => {
        tr.setAttribute('draggable', 'true');
        tr.classList.add('sorting-mode');
    });

    tbody.addEventListener('dragstart', (e) => {
        const row = getRowFromTarget(e.target);
        if (!row) return;
        dragRow = row;
        dragRow.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', dragRow.dataset.code);
    });

    tbody.addEventListener('dragover', (e) => {
        if (!dragRow) return;
        e.preventDefault();
        const target = getRowFromTarget(e.target);
        if (!target || target === dragRow) return;
        tbody.querySelectorAll('tr.drag-over').forEach(tr => tr.classList.remove('drag-over'));
        target.classList.add('drag-over');
        const rect = target.getBoundingClientRect();
        if (e.clientY > rect.top + rect.height / 2) {
            target.after(dragRow);
        } else {
            target.before(dragRow);
        }
    });

    tbody.addEventListener('dragend', (e) => {
        if (dragRow) {
            saveSortOrder();
            clearDragState();
        }
    });

    // 触摸拖拽 (长按触发)
    tbody.querySelectorAll('tr[data-code]').forEach(tr => {
        tr.addEventListener('touchstart', (e) => {
            // 如果触摸点在链接或按钮上，忽略（不启动长按）
            const target = e.target;
            if (target.closest('a') || target.closest('button')) return;

            const row = getRowFromTarget(target);
            if (!row) return;

            // 清除之前的定时器
            if (longPressTimer) clearTimeout(longPressTimer);

            // 保存当前触摸的行和起始位置
            dragRow = row;
            touchStartY = e.touches[0].clientY;

            // 启动长按定时器（500ms）
            longPressTimer = setTimeout(() => {
                // 进入拖拽模式
                isDragging = true;
                dragRow.classList.add('dragging');
                // 震动反馈
                if (navigator.vibrate) navigator.vibrate(20);
                // 后续 touchmove 将阻止滚动
            }, 500);
        }, { passive: true }); // passive 不阻止默认行为，以便滚动
    });

    // 全局 touchmove 监听
    document.addEventListener('touchmove', (e) => {
        // 如果没有拖拽行或尚未进入拖拽模式，不阻止滚动
        if (!dragRow || !isDragging) {
            // 如果长按定时器存在且移动距离过大，取消长按（避免误触）
            if (longPressTimer && dragRow) {
                // 简单判断：移动超过10px则取消长按
                const touch = e.touches[0];
                if (Math.abs(touch.clientY - touchStartY) > 10) {
                    clearTimeout(longPressTimer);
                    longPressTimer = null;
                    dragRow = null; // 重置，防止后续操作
                }
            }
            return;
        }

        // 拖拽模式：阻止页面滚动
        e.preventDefault();

        const touch = e.touches[0];
        const clientY = touch.clientY;

        // 获取所有行（排除当前拖拽行）
        const rows = Array.from(tbody.querySelectorAll('tr[data-code]')).filter(r => r !== dragRow);
        let targetRow = null;
        for (const row of rows) {
            const rect = row.getBoundingClientRect();
            const midY = rect.top + rect.height / 2;
            if (clientY > midY) {
                targetRow = row;
            } else {
                break;
            }
        }

        // 清除所有悬停样式
        tbody.querySelectorAll('tr.drag-over').forEach(tr => tr.classList.remove('drag-over'));

        if (targetRow) {
            targetRow.classList.add('drag-over');
            const rect = targetRow.getBoundingClientRect();
            if (clientY > rect.top + rect.height / 2) {
                targetRow.after(dragRow);
            } else {
                targetRow.before(dragRow);
            }
        } else {
            // 处理第一行之前或最后一行之后
            const firstRow = tbody.querySelector('tr[data-code]');
            if (firstRow && firstRow !== dragRow && clientY < firstRow.getBoundingClientRect().top + 10) {
                firstRow.before(dragRow);
            }
            const lastRow = tbody.querySelector('tr[data-code]:last-child');
            if (lastRow && lastRow !== dragRow && clientY > lastRow.getBoundingClientRect().bottom - 10) {
                lastRow.after(dragRow);
            }
        }
    }, { passive: false });

    // 全局 touchend 和 touchcancel
    document.addEventListener('touchend', (e) => {
        if (longPressTimer) {
            clearTimeout(longPressTimer);
            longPressTimer = null;
        }
        if (isDragging && dragRow) {
            // 保存排序
            saveSortOrder();
            // 清理状态
            clearDragState();
        } else {
            // 如果没有进入拖拽，重置 dragRow
            if (dragRow) {
                dragRow = null;
            }
        }
        // 确保所有拖拽样式清除
        tbody.querySelectorAll('tr.drag-over').forEach(tr => tr.classList.remove('drag-over'));
    });

    document.addEventListener('touchcancel', () => {
        if (longPressTimer) {
            clearTimeout(longPressTimer);
            longPressTimer = null;
        }
        if (isDragging && dragRow) {
            // 不保存排序，直接取消
            clearDragState();
        } else {
            if (dragRow) dragRow = null;
        }
        tbody.querySelectorAll('tr.drag-over').forEach(tr => tr.classList.remove('drag-over'));
    });

    // 首次加载 + 启动定时轮询
    function loadQuotesAndStartRefresh() {
        // 先清除旧定时器，防止重复
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
        // 首次加载
        refreshQuotes('/focus/list', tbody);
        refreshTimer = setInterval(() => {
            refreshQuotes('/focus/list', tbody);
        }, interval);
    }

    // 执行首次加载与轮询
    loadQuotesAndStartRefresh();

    // 页面卸载时清除定时器
    window.addEventListener('beforeunload', function cleanup() {
        if (refreshTimer) {
            clearInterval(refreshTimer);
            refreshTimer = null;
        }
        // 移除监听器以避免重复绑定（可选）
        window.removeEventListener('beforeunload', cleanup);
    });
}


export function initFocusPlus(config) {
    const catSel = document.querySelector('[name="cat_choice"]');
    const marketSel = document.querySelector('[name="market_choice"]');
    const codeInput = document.getElementById('id_code_input');
    const nameInput = document.getElementById('id_name_input');
    const priceInput = document.getElementById('id_plan_price');
    const qtyInput = document.getElementById('id_plan_qty');
    const targetInput = document.getElementById('id_target_price');
    const stopInput = document.getElementById('id_stop_price');
    const allowedInput = document.getElementById('id_allowed_qty');
    const ratioInput = document.getElementById('id_win_ratio');
    const formErr = document.getElementById('formError');
    const errText = document.getElementById('errorText');

    if (!codeInput) return;
    const initChart = config.initChart || {};
    let nameFetchTimer = null;

    // 清除 form 错误提示
    function clearFormErr() {                        
        if (formErr) {                            
            formErr.textContent = '';
            formErr.style.display = 'none';
        }
    }

    function fetchStockInfo() {
        const code = (codeInput?.value || '').trim();
        const market = marketSel?.value || 'SH';
        const cat = catSel?.value || 'stock';
        const deci = cat === 'stock'?2:3;
         
        // 清除之前的定时器
        clearTimeout(nameFetchTimer);

        // 代码无效：清空名称，隐藏图表，销毁实例
        if (!code || code.length < 4) {
            if (nameInput) nameInput.value = '';
            if (errText) { errText.classList.add('d-none'); }
            return;
        }

        // 延迟请求（防抖）
        nameFetchTimer = setTimeout(() => {
            fetch(`/focus/api/stock-name?code=${code}&market=${market}`)
                .then(r => r.json())
                .then(data => {
                    if (data.name) {
                        nameInput.value = data.name;
                        
                        // 构建动态图表配置
                        const chartConfig = {
                            site: initChart.site,
                            code: code,
                            market: market,
                            name: data.name,
                            cat: cat,
                            view: initChart.view || 'kline',
                            navi: initChart.navi || false,
                            kline: initChart.kline,
                            trend: initChart.trend,
                            deci: deci
                        };
                        
                        if (errText) {
                            errText.textContent = '';
                            errText.classList.add('d-none');
                        }

                        if (chartPageContainer) {
                            chartPageContainer.classList.remove('d-none'); // 显示
                            initChartPage(chartConfig);
                        }
                    } else {
                        nameInput.value = '';
                        if (errText) {
                            errText.textContent = '未找到该股票代码';
                            errText.classList.remove('d-none');
                            chartPageContainer.classList.add('d-none');
                            destroyChart();
                        }
                    }
                })
                .catch(() => {
                    if (errText) {
                        errText.textContent = '网络请求失败';
                        errText.classList.remove('d-none');
                        chartPageContainer.classList.add('d-none');
                        destroyChart();
                    }
                });
        }, 1000);
    }

    // ---- 允许购买数量 ----
    function calcAllowed() {
        const price = parseFloat(priceInput.value) || 0;
        const capital = config.available || 0;
        if (price <= 0 || capital <= 0) { allowedInput.value = 0; return; }
        const maxQty = Math.floor(capital / price);
        allowedInput.value = Math.floor(maxQty / 100) * 100;
        checkQtyExceed();
    }

    // ---- 胜率 ----
    function calcWinRatio() {
        let buy = parseFloat(priceInput.value) || 0;
        let target = parseFloat(targetInput.value) || 0;
        let stop = parseFloat(stopInput.value) || 0;
        if (buy <= 0) return 0;
        if (stop >= buy) return 99;
        if (target <= buy) return 0;

        const ratio = Math.max(0, Math.min(99, Math.round((target - buy) / (target - stop) * 99)));        
        ratioInput.value = ratio;
        if (ratio === 0 || ratio === 99) {
            ratioInput.style.color = '#00008B';
            ratioInput.style.fontWeight = 'bold';
        } else {
            ratioInput.style.color = '';
            ratioInput.style.fontWeight = '';
        }
    }
    
    // ---- 购买数量超限检查 ----
    function checkQtyExceed() {
        const planQty = parseInt(qtyInput?.value) || 0;
        const allowed = parseInt(allowedInput?.value) || 0;
        if (planQty > allowed && allowed > 0) {
            allowedInput.style.color = '#8B0000';
            allowedInput.style.fontWeight = 'bold';
        } else {
            allowedInput.style.color = '';
            allowedInput.style.fontWeight = '';
        }
    }

    // ---- 事件绑定 ----
    priceInput.addEventListener('input', () => {calcAllowed(); calcWinRatio(); });
    targetInput.addEventListener('input', calcWinRatio);
    stopInput.addEventListener('input', calcWinRatio);
    qtyInput?.addEventListener('input', checkQtyExceed);

    // catSel?.addEventListener('change', () => {clearFormErr(); fetchStockInfo()});
    marketSel?.addEventListener('change', () => {clearFormErr(); fetchStockInfo()});
    codeInput?.addEventListener('blur', () => {clearFormErr(); fetchStockInfo()});
    // codeInput?.addEventListener('input', () => {clearFormErr(); fetchStockInfo()});

    // 初始计算
    calcAllowed();
    calcWinRatio();

    // ---- 页面初始化时，若已有代码，自动获取股票信息 ----
    if (codeInput && codeInput.value.trim()) {
        fetchStockInfo();
    }
}



