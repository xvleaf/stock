// ===================== 模块状态 =====================
export let priceDecimal = 2;

export function setPriceDecimal(val) {
    priceDecimal = Number(val) || 2;
}

// ===================== CSRF / HTTP =====================
export function getCsrfToken() {
    const cookie = document.cookie.split(';')
        .map(c => c.trim())
        .find(c => c.startsWith('csrftoken='));
    return cookie ? decodeURIComponent(cookie.split('=')[1]) : '';
}

/**
 * 统一 JSON POST：自动注入 CSRF、序列化、收敛异常。
 * 成功（2xx）返回解析后的 JSON；非 2xx 也尽量返回错误体（通常含 error/message），
 * 以便调用方提示后端报错；无法解析或网络异常时返回 null。
 */
export async function postRequest(url, data) {
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify(data),
        });
        const text = await response.text();
        let payload = null;
        if (text) {
            try { payload = JSON.parse(text); } catch { payload = null; }
        }
        if (!response.ok) {
            console.error(`请求失败：${url}，状态码 ${response.status}`);
        }
        return payload;
    } catch (err) {
        console.error('接口请求异常：', err);
        return null;
    }
}

/**
 * 先 POST 记录来源（set_back），再跳转到目标页；记录来源失败也照常跳转。
 * @param {string} fetchUrl - 接收 set_back 的 POST 地址
 * @param {string} backValue - 来源 URL
 * @param {string} goUrl - 跳转目标
 */
export async function setBackAndGo(fetchUrl, backValue, goUrl) {
    await postRequest(fetchUrl, { set_back: backValue });
    window.location.href = goUrl;
}

// ===================== 通用纯工具 =====================
/** HTML 转义，防止用户可控文本插入 innerHTML 造成 XSS */
export function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

/** 按类别返回价格小数位（基金/债券 3 位，其余 2 位） */
export function priceDecimalsByCat(cat) {
    return (cat === 'fund' || cat === 'bond') ? 3 : 2;
}

/** 通用防抖 */
export function debounce(fn, delay = 16) {
    let timer = null;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), delay);
    };
}

// ===================== 行情刷新 =====================
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

// ===================== 图表错误提示 =====================
export function showChartError(text) {
    const errText = document.getElementById('errorText');
    if (errText) {
        errText.textContent = text;
        errText.classList.remove('d-none');
    }
}

// ===================== updateFormData（编排 + 子函数） =====================
export function updateFormData(data) {
    _fillNameCode(data);
    _fillFocusFields(data);
    _fillChoiceFields(data);
    _fillTransFields(data);
    _updatePilotIndicators(data);
    _applyHistoryMode(data);
    _fillReviewFields(data);
    _updatePilotButtons(data);
    _syncHistoryMeta(data);
}

/** 顶部名称、代码 */
function _fillNameCode(data) {
    const nameItem = document.getElementById('nameItem');
    const codeItem = document.getElementById('codeItem');
    if (nameItem) nameItem.textContent = data.name || '';
    if (codeItem) codeItem.textContent = data.code || '';
}

/** focus 表单可编辑字段（金额按 cat 格式化） */
function _fillFocusFields(data) {
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
    const amountFields = ['id_plan_price', 'id_target_price', 'id_stop_price'];
    const deci = priceDecimalsByCat(data.cat);

    for (const [id, key] of Object.entries(fieldMap)) {
        const el = document.getElementById(id);
        if (el && data[key] !== undefined) {
            let value = data[key];
            if (amountFields.includes(id) && value !== '' && value !== null && !isNaN(value)) {
                value = parseFloat(value).toFixed(deci);
            }
            el.value = value;
        }
    }
}

/** 市场 / 类别 / 交易方向（下拉或只读） */
function _fillChoiceFields(data) {
    _setChoice('market_choice', data, { valueKey: 'market', displayKey: 'market_display', fallback: 'SH' });
    _setChoice('cat_choice', data, { valueKey: 'cat', displayKey: 'cat_display', fallback: 'stock' });
    _setChoice('intent_choice', data, {
        valueKey: 'intent',
        fallback: 'B',
        toText: d => d.intent === 'B' ? '买入' : '卖出',
    });
}

function _setChoice(name, data, { valueKey, displayKey, fallback, toText }) {
    const sel = document.querySelector(`[name="${name}"]`);
    if (sel) {
        if (sel.tagName === 'SELECT') {
            sel.value = data[valueKey] ?? fallback;
        } else {
            sel.value = toText ? toText(data) : (data[displayKey] ?? '');
        }
    }
    const ro = document.getElementById(`id_${name}`);
    if (ro && ro.readOnly) {
        ro.value = toText ? toText(data) : (data[displayKey] ?? '');
    }
}

