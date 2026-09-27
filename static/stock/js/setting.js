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
    // 界面配置 - 导航栏
    'nav_locked': '锁定导航栏',
    'screen_height_threshold': '高度阈值',
    'nav_height': '导航高度（桌面）',
    'nav_height_mobile': '导航高度（移动）',
    'gap_height': '导航间隔',
    'navi_bar_height': '底部导航高度',
    // 界面配置 - 内容布局
    'mobile_breakpoint': '移动断点',
    'w1': '页面宽度一',
    'bp1': '断点一',
    'w2': '页面宽度二',
    'bp2': '断点二',
    'w3': '页面宽度三',
    'bp3': '断点三',
    'w4': '页面宽度四',
    // 界面配置 - 图表布局
    'h1': '高度一',
    'h2': '高度二',
    'h3': '高度三',
    'h4': '高度四',
    'cash_chart_height': '资金曲线高度',
    'chart_placeholder_height': '图表最小高度',
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

        // 锁定导航栏与高度阈值联动
        const navLockedSelect = form.querySelector('select[name="nav_locked"]');
        const heightThresholdInput = document.getElementById('id_screen_height_threshold');
        const updateHeightThresholdState = () => {
            if (navLockedSelect && heightThresholdInput) {
                const locked = navLockedSelect.value === 'true';
                heightThresholdInput.disabled = locked;
                if (locked) {
                    heightThresholdInput.dataset.original = heightThresholdInput.value;
                }
            }
        };
        updateHeightThresholdState();
        if (navLockedSelect) {
            navLockedSelect.addEventListener('change', updateHeightThresholdState);
        }

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

                // bool 字段值转换为中文显示
                const BOOL_FIELDS = {'nav_locked': true};
                const displayOld = BOOL_FIELDS[fieldName] ? (oldValue === 'true' ? '是' : '否') : oldValue;
                const displayNew = BOOL_FIELDS[fieldName] ? (newValue === 'true' ? '是' : '否') : newValue;

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
                    // 恢复联动状态（如锁定导航栏取消后恢复高度阈值可用）
                    if (fieldName === 'nav_locked') {
                        updateHeightThresholdState();
                    }
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
