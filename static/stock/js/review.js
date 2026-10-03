/**
 * 复盘模块 JS
 */
import { getCsrfToken, showAlert, showConfirm } from './func.js';
import { chartPageContainer, initChartPage, setPageConfig, pageConfig } from './chart.js';

// ========== 复盘列表 ==========
export function initReviewList(postUrl, reviewType) {
    const pag = document.querySelector('.list-pagination');
    if (!pag) return;

    function saveAndReload(patch) {
        fetch(postUrl, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify(patch),
        }).then(() => { window.location.reload(); });
    }

    // 分页：上一页/下一页
    pag.querySelector('.page-prev')?.addEventListener('click', (e) => {
        if (e.currentTarget.disabled) return;
        saveAndReload({ page: parseInt(e.currentTarget.dataset.page) });
    });
    pag.querySelector('.page-next')?.addEventListener('click', (e) => {
        if (e.currentTarget.disabled) return;
        saveAndReload({ page: parseInt(e.currentTarget.dataset.page) });
    });

    // 每页数量
    const sizeInput = pag.querySelector('.page-size-input');
    if (sizeInput) {
        const originalSize = parseInt(sizeInput.dataset.size);
        const doSubmit = () => {
            let val = parseInt(sizeInput.textContent.trim());
            if (isNaN(val) || val < 1) {
                showAlert({ title: '提示', text: '请输入有效的正整数', type: 'warning' });
                sizeInput.textContent = originalSize;
                return;
            }
            sizeInput.textContent = val;
            if (val === originalSize) return;
            saveAndReload({ per_page: val, page: 1 });
        };
        sizeInput.addEventListener('blur', doSubmit);
        sizeInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); sizeInput.blur(); }
        });
    }

    // 页码跳转
    const jumpInput = pag.querySelector('.page-jump-input');
    if (jumpInput) {
        const original = parseInt(jumpInput.dataset.page);
        const doJump = () => {
            let val = parseInt(jumpInput.textContent.trim());
            if (isNaN(val) || val < 1) val = 1;
            const max = parseInt(jumpInput.dataset.max);
            if (max && val > max) val = max;
            jumpInput.textContent = val;
            if (val === original) return;
            saveAndReload({ page: val });
        };
        jumpInput.addEventListener('blur', doJump);
        jumpInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') { e.preventDefault(); jumpInput.blur(); }
        });
    }
}


// ========== 复盘详情 ==========
export function initReviewView(opts) {
    const { review_type, review_id, history_count, history_list, prev_item, next_item, site, init_chart } = opts;

    const ratingSelect = document.getElementById('reviewRating');
    // 备注输入框：交易模式用 trans_comments，关注模式用 id_comments
    const commentsTextarea = document.getElementById(review_type === 'trans' ? 'trans_comments' : 'id_comments');

    // 保存原始值用于取消恢复
    let originalRating = ratingSelect ? ratingSelect.value : '';
    let originalComments = commentsTextarea ? commentsTextarea.value : '';

    // 保存汇总页面的备注初始值，切换回汇总模式时恢复
    window._reviewSummaryComments = originalComments;

    // 根据 cat 类型格式化价格小数点位数
    function getDecimalsByCat(cat) {
        if (cat === 'fund' || cat === 'bond') return 3;
        return 2;
    }
    function formatPricesByCat(cat) {
        const decimals = getDecimalsByCat(cat);
        let priceFields;
        if (review_type === 'trans') {
            priceFields = ['trans_price', 'trans_amount', 'trans_profit', 'trans_target_price',
                           'trans_stop_price', 'trans_risk_amount'];
        } else {
            priceFields = ['id_plan_price', 'id_target_price', 'id_stop_price'];
        }
        priceFields.forEach(id => {
            const el = document.getElementById(id);
            if (el && el.value !== '' && !isNaN(parseFloat(el.value))) {
                el.value = parseFloat(el.value).toFixed(decimals);
            }
        });
    }
    if (init_chart && init_chart.cat) {
        formatPricesByCat(init_chart.cat);
    }

    // 保存评级和备注
    function saveData(rating, comments) {
        if (!review_id) return;
        fetch('/review/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify({ review_id, rating, comments }),
        }).then(r => r.json()).then(data => {
            if (data.status === 'ok') {
                showAlert({ title: '提示', text: '保存成功', type: 'success' });
                originalRating = rating;
                originalComments = comments;
            }
        });
    }

    // 评级变更确认
    if (ratingSelect) {
        ratingSelect.addEventListener('change', async () => {
            const newRating = ratingSelect.value;
            if (newRating === originalRating) return;
            const ratingText = ratingSelect.options[ratingSelect.selectedIndex].text;
            const originalText = originalRating ? ratingSelect.querySelector(`option[value="${originalRating}"]`)?.text : '未评级';
            const confirmed = await showConfirm({
                title: '确认修改',
                text: `确认将评级由"${originalText}"改为"${ratingText}"吗？`,
                confirmText: '确认',
                cancelText: '取消'
            });
            if (confirmed) {
                saveData(newRating, commentsTextarea ? commentsTextarea.value : '');
            } else {
                ratingSelect.value = originalRating;
            }
        });
    }

    // 保存历史记录备注
    function saveHistoryComment(history_id, history_type, comments) {
        fetch('/review/save-history-comment', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken()},
            body: JSON.stringify({ history_id, history_type, comments }),
        }).then(r => r.json()).then(data => {
            if (data.status === 'ok') {
                showAlert({ title: '提示', text: '保存成功', type: 'success' });
                originalComments = comments;
            }
        });
    }

    // 备注失焦确认
    if (commentsTextarea) {
        let focusStartValue = '';
        commentsTextarea.addEventListener('focus', () => {
            focusStartValue = commentsTextarea.value;
        });
        commentsTextarea.addEventListener('blur', async () => {
            const newComments = commentsTextarea.value;
            // 内容没变不弹窗
            if (newComments === focusStartValue) return;
            const confirmed = await showConfirm({
                title: '确认修改',
                text: '确认保存备注修改吗？',
                confirmText: '确认',
                cancelText: '取消'
            });
            if (confirmed) {
                // 检查是否在历史模式
                const form = document.getElementById(review_type === 'trans' ? 'transViewForm' : 'focusForm');
                const history_id = form ? form.dataset.historyId : null;
                const history_type = form ? form.dataset.historyType : null;
                if (history_id) {
                    // 历史模式：保存到 history 表
                    saveHistoryComment(history_id, history_type || 'trans', newComments);
                } else {
                    // 汇总模式：保存到 ReviewList 表
                    saveData(ratingSelect ? ratingSelect.value : '', newComments);
                }
                focusStartValue = newComments;
            } else {
                // 取消时保留当前备注框中的内容，不恢复原始值
                focusStartValue = newComments;
            }
        });
    }

    // 初始化图表
    if (init_chart) {
        setPageConfig(init_chart);
        // 设置当前 review_id，供 navi 切换时更新 URL
        if (review_id) {
            pageConfig.navi_id = review_id;
        }
        if (chartPageContainer) {
            chartPageContainer.classList.remove('d-none');
            initChartPage();
        }
    }
}