/** 交易详情（trans-view）字段 */
function _fillTransFields(data) {
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
    const amountFields = ['trans_price', 'trans_amount', 'trans_profit', 'trans_target_price',
        'trans_stop_price', 'trans_risk_amount', 'trans_deal_price', 'trans_total_profit'];
    const deci = priceDecimalsByCat(data.cat);

    for (const [id, key] of Object.entries(transFieldMap)) {
        const el = document.getElementById(id);
        if (el && data[key] !== undefined) {
            let value = data[key];
            if (amountFields.includes(id) && value !== '' && value !== null && !isNaN(value)) {
                value = parseFloat(value).toFixed(deci);
            }
            el.value = value;
        }
    }
}

/** trans / focus 历史指示器 */
function _updatePilotIndicators(data) {
    // trans 指示器
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
            pilotIndicator.textContent = pilotIndicatorText({
                idx: isSummary ? 1 : (data.pilot_idx + 1),
                total: data.pilot_total,
                date: data.pilot_date,
                action: data.pilot_action,
                qty: data.pilot_qty,
                price: data.pilot_price,
                dividendAmount: data.pilot_dividend_amount,
            });
        }
    }

    // focus 指示器
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
}

/** 历史模式字段状态 + focus 字段灰化 + 复盘字段显隐 */
function _applyHistoryMode(data) {
    const isHistoryMode = data.is_summary === false || (data.pilot_idx !== undefined && data.pilot_idx >= 0);
    setTransHistoryState(isHistoryMode, !!data.is_close_trade);

    const fields = document.querySelectorAll('#focusForm input, #focusForm select, #focusForm textarea');
    if (isHistoryMode) {
        fields.forEach(el => {
            // 备注输入框不变灰，保持可编辑
            if (el.id === 'id_comments') return;
            el.style.color = '#6c757d';
        });
        const reviewRatingWrap = document.getElementById('reviewRatingWrap');
        if (reviewRatingWrap) reviewRatingWrap.classList.add('d-none');
        document.querySelectorAll('.review-only-fields').forEach(el => el.classList.add('d-none'));
    } else {
        fields.forEach(el => { el.style.color = ''; });
        const reviewRatingWrap = document.getElementById('reviewRatingWrap');
        if (reviewRatingWrap) reviewRatingWrap.classList.remove('d-none');
        document.querySelectorAll('.review-only-fields').forEach(el => el.classList.remove('d-none'));
    }
}

/** 复盘特有字段（建/平仓日期、全部收益、收益比例），收益按正负着色 */
function _fillReviewFields(data) {
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
}

/** pilot 上一页 / 下一页按钮可用态 */
function _updatePilotButtons(data) {
    if (data.pilotPrev !== undefined) {
        const pilotPrevItem = document.getElementById('pilotPrevItem');
        if (pilotPrevItem) pilotPrevItem.classList.toggle('disabled', !data.pilotPrev);
    }
    if (data.pilotNext !== undefined) {
        const pilotNextItem = document.getElementById('pilotNextItem');
        if (pilotNextItem) pilotNextItem.classList.toggle('disabled', !data.pilotNext);
    }
}

/** 表单 history 元数据、trans 历史类型切换、备注绑定/恢复 */
function _syncHistoryMeta(data) {
    const transForm = document.getElementById('transViewForm');
    const focusForm = document.getElementById('focusForm');
    const targetForm = transForm || focusForm;
    const isSummary = data.is_summary === true || data.pilot_idx === -1;

    if (targetForm) {
        if (data.history_id !== undefined) targetForm.dataset.historyId = data.history_id;
        if (data.history_type !== undefined) targetForm.dataset.historyType = data.history_type;
        // 汇总模式时清除
        if (isSummary) {
            delete targetForm.dataset.historyId;
            delete targetForm.dataset.historyType;
        }
    }

    // 复盘交易页：根据 history_type 切换 trans / focus 字段与左侧标签
    if (transForm) {
        const transFields = document.getElementById('transForm');
        const focusFieldsInTrans = document.getElementById('focusFieldsInTrans');
        const isFocusHistory = data.history_type === 'focus' && !isSummary;
        if (transFields) transFields.classList.toggle('d-none', isFocusHistory);
        if (focusFieldsInTrans) focusFieldsInTrans.classList.toggle('d-none', !isFocusHistory);

        const pilotLabelFirst = document.getElementById('pilotLabelFirst');
        if (pilotLabelFirst) pilotLabelFirst.textContent = isFocusHistory ? '关注' : '交易';
    }

    // 汇总模式恢复汇总备注并解绑失焦保存；历史模式绑定失焦保存（复盘页除外）
    if (isSummary) {
        if (transForm && window._reviewSummaryComments !== undefined) {
            const transComments = document.getElementById('trans_comments');
            if (transComments) transComments.value = window._reviewSummaryComments;
        }
        if (focusForm && window._reviewSummaryComments !== undefined) {
            const idComments = document.getElementById('id_comments');
            if (idComments) idComments.value = window._reviewSummaryComments;
        }
        _unbindHistoryCommentSave();
    } else {
        const isReviewPage = window.location.pathname.startsWith('/review/');
        if (!isReviewPage) _bindHistoryCommentSave();
    }
}

