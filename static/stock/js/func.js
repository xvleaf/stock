export let priceDecimal = 2;
// 滚动监听：上滑隐藏，下滑显示
let lastScrollTop = 0;


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

export function refreshQuotes(url, tbody) {
    // 收集当前页显示的股票（只查询这些，避免查询所有股票）
    const codes = Array.from(tbody.querySelectorAll('tr[data-code]')).map(tr => tr.dataset.code);
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ codes: codes }),
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

export function setPriceDecimal(val) {
    priceDecimal = Number(val) || 2;
}

export function showChartError(text) {
    const errText = document.getElementById('errorText');
    if (errText) {
        errText.textContent = text;
        errText.classList.remove('d-none');
    }
}

export function sweetMessage(title, message) {
    showConfirm({ title: title, text: message, confirmText: '确认', cancelText: '取消' }).then((confirmed) => {
        if (confirmed) {
            showAlert({ title: '已删除', text: '记录已成功删除', type: 'success' });
        }
    });
}

export function updateFormData(data) {
    // 更新顶部名称和代码
    const nameItem = document.getElementById('nameItem');
    const codeItem = document.getElementById('codeItem');
    if (nameItem) nameItem.textContent = data.name || '';
    if (codeItem) codeItem.textContent = data.code || '';

    // 更新表单字段（所有可编辑字段）
    const fieldMap = {
        'id_code_input': 'code',
        'id_name_input': 'name',
        'id_code': 'code',
        'id_name': 'name',
        'id_focus_date': 'focus_date',
        'id_plan_price': 'plan_price',
        'id_plan_qty': 'plan_qty',
        'id_target_price': 'target_price',
        'id_stop_price': 'stop_price',
        'id_allowed_qty': 'allowed_qty',
        'id_win_ratio': 'win_ratio',
        'id_comments': 'comments',
    };

    // focus金额字段也需要按cat类型格式化
    const focusAmountFields = ['id_plan_price', 'id_target_price', 'id_stop_price'];
    const focusCat = data.cat || 'stock';
    const focusDeci = (focusCat === 'fund' || focusCat === 'bond') ? 3 : 2;

    for (const [id, key] of Object.entries(fieldMap)) {
        const el = document.getElementById(id);
        if (el && data[key] !== undefined) {
            let value = data[key];
            // 金额字段按cat类型格式化
            if (focusAmountFields.includes(id) && value !== '' && value !== null && !isNaN(value)) {
                value = parseFloat(value).toFixed(focusDeci);
            }
            el.value = value;
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

    // 交易详情（trans-view）字段
    const transFieldMap = {
        'trans_cat': 'cat_display',
        'trans_market': 'market_display',
        'trans_code': 'code',
        'trans_name': 'name',
        'trans_price': 'price',
        'trans_qty': 'qty',
        'trans_amount': 'amount',
        'trans_profit': 'profit',
        'trans_target_price': 'target_price',
        'trans_stop_price': 'stop_price',
        'trans_win_ratio': 'win_ratio',
        'trans_risk_amount': 'risk_amount',
        'trans_comments': 'comments',
        // 清仓交易特有字段
        'trans_deal_price': 'deal_price',
        'trans_deal_qty': 'deal_qty',
        'trans_total_profit': 'total_profit',
        'trans_profit_ratio': 'profit_ratio',
    };

    // 需要按cat类型格式化的金额字段
    const amountFields = ['trans_price', 'trans_amount', 'trans_profit', 'trans_target_price', 
                          'trans_stop_price', 'trans_risk_amount', 'trans_deal_price', 'trans_total_profit'];
    // 根据cat类型确定小数点位数（fund/bond为3位，其他为2位）
    const cat = data.cat || 'stock';
    const deci = (cat === 'fund' || cat === 'bond') ? 3 : 2;

    for (const [id, key] of Object.entries(transFieldMap)) {
        const el = document.getElementById(id);
        if (el && data[key] !== undefined) {
            let value = data[key];
            // 金额字段按cat类型格式化
            if (amountFields.includes(id) && value !== '' && value !== null && !isNaN(value)) {
                value = parseFloat(value).toFixed(deci);
            }
            el.value = value;
        }
    }

    // 历史指示器更新（trans）
    const pilotWrap = document.getElementById('transPilotWrap');
    const pilotIndicator = document.getElementById('transPilotIndicator');
    if (pilotIndicator && data.pilot_idx !== undefined && data.pilot_total !== undefined) {
        const isSummary = data.is_summary === true || data.pilot_idx === -1;
        if (pilotWrap) {
            // 汇总模式且有多条历史时隐藏；只有一条历史时显示建仓记录
            if (isSummary && data.pilot_total > 1) {
                pilotWrap.classList.add('d-none');
            } else {
                pilotWrap.classList.remove('d-none');
            }
        }
        if (!isSummary || data.pilot_total === 1) {
            const qtyPriceStr = (data.pilot_qty && data.pilot_price !== '') ? `${data.pilot_qty}股@${data.pilot_price}元` : '';
            const dateStr = data.pilot_date ? ` [${data.pilot_date}` : '';
            const actionStr = data.pilot_action ? ` ${data.pilot_action}${qtyPriceStr}]` : (data.pilot_date ? ']' : '');
            const idx = isSummary ? 1 : (data.pilot_idx + 1);
            pilotIndicator.textContent = `第 ${idx} / ${data.pilot_total} 笔${dateStr}${actionStr}`;
        }
    }

    // 历史指示器更新（focus）
    const focusPilotWrap = document.getElementById('focusPilotWrap');
    const focusPilotIndicator = document.getElementById('focusPilotIndicator');
    if (focusPilotIndicator && data.pilot_idx !== undefined && data.pilot_total !== undefined) {
        const isSummary = data.is_summary === true || data.pilot_idx === -1;
        if (focusPilotWrap) {
            if (isSummary) {
                focusPilotWrap.classList.add('d-none');
            } else {
                focusPilotWrap.classList.remove('d-none');
            }
        }
        if (!isSummary) {
            const focusDateStr = data.pilot_date ? ` [${data.pilot_date}` : '';
            const focusActionStr = data.pilot_action ? ` ${data.pilot_action}]` : (data.pilot_date ? ']' : '');
            focusPilotIndicator.textContent = `第 ${data.pilot_idx + 1} / ${data.pilot_total} 笔${focusDateStr}${focusActionStr}`;
        }
    }

    // 历史模式下文字变灰，汇总模式恢复（trans）
    if (data.is_summary === false || (data.pilot_idx !== undefined && data.pilot_idx >= 0)) {
        document.querySelectorAll('#transViewForm .readonly-field').forEach(el => {
            el.style.color = '#6c757d';
        });
        // 历史模式隐藏复盘特有字段
        document.querySelectorAll('.review-only-fields').forEach(el => el.classList.add('d-none'));
        // 历史模式显示仅历史模式的字段
        document.querySelectorAll('.trans-history-only').forEach(el => el.classList.remove('d-none'));
        // 历史模式隐藏评级下拉框（review 页面）
        const reviewRatingWrap = document.getElementById('reviewRatingWrap');
        if (reviewRatingWrap) reviewRatingWrap.classList.add('d-none');
    } else {
        document.querySelectorAll('#transViewForm .readonly-field').forEach(el => {
            el.style.color = '';
        });
        // 汇总模式显示复盘特有字段
        document.querySelectorAll('.review-only-fields').forEach(el => el.classList.remove('d-none'));
        // 汇总模式隐藏仅历史模式的字段
        document.querySelectorAll('.trans-history-only').forEach(el => el.classList.add('d-none'));
        // 汇总模式显示评级下拉框（review 页面）
        const reviewRatingWrap = document.getElementById('reviewRatingWrap');
        if (reviewRatingWrap) reviewRatingWrap.classList.remove('d-none');
    }

    // 清仓交易字段显示控制（必须在 trans-history-only 处理之后执行）
    const isHistoryMode = data.is_summary === false || (data.pilot_idx !== undefined && data.pilot_idx >= 0);
    if (isHistoryMode) {
        if (data.is_close_trade) {
            // 清仓交易：隐藏普通历史字段，显示清仓特有字段
            document.querySelectorAll('.trans-normal-history').forEach(el => el.classList.add('d-none'));
            document.querySelectorAll('.trans-close-only').forEach(el => el.classList.remove('d-none'));
        } else {
            // 非清仓交易：显示普通历史字段，隐藏清仓特有字段
            document.querySelectorAll('.trans-normal-history').forEach(el => el.classList.remove('d-none'));
            document.querySelectorAll('.trans-close-only').forEach(el => el.classList.add('d-none'));
        }
    } else {
        // 汇总模式：隐藏清仓特有字段
        document.querySelectorAll('.trans-close-only').forEach(el => el.classList.add('d-none'));
    }

    // 历史模式下文字变灰，汇总模式恢复（focus）
    if (data.is_summary === false || (data.pilot_idx !== undefined && data.pilot_idx >= 0)) {
        document.querySelectorAll('#focusForm input, #focusForm select, #focusForm textarea').forEach(el => {
            // 备注输入框不变灰，保持可编辑
            if (el.id === 'id_comments') return;
            el.style.color = '#6c757d';
        });
        // 历史模式隐藏评级下拉框（review 页面）
        const reviewRatingWrap = document.getElementById('reviewRatingWrap');
        if (reviewRatingWrap) reviewRatingWrap.classList.add('d-none');
        // 历史模式隐藏复盘特有字段
        document.querySelectorAll('.review-only-fields').forEach(el => el.classList.add('d-none'));
    } else {
        document.querySelectorAll('#focusForm input, #focusForm select, #focusForm textarea').forEach(el => {
            el.style.color = '';
        });
        // 汇总模式显示评级下拉框（review 页面）
        const reviewRatingWrap = document.getElementById('reviewRatingWrap');
        if (reviewRatingWrap) reviewRatingWrap.classList.remove('d-none');
        // 汇总模式显示复盘特有字段
        document.querySelectorAll('.review-only-fields').forEach(el => el.classList.remove('d-none'));
    }

    // 复盘特有字段更新（建仓日期、平仓日期、全部收益、收益比例）
    const reviewFieldMap = {
        'reviewOpenDate': 'open_date',
        'reviewCloseDate': 'close_date',
        'reviewProfit': 'total_profit',
        'reviewProfitRatio': 'profit_ratio',
    };
    for (const [id, key] of Object.entries(reviewFieldMap)) {
        const el = document.getElementById(id);
        if (el && data[key] !== undefined) {
            el.value = data[key];
            // 根据正负值设置颜色（全部收益和收益比例）
            if (id === 'reviewProfit' || id === 'reviewProfitRatio') {
                el.classList.remove('text-danger', 'text-success');
                if (parseFloat(data[key]) > 0) {
                    el.classList.add('text-danger');
                } else if (parseFloat(data[key]) < 0) {
                    el.classList.add('text-success');
                }
            }
        }
    }

    // 更新 pilot 按钮状态
    if (data.pilotPrev !== undefined) {
        const pilotPrevItem = document.getElementById('pilotPrevItem');
        if (pilotPrevItem) {
            if (data.pilotPrev) {
                pilotPrevItem.classList.remove('disabled');
            } else {
                pilotPrevItem.classList.add('disabled');
            }
        }
    }
    if (data.pilotNext !== undefined) {
        const pilotNextItem = document.getElementById('pilotNextItem');
        if (pilotNextItem) {
            if (data.pilotNext) {
                pilotNextItem.classList.remove('disabled');
            } else {
                pilotNextItem.classList.add('disabled');
            }
        }
    }

    // 存储 history_id 和 history_type 到表单 data 属性，供 review.js 使用
    const transForm = document.getElementById('transViewForm');
    const focusForm = document.getElementById('focusForm');
    const targetForm = transForm || focusForm;
    if (targetForm) {
        if (data.history_id !== undefined) {
            targetForm.dataset.historyId = data.history_id;
        }
        if (data.history_type !== undefined) {
            targetForm.dataset.historyType = data.history_type;
        }
        // 汇总模式时清除
        if (data.is_summary === true || data.pilot_idx === -1) {
            delete targetForm.dataset.historyId;
            delete targetForm.dataset.historyType;
        }
    }

    // 复盘交易页面：根据 history_type 切换显示 trans 字段还是 focus 字段
    if (transForm) {
        const transFields = document.getElementById('transForm');
        const focusFieldsInTrans = document.getElementById('focusFieldsInTrans');
        const isFocusHistory = data.history_type === 'focus' && data.is_summary !== true && data.pilot_idx !== -1;
        if (transFields) transFields.classList.toggle('d-none', isFocusHistory);
        if (focusFieldsInTrans) focusFieldsInTrans.classList.toggle('d-none', !isFocusHistory);

        // 指示器左侧标签切换：关注历史显示"关注记录"，交易历史显示"交易记录"
        const pilotLabelFirst = document.getElementById('pilotLabelFirst');
        if (pilotLabelFirst) {
            pilotLabelFirst.textContent = isFocusHistory ? '关注' : '交易';
        }
    }

    // 汇总模式时恢复备注为汇总页面的值（从初始值或 ReviewList 中获取）
    if (data.is_summary === true || data.pilot_idx === -1) {
        if (transForm && window._reviewSummaryComments !== undefined) {
            const transComments = document.getElementById('trans_comments');
            if (transComments) transComments.value = window._reviewSummaryComments;
        }
        if (focusForm && window._reviewSummaryComments !== undefined) {
            const idComments = document.getElementById('id_comments');
            if (idComments) idComments.value = window._reviewSummaryComments;
        }
        // 汇总模式移除备注失焦保存事件
        _unbindHistoryCommentSave();
    } else {
        // 历史模式绑定备注失焦保存（非复盘页面）
        const isReviewPage = window.location.pathname.startsWith('/review/');
        if (!isReviewPage) {
            _bindHistoryCommentSave(data);
        }
    }
}

// 历史模式备注失焦保存（focus-view / trans-view）
let _historyCommentHandler = null;
let _historyCommentOriginal = '';
let _historyCommentEl = null;

function _bindHistoryCommentSave(data) {
    // 确定备注输入框和接口
    const transComments = document.getElementById('trans_comments');
    const idComments = document.getElementById('id_comments');
    const el = transComments || idComments;
    if (!el) return;

    // 如果已经绑定了同一个元素，只更新原始值
    if (_historyCommentEl === el && _historyCommentHandler) {
        _historyCommentOriginal = el.value;
        return;
    }

    // 先移除旧的
    _unbindHistoryCommentSave();

    // 保存原始值
    _historyCommentOriginal = el.value;
    _historyCommentEl = el;

    _historyCommentHandler = async () => {
        if (!_historyCommentEl) return;
        const newValue = _historyCommentEl.value;
        // 内容没变不弹窗
        if (newValue === _historyCommentOriginal) return;

        const confirmed = await showConfirm({
            title: '确认修改备注',
            text: '确定要保存备注修改吗？',
            confirmText: '确定',
            cancelText: '取消',
        });

        if (confirmed) {
            const form = document.getElementById('transViewForm') || document.getElementById('focusForm');
            const historyId = form ? form.dataset.historyId : null;
            const isTrans = !!document.getElementById('transViewForm');
            const url = isTrans ? '/trans/save-history-comment' : '/focus/save-history-comment';

            try {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken(),
                    },
                    body: JSON.stringify({
                        history_id: historyId,
                        comments: newValue,
                    }),
                });
                const result = await res.json();
                if (result.success) {
                    _historyCommentOriginal = newValue;
                    showAlert({ title: '已保存', text: '备注已更新', type: 'success' });
                } else {
                    showAlert({ title: '保存失败', text: result.error || '未知错误', type: 'error' });
                    _historyCommentEl.value = _historyCommentOriginal;
                }
            } catch (e) {
                showAlert({ title: '保存失败', text: '网络错误', type: 'error' });
                _historyCommentEl.value = _historyCommentOriginal;
            }
        } else {
            // 取消时恢复原始值
            _historyCommentEl.value = _historyCommentOriginal;
        }
    };

    el.addEventListener('blur', _historyCommentHandler);
}

