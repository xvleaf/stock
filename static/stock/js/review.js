/**
 * 复盘模块 JS（详情页）
 * 列表页分页统一使用 list.js 的 initPagination，不再在本文件重复实现。
 */
import { postRequest, showAlert, showConfirm, priceDecimalsByCat } from './utils.js';
import { chartPageContainer, initChartPage, setPageConfig, pageConfig } from './chart.js';

// ========== 复盘详情 ==========
export function initReviewView(opts) {
    const { review_type, review_id, init_chart } = opts;

    const ratingSelect = document.getElementById('reviewRating');
    // 备注输入框：交易模式用 trans_comments，关注模式用 id_comments
    const commentsTextarea = document.getElementById(review_type === 'trans' ? 'trans_comments' : 'id_comments');

    // 保存原始值用于取消恢复
    let originalRating = ratingSelect ? ratingSelect.value : '';
    let originalComments = commentsTextarea ? commentsTextarea.value : '';

    // 保存汇总页面备注初始值，切换回汇总模式时恢复
    window._reviewSummaryComments = originalComments;

    // 根据 cat 类型格式化价格小数位
    function formatPricesByCat(cat) {
        const decimals = priceDecimalsByCat(cat);
        const priceFields = review_type === 'trans'
            ? ['trans_price', 'trans_amount', 'trans_profit', 'trans_target_price',
               'trans_stop_price', 'trans_risk_amount']
            : ['id_plan_price', 'id_target_price', 'id_stop_price'];
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

    // 保存评级和备注（汇总模式 → ReviewList 表）
    function saveData(rating, comments) {
        if (!review_id) return;
        postRequest('/review/save', { review_id, rating, comments }).then(result => {
            if (result && result.status === 'ok') {
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
            const originalText = originalRating
                ? ratingSelect.querySelector(`option[value="${originalRating}"]`)?.text
                : '未评级';
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

    // 保存历史记录备注（历史模式 → history 表）
    function saveHistoryComment(history_id, history_type, comments) {
        postRequest('/review/save-history-comment', { history_id, history_type, comments })
            .then(result => {
                if (result && result.success) {
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
        if (review_id) pageConfig.navi_id = review_id;
        if (chartPageContainer) {
            chartPageContainer.classList.remove('d-none');
            initChartPage();
        }
    }
}
