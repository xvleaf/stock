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
    Swal.fire({
        title: title,
        text: message,
        icon: 'warning',
        width: 420,
        customClass: {
            popup: 'sweet-popup', 
            title: 'sweet-title'
        },
        showCancelButton: true,
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        confirmButtonColor: '#0d6efd',
        // cancelButtonColor: '#6c757d',
        preConfirm: () => {
            console.log('TEST');
        }
    }).then(result => {
        if (result.isConfirmed) {
            // 用户点击确认
            Swal.fire('已删除', '记录已成功删除', 'success');
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
