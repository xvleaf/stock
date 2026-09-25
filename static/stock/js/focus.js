import { chartPageContainer, initChartPage, destroyChart, setPageConfig } from './chart.js';
import { postRequest, refreshQuotes, getCsrfToken } from './func.js';

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
            .map(tr => tr.dataset.code.split('.'));   // split 为[code, market]
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

            // 启动长按定时器
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
    function loadQuotes() {
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
    loadQuotes();

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

// ===================== 通用：focus 计算（AJAX 请求后台） =====================
function createFocusCalc(priceId, targetId, stopId, allowedId, winId, intentSelector) {
    const priceInput = document.getElementById(priceId);
    const targetInput = document.getElementById(targetId);
    const stopInput = document.getElementById(stopId);
    const allowedInput = document.getElementById(allowedId);
    const winInput = document.getElementById(winId);
    if (!priceInput) return null;

    let lastParams = null;
    let calcTimer = null;

    function getIntent() {
        const intentEl = document.querySelector(intentSelector || '[name="intent_choice"]');
        if (intentEl) {
            if (intentEl.tagName === 'SELECT') return intentEl.value;
            return intentEl.value === '卖出' ? 'S' : 'B';
        }
        return 'B';
    }

    function collectParams() {
        return {
            intent: getIntent(),
            plan_price: parseFloat(priceInput.value) || 0,
            target_price: parseFloat(targetInput?.value) || 0,
            stop_price: parseFloat(stopInput?.value) || 0,
        };
    }

    function isParamsChanged(params) {
        if (!lastParams) return true;
        return JSON.stringify(params) !== JSON.stringify(lastParams);
    }

    function requestCalc() {
        const params = collectParams();
        if (!isParamsChanged(params)) return;
        lastParams = { ...params };

        fetch('/focus/calc', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(params),
        })
        .then(res => res.json())
        .then(data => {
            if (data.error) return;
            if (allowedInput) allowedInput.value = data.allowed_qty;
            if (winInput) winInput.value = data.win_ratio;

            // 超限检查
            const planQty = parseInt(document.getElementById('id_plan_qty')?.value) || 0;
            const allowedQty = parseInt(data.allowed_qty) || 0;
            if (allowedInput) {
                if (planQty > allowedQty && allowedQty > 0) {
                    allowedInput.style.color = '#8B0000';
                    allowedInput.style.fontWeight = 'bold';
                } else {
                    allowedInput.style.color = '';
                    allowedInput.style.fontWeight = '';
                }
            }
        })
        .catch(() => {});
    }

    function scheduleCalc() {
        if (calcTimer) clearTimeout(calcTimer);
        calcTimer = setTimeout(requestCalc, 300);
    }

    // 事件绑定
    priceInput.addEventListener('input', scheduleCalc);
    if (targetInput) targetInput.addEventListener('input', scheduleCalc);
    if (stopInput) stopInput.addEventListener('input', scheduleCalc);
    const planQtyInput = document.getElementById('id_plan_qty');
    if (planQtyInput) planQtyInput.addEventListener('input', scheduleCalc);
    const intentEl = document.querySelector(intentSelector || '[name="intent_choice"]');
    if (intentEl) intentEl.addEventListener('change', scheduleCalc);

    // 初始计算
    requestCalc();

    return { requestCalc, scheduleCalc };
}

// ===================== focus-plus 页面 =====================
export function initFocusPlus(config) {
    const catSel = document.querySelector('[name="cat_choice"]');
    const marketSel = document.querySelector('[name="market_choice"]');
    const codeInput = document.getElementById('id_code_input');
    const nameInput = document.getElementById('id_name_input');
    const priceInput = document.getElementById('id_plan_price');
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
        
        // 清除之前的定时器
        clearTimeout(nameFetchTimer);

        if (!code || code.length < 4) {
            if (nameInput) nameInput.value = '';
            if (errText) { errText.classList.add('d-none'); }
            return;
        }

        nameFetchTimer = setTimeout(() => {
            fetch(`/api/stock-name?code=${code}&market=${market}`)
                .then(r => r.json())
                .then(data => {
                    if (data.name) {
                        nameInput.value = data.name;
                        initChart.code = code;
                        initChart.name = data.name;
                        initChart.market = market;
                        initChart.cat = cat;
                        setPageConfig(initChart);

                        if (errText) {
                            errText.textContent = '';
                            errText.classList.add('d-none');
                        }
                        if (chartPageContainer) {
                            chartPageContainer.classList.remove('d-none');
                            initChartPage();
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

    // 启动自动计算
    createFocusCalc('id_plan_price', 'id_target_price', 'id_stop_price', 'id_allowed_qty', 'id_win_ratio');

    // cat_choice 变化时动态更新价格字段 step
    catSel?.addEventListener('change', () => {
        const step = catSel.value === 'fund' || catSel.value === 'bond' ? '0.001' : '0.01';
        const targetInput = document.getElementById('id_target_price');
        const stopInput = document.getElementById('id_stop_price');
        [priceInput, targetInput, stopInput].forEach(el => {
            if (el) el.step = step;
        });
        clearFormErr();
        fetchStockInfo();
    });
    marketSel?.addEventListener('change', () => {clearFormErr(); fetchStockInfo()});
    codeInput?.addEventListener('blur', () => {clearFormErr(); fetchStockInfo()});

    // 若已有代码，自动获取
    if (codeInput && codeInput.value.trim()) {
        fetchStockInfo();
    }
}

export function initFocusView(config) {
    const form = document.getElementById('focusForm');
    if (!form) return;

    const isSummary = config.is_summary !== false;
    const initChart = config.initChart || {};
    setPageConfig(initChart);

    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }

    // 历史模式下文字变灰，汇总模式恢复
    if (!isSummary) {
        form.querySelectorAll('input, select, textarea').forEach(el => {
            el.style.color = '#6c757d';
        });
    } else {
        form.querySelectorAll('input, select, textarea').forEach(el => {
            el.style.color = '';
        });
    }

    // 启动自动计算
    createFocusCalc('id_plan_price', 'id_target_price', 'id_stop_price', 'id_allowed_qty', 'id_win_ratio');
}

// ===================== 编辑关注页面 =====================
export function initFocusEdit(config) {
    const form = document.getElementById('focusForm');
    if (!form) return;

    const initChart = config.initChart || {};
    setPageConfig(initChart);

    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }

    // 启动自动计算
    createFocusCalc('id_plan_price', 'id_target_price', 'id_stop_price', 'id_allowed_qty', 'id_win_ratio');
}
