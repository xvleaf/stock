/**
 * 全站参数设置页面 JS
 * - 失焦自动确认保存
 * - 单字段AJAX提交
 */
import { baseInit } from "/static/base/js/base.js";
import { showAlert, showConfirm, getCsrfToken } from "/static/stock/js/func.js";

// 字段中文名映射
const FIELD_LABELS = {
    'icp_number': '备案编号',
    'icp_website': '备案官网',
    'default_page_size': '分页默认数量',
    'quote_interval': '行情刷新间隔',
    'cash_stat_start': '资金统计起始',
    'cash_stat_end': '资金统计结束',
    'review_stat_start': '复盘统计起始',
    'review_stat_end': '复盘统计结束',
    'commission_ratio': '佣金费率',
    'commission_min': '最低佣金',
    'stamp_buy_ratio': '印花税率（买入）',
    'stamp_sell_ratio': '印花税率（卖出）',
    'transfer_fee_sh': '过户费（沪市）',
    'transfer_fee_sz': '过户费（深市）',
    'transfer_fee_bj': '过户费（北交所）',
    'dividend_tax_long': '分红税（持股 > 1年）',
    'dividend_tax_mid': '分红税（持股 ≥ 1月）',
    'dividend_tax_short': '分红税（持股 < 1月）',
    'trade_am_start': '上午开始时间',
    'trade_am_end': '上午结束时间',
    'trade_pm_start': '下午开始时间',
    'trade_pm_end': '下午结束时间',
    'kline_start_date_day': '日线起始日期',
    'kline_start_date_week': '周线起始日期',
    'kline_start_date_month': '月线起始日期',
    'kline_ma_day': '日线MA周期',
    'kline_ma_week': '周线MA周期',
    'kline_ma_month': '月线MA周期',
    'kline_mv_day': '日线MV周期',
    'kline_mv_week': '周线MV周期',
    'kline_mv_month': '月线MV周期',
    'kline_ema_k_day': '日线EMA-K值',
    'kline_ema_k_week': '周线EMA-K值',
    'kline_ema_k_month': '月线EMA-K值',
    'kline_ema_d_day': '日线EMA-D值',
    'kline_ema_d_week': '周线EMA-D值',
    'kline_ema_d_month': '月线EMA-D值',
    'density_max': 'K线最大密度',
    'density_std': 'K线标准密度',
    'density_min': 'K线最小密度',
    // 界面配置 - 通用布局
    'stock_chart_visible': '股票图表',
    'nav_locked_screen_height': '导航栏隐藏阈值',
    'gap_height': '导航间隔',
    'nav_height': '导航高度（桌面）',
    'nav_height_mobile': '导航高度（移动）',
    'navi_bar_height': '底部导航高度',
    // 界面配置 - 内容布局
    'mobile_breakpoint': '移动断点',
    'w1': '宽度一（正常）',
    'bp1': '断点一',
    'w2': '宽度二（正常）',
    'bp2': '断点二',
    'w3': '宽度三（正常）',
    'bp3': '断点三',
    'w4': '宽度四（正常）',
    // 界面配置 - 图表布局
    'h1l': '高度一（正常横屏）',
    'h2l': '高度二（正常横屏）',
    'h3l': '高度三（正常横屏）',
    'h4l': '高度四（正常横屏）',
    'h1': '高度一（正常竖屏）',
    'h2': '高度二（正常竖屏）',
    'h3': '高度三（正常竖屏）',
    'h4': '高度四（正常竖屏）',
    'w5': '宽度一（全屏）',
    'w6': '宽度二（全屏）',
    'w7': '宽度三（全屏）',
    'w8': '宽度四（全屏）',
    'h5': '高度一（全屏）',
    'h6': '高度二（全屏）',
    'h7': '高度三（全屏）',
    'h8': '高度四（全屏）',
    'cash_chart_height': '资金曲线高度',
    'chart_vertical_align_fullscreen': '高度对齐（全屏）',
    'trend_main_ratio': '分时主图比例',
    'kline_main_ratio': 'K线主图比例',
};

function getFieldLabel(fieldName) {
    return FIELD_LABELS[fieldName] || fieldName;
}

export function initSetting(saved = false, error = false) {
    const init = () => {
        baseInit();
        if (saved) {
            showAlert({ text: '参数设置已保存。', type: 'success' });
        }
        if (error) {
            showAlert({ text: '数据输入有误。', type: 'error' });
        }

        // 通过 id 选择表单，避免选错其他 form
        const form = document.getElementById('settingForm');
        if (!form) return;

        const inputs = form.querySelectorAll('input[name], select[name]');

        // 记录每个输入框的原始值
        inputs.forEach(input => {
            input.dataset.original = input.value;
        });

        // 失焦处理
        inputs.forEach(input => {
            input.addEventListener('blur', async () => {
                // 禁用状态不处理
                if (input.disabled) return;

                const fieldName = input.name;
                const oldValue = input.dataset.original;
                const newValue = input.value.trim();

                // 值未变化，不处理
                if (newValue === oldValue) return;

                const label = getFieldLabel(fieldName);

                // 字段值中文映射
                const VALUE_LABELS = {
                    'stock_chart_visible': {'true': '显示', 'false': '隐藏'},
                    'chart_vertical_align_fullscreen': {'flex-start': '顶部', 'center': '居中', 'flex-end': '底部'},
                };
                const displayOld = VALUE_LABELS[fieldName] ? (VALUE_LABELS[fieldName][oldValue] || oldValue) : oldValue;
                const displayNew = VALUE_LABELS[fieldName] ? (VALUE_LABELS[fieldName][newValue] || newValue) : newValue;

                // 弹出确认对话框
                const confirmed = await showConfirm({
                    title: '确认修改',
                    text: `确认「${label}」由"${displayOld}"改为"${displayNew}"吗？`,
                    confirmText: '确认',
                    cancelText: '取消',
                });

                if (!confirmed) {
                    // 用户取消，还原输入框
                    input.value = oldValue;
                    return;
                }

                // 确认后，AJAX提交
                try {
                    const formData = new FormData();
                    formData.append('field', fieldName);
                    formData.append('value', newValue);
                    formData.append('csrfmiddlewaretoken', getCsrfToken());

                    const response = await fetch('/setting/save', {
                        method: 'POST',
                        body: formData,
                    });
                    const result = await response.json();

                    if (result.success) {
                        input.dataset.original = newValue;
                        showAlert({ text: `${label}已保存。`, type: 'success' });
                    } else {
                        input.value = oldValue;
                        showAlert({ text: result.error || '保存失败', type: 'error' });
                    }
                } catch (e) {
                    input.value = oldValue;
                    showAlert({ text: '网络请求失败', type: 'error' });
                }
            });

            // 输入时清除错误状态
            input.addEventListener('input', () => {
                input.classList.remove('is-invalid');
            });
        });

        // 恢复滚动位置
        const savedScroll = sessionStorage.getItem('setting-scroll');
        if (savedScroll) {
            window.scrollTo(0, parseInt(savedScroll, 10));
            sessionStorage.removeItem('setting-scroll');
        }

        // 滚动时保存位置
        let scrollTimer = null;
        window.addEventListener('scroll', () => {
            clearTimeout(scrollTimer);
            scrollTimer = setTimeout(() => {
                sessionStorage.setItem('setting-scroll', window.scrollY.toString());
            }, 100);
        });
    };

    // 模块脚本可能在 DOMContentLoaded 之后执行，需要检查 readyState
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}