function _unbindHistoryCommentSave() {
    if (_historyCommentEl && _historyCommentHandler) {
        _historyCommentEl.removeEventListener('blur', _historyCommentHandler);
    }
    _historyCommentHandler = null;
    _historyCommentEl = null;
    _historyCommentOriginal = '';
}

export function initScrollFold() {
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

// 滚动防抖
function debounce(fn, delay = 16) {
    let timer = null;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// ===================== Bootstrap Modal 通用弹窗工具 =====================
let _modalCounter = 0;

function _createModal({ title, bodyHtml, footerHtml, centered = true, backdrop = 'static' }) {
    const id = `bs-modal-${++_modalCounter}`;
    const wrap = document.createElement('div');
    wrap.innerHTML = `
        <div class="modal fade" id="${id}" tabindex="-1" data-bs-backdrop="${backdrop}" data-bs-keyboard="false">
            <div class="modal-dialog ${centered ? 'modal-dialog-centered' : ''}">
                <div class="modal-content">
                    <div class="modal-header py-2 justify-content-center border-bottom-0">
                        <h5 class="modal-title fs-6 fw-bold text-center w-100">${title || ''}</h5>
                    </div>
                    <div class="modal-body">${bodyHtml || ''}</div>
                    ${footerHtml ? `<div class="modal-footer py-2 justify-content-between">${footerHtml}</div>` : ''}
                </div>
            </div>
        </div>`;
    const modalEl = wrap.firstElementChild;
    document.body.appendChild(modalEl);
    const modal = new bootstrap.Modal(modalEl);
    // 取消按钮：先 blur 焦点再手动 hide，避免 aria-hidden 警告
    modalEl.addEventListener('click', (e) => {
        if (e.target.closest('.modal-cancel')) {
            if (document.activeElement) document.activeElement.blur();
            modal.hide();
        }
    });
    modal.show();
    modalEl.addEventListener('hidden.bs.modal', () => {
        setTimeout(() => { modalEl.remove(); }, 200);
    });
    return { modal, modalEl };
}

/** 确认对话框，返回 Promise<boolean> */
export function showConfirm({ title, text, confirmText = '确定', cancelText = '取消', confirmClass = 'btn-primary' }) {
    return new Promise((resolve) => {
        const footer = `
            <button type="button" class="btn btn-link btn-sm text-decoration-none text-muted modal-cancel">${cancelText}</button>
            <button type="button" class="btn ${confirmClass} btn-sm modal-confirm">${confirmText}</button>`;
        const { modal, modalEl } = _createModal({ title, bodyHtml: `<p class="mb-0">${text || ''}</p>`, footerHtml: footer });
        modalEl.querySelector('.modal-confirm').addEventListener('click', () => {
            if (document.activeElement) document.activeElement.blur();
            modal.hide();
            resolve(true);
        });
        modalEl.addEventListener('hidden.bs.modal', () => resolve(false));
    });
}

/** 简单提示弹窗，自动关闭 */
export function showAlert({ title, text, type = 'info', autoClose = 3000 }) {
    // 方案A：Tabler Icons 线性描边图标（线宽约1.5px，更细更美观）
    const iconHtml = {
        success: '<iconify-icon icon="tabler:circle-check" style="color:#198754;font-size:48px;"></iconify-icon>',
        error: '<iconify-icon icon="tabler:circle-x" style="color:#dc3545;font-size:48px;"></iconify-icon>',
        warning: '<iconify-icon icon="tabler:alert-triangle" style="color:#fd7e14;font-size:48px;"></iconify-icon>',
        info: '<iconify-icon icon="tabler:info-circle" style="color:#0d6efd;font-size:48px;"></iconify-icon>'
    };
    const bodyHtml = `<div class="text-center"><div class="mb-2">${iconHtml[type] || ''}</div><p class="mb-0 fw-bold">${title || ''}</p>${text ? `<p class="mb-0 text-muted small">${text}</p>` : ''}</div>`;
    const { modal, modalEl } = _createModal({ title: '', bodyHtml, footerHtml: '' });
    if (autoClose > 0) {
        setTimeout(() => {
            // 先 blur 焦点再 hide，避免 aria-hidden 警告
            if (document.activeElement && modalEl.contains(document.activeElement)) {
                document.activeElement.blur();
            }
            modal.hide();
        }, autoClose);
    }
}

/** Radio 选择弹窗，返回 Promise<string|null> */
export function showRadioModal({ title, options, defaultValue }) {
    return new Promise((resolve) => {
        const radios = options.map(([val, label]) => `
            <div class="form-check mb-2">
                <input class="form-check-input" type="radio" name="bs-modal-radio" id="bs-radio-${val}" value="${val}" ${val === defaultValue ? 'checked' : ''}>
                <label class="form-check-label" for="bs-radio-${val}">${label}</label>
            </div>`).join('');
        const footer = `
            <button type="button" class="btn btn-link btn-sm text-decoration-none text-muted modal-cancel" data-bs-dismiss="modal">取消</button>
            <button type="button" class="btn btn-primary btn-sm modal-confirm">确定</button>`;
        const { modal, modalEl } = _createModal({ title, bodyHtml: radios, footerHtml: footer });
        modalEl.querySelector('.modal-confirm').addEventListener('click', () => {
            const checked = modalEl.querySelector('input[name="bs-modal-radio"]:checked');
            modal.hide();
            resolve(checked ? checked.value : null);
        });
        modalEl.addEventListener('hidden.bs.modal', () => resolve(null));
    });
}

/** 自定义表单弹窗，onConfirm(modalEl) 返回表单数据，onShow(modalEl) 弹窗显示后调用，返回 Promise<any|null> */
export function showFormModal({ title, formHtml, confirmText = '确定', cancelText = '取消', onConfirm, onShow }) {
    return new Promise((resolve) => {
        const footer = `
            <button type="button" class="btn btn-link btn-sm text-decoration-none text-muted modal-cancel">${cancelText}</button>
            <button type="button" class="btn btn-primary btn-sm modal-confirm">${confirmText}</button>`;
        const { modal, modalEl } = _createModal({ title, bodyHtml: formHtml, footerHtml: footer });
        if (typeof onShow === 'function') onShow(modalEl);
        modalEl.querySelector('.modal-confirm').addEventListener('click', () => {
            let data = null;
            if (typeof onConfirm === 'function') {
                data = onConfirm(modalEl);
                if (data === false) return; // 校验不通过，不关闭
            }
            modal.hide();
            resolve(data);
        });
        modalEl.addEventListener('hidden.bs.modal', () => resolve(null));
    });
}

/**
 * 通用：计算允许买入数量（按手取整）
 * 止损价>=成交价时仅按现金计算
 * @param {number} price - 成交价
 * @param {number} stopPrice - 止损价
 * @param {number} cash - 可用现金
 * @param {number} riskBudget - 剩余风险额度（allowance - risk）
 * @returns {number} 股数（100的整数倍）
 */
export function calcAllowedQty(price, stopPrice, cash, riskBudget, intent='B') {
    const p = parseFloat(price) || 0;
    const s = parseFloat(stopPrice) || 0;
    if (p <= 0) return 0;
    const byCash = cash > 0 ? Math.floor(cash / p) : 0;
    let riskPerShare;
    if (intent === 'S') {
        // 卖出：风险 = (止损价 - 成交价)
        riskPerShare = s - p;
    } else {
        // 买入：风险 = (成交价 - 止损价)
        riskPerShare = p - s;
    }
    if (riskPerShare <= 0) return Math.floor(byCash / 100) * 100;
    const byRisk = riskBudget > 0 ? Math.floor(riskBudget / riskPerShare) : 0;
    return Math.floor(Math.min(byCash, byRisk) / 100) * 100;
}

/**
 * 通用：计算盈利机会（0-99）
 * 买入：(目标价 - 成交价) / (目标价 - 止损价) × 99
 * 卖出：(成交价 - 目标价) / (止损价 - 目标价) × 99
 * @param {number} price - 成交价
 * @param {number} targetPrice - 目标价
 * @param {number} stopPrice - 止损价
 * @param {string} intent - 'B'买入 / 'S'卖出
 * @returns {number} 盈利机会百分比
 */
export function calcWinRatio(price, targetPrice, stopPrice, intent='B') {
    const p = parseFloat(price) || 0;
    const t = parseFloat(targetPrice) || 0;
    const s = parseFloat(stopPrice) || 0;
    if (p <= 0) return 0;
    if (intent === 'S') {
        // 卖出：止损价 > 成交价 > 目标价
        if (s <= p) return 99;
        if (t >= p) return 0;
        return Math.max(0, Math.min(99, Math.round((p - t) / (s - t) * 99)));
    } else {
        // 买入：目标价 > 成交价 > 止损价
        if (t <= p) return 0;
        if (s >= p) return 99;
        return Math.max(0, Math.min(99, Math.round((t - p) / (t - s) * 99)));
    }
}