// ===================== 历史备注失焦保存 =====================
let _historyCommentHandler = null;
let _historyCommentOriginal = '';
let _historyCommentEl = null;

function _bindHistoryCommentSave() {
    const transComments = document.getElementById('trans_comments');
    const idComments = document.getElementById('id_comments');
    const el = transComments || idComments;
    if (!el) return;

    // 已绑定同一元素，仅更新原始值
    if (_historyCommentEl === el && _historyCommentHandler) {
        _historyCommentOriginal = el.value;
        return;
    }

    _unbindHistoryCommentSave();
    _historyCommentOriginal = el.value;
    _historyCommentEl = el;

    _historyCommentHandler = async () => {
        if (!_historyCommentEl) return;
        const newValue = _historyCommentEl.value;
        if (newValue === _historyCommentOriginal) return; // 内容没变不弹窗

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

            const result = await postRequest(url, { history_id: historyId, comments: newValue });
            if (result && result.success) {
                _historyCommentOriginal = newValue;
                showAlert({ title: '已保存', text: '备注已更新', type: 'success' });
            } else {
                showAlert({ title: '保存失败', text: (result && result.error) || '网络错误', type: 'error' });
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

// ===================== 滚动折叠（图表自适应） =====================
export function initScrollFold() {
    const handleScroll = debounce(() => {
        if (window.Highcharts) {
            const chart = window.Highcharts.charts.find(c => c);
            chart?.reflow();
        }
    });
    window.addEventListener('scroll', handleScroll, { passive: true });
}

// ===================== Bootstrap Modal 通用弹窗 =====================
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
    // Tabler Icons 线性描边图标（线宽约 1.5px）
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

/** 自定义表单弹窗：onConfirm(modalEl) 返回表单数据，返回 false 表示校验不通过不关窗；onShow(modalEl) 显示后调用 */
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

// ===================== Pilot 指示器 / 历史字段状态 =====================
/**
 * 生成 pilot 历史指示器文本（trans-view 初始化与 updateFormData 异步加载共用）
 */
export function pilotIndicatorText({ idx, total, date, action, qty, price, dividendAmount }) {
    const dateStr = date ? ` [${date}` : '';
    let actionStr;
    if (dividendAmount !== undefined && dividendAmount !== '') {
        const cash = Number(dividendAmount);
        const bonus = Number(qty || 0);
        if (cash > 0 && bonus > 0) actionStr = ` 分红${cash.toFixed(2)}元，送股${bonus}股]`;
        else if (cash > 0) actionStr = ` 分红${cash.toFixed(2)}元]`;
        else if (bonus > 0) actionStr = ` 送股${bonus}股]`;
        else actionStr = date ? ']' : '';
    } else {
        const qtyPriceStr = (qty && price !== '') ? `${qty}股@${price}元` : '';
        actionStr = action ? ` ${action}${qtyPriceStr}]` : (date ? ']' : '');
    }
    return `第 ${idx} / ${total} 笔${dateStr}${actionStr}`;
}

/**
 * 切换 trans 视图历史模式字段状态（trans-view 初始化与 updateFormData 共用）
 * @param {boolean} isHistory - 是否历史模式（false 为汇总模式）
 * @param {boolean} isCloseTrade - 历史模式下是否为清仓交易
 */
export function setTransHistoryState(isHistory, isCloseTrade = false) {
    // 只读字段：历史变灰，汇总恢复
    document.querySelectorAll('#transViewForm .readonly-field').forEach(el => {
        el.style.color = isHistory ? '#6c757d' : '';
    });
    // 复盘特有字段：历史隐藏，汇总显示
    document.querySelectorAll('.review-only-fields').forEach(el => el.classList.toggle('d-none', isHistory));
    // 仅历史模式字段：历史显示，汇总隐藏
    document.querySelectorAll('.trans-history-only').forEach(el => el.classList.toggle('d-none', !isHistory));
    // 评级下拉框（review 页面）：历史隐藏，汇总显示
    const reviewRatingWrap = document.getElementById('reviewRatingWrap');
    if (reviewRatingWrap) reviewRatingWrap.classList.toggle('d-none', isHistory);

    // 清仓交易字段（必须在 trans-history-only 处理之后）
    if (isHistory) {
        document.querySelectorAll('.trans-normal-history').forEach(el => el.classList.toggle('d-none', !!isCloseTrade));
        document.querySelectorAll('.trans-close-only').forEach(el => el.classList.toggle('d-none', !isCloseTrade));
    } else {
        // 汇总模式：隐藏清仓特有字段
        document.querySelectorAll('.trans-close-only').forEach(el => el.classList.add('d-none'));
    }
}
