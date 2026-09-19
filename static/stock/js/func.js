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
export function showAlert({ title, text, type = 'info', autoClose = 2000 }) {
    const iconMap = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    const bodyHtml = `<div class="text-center"><div class="fs-2 mb-2">${iconMap[type] || ''}</div><p class="mb-0 fw-bold">${title || ''}</p>${text ? `<p class="mb-0 text-muted small">${text}</p>` : ''}</div>`;
    const { modal } = _createModal({ title: '', bodyHtml, footerHtml: '' });
    if (autoClose > 0) {
        setTimeout(() => modal.hide(), autoClose);
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
