/**
 * 全站参数设置页面 JS
 */
import { baseInit } from "/static/base/js/base.js";
import { showAlert } from "/static/stock/js/func.js";

// 需要验证的字段配置
const FIELDS = [
    // 通用设置
    { name: 'icp_number', label: '备案编号', type: 'text' },
    { name: 'icp_website', label: '备案官网', type: 'text' },
    { name: 'default_page_size', label: '分页默认数量', type: 'int' },
    { name: 'quote_interval', label: '行情刷新间隔', type: 'int' },
    // 交易费用
    { name: 'commission_ratio', label: '佣金费率', type: 'num' },
    { name: 'commission_min', label: '最低佣金', type: 'num' },
    { name: 'stamp_buy_ratio', label: '印花税率（买入）', type: 'num' },
    { name: 'stamp_sell_ratio', label: '印花税率（卖出）', type: 'num' },
    // 过户费用
    { name: 'transfer_fee_sh', label: '过户费（沪市）', type: 'num' },
    { name: 'transfer_fee_sz', label: '过户费（深市）', type: 'num' },
    { name: 'transfer_fee_bj', label: '过户费（北交所）', type: 'num' },
    // 分红税率
    { name: 'dividend_tax_long', label: '分红税（持股 > 1年）', type: 'num' },
    { name: 'dividend_tax_mid', label: '分红税（持股 ≥ 1月）', type: 'num' },
    { name: 'dividend_tax_short', label: '分红税（持股 < 1月）', type: 'num' },
    // 交易时间
    { name: 'trade_am_start', label: '上午开始时间', type: 'time' },
    { name: 'trade_am_end', label: '上午结束时间', type: 'time' },
    { name: 'trade_pm_start', label: '下午开始时间', type: 'time' },
    { name: 'trade_pm_end', label: '下午结束时间', type: 'time' },
    // K线起始日期
    { name: 'kline_start_date_day', label: '日线起始日期', type: 'date' },
    { name: 'kline_start_date_week', label: '周线起始日期', type: 'date' },
    { name: 'kline_start_date_month', label: '月线起始日期', type: 'date' },
    // K线MA周期
    { name: 'kline_ma_day', label: '日线MA周期', type: 'int' },
    { name: 'kline_ma_week', label: '周线MA周期', type: 'int' },
    { name: 'kline_ma_month', label: '月线MA周期', type: 'int' },
    // K线MV周期
    { name: 'kline_mv_day', label: '日线MV周期', type: 'int' },
    { name: 'kline_mv_week', label: '周线MV周期', type: 'int' },
    { name: 'kline_mv_month', label: '月线MV周期', type: 'int' },
    // K线EMA-K值
    { name: 'kline_ema_k_day', label: '日线EMA-K值', type: 'int' },
    { name: 'kline_ema_k_week', label: '周线EMA-K值', type: 'int' },
    { name: 'kline_ema_k_month', label: '月线EMA-K值', type: 'int' },
    // K线EMA-D值
    { name: 'kline_ema_d_day', label: '日线EMA-D值', type: 'int' },
    { name: 'kline_ema_d_week', label: '周线EMA-D值', type: 'int' },
    { name: 'kline_ema_d_month', label: '月线EMA-D值', type: 'int' },
];

function validateForm(form) {
    const errors = [];
    const numRegex = /^\d+(\.\d+)?$/;
    const intRegex = /^\d+$/;
    const dateRegex = /^\d{8}$/;
    const timeRegex = /^\d{2}:\d{2}$/;

    for (const field of FIELDS) {
        const input = form.querySelector(`[name="${field.name}"]`);
        if (!input) continue;
        const value = input.value.trim();
        // text 类型允许为空
        if (field.type === 'text') {
            input.classList.remove('is-invalid');
            continue;
        }
        // 检查是否为空
        if (value === '') {
            errors.push(`${field.label}不能为空`);
            input.classList.add('is-invalid');
            continue;
        }
        // 按类型校验
        let valid = false;
        let errorMsg = '格式错误';
        if (field.type === 'num') {
            valid = numRegex.test(value);
            errorMsg = '请输入数字';
        } else if (field.type === 'int') {
            valid = intRegex.test(value);
            errorMsg = '请输入整数';
        } else if (field.type === 'date') {
            valid = dateRegex.test(value);
            errorMsg = '请输入YYYYMMDD格式';
        } else if (field.type === 'time') {
            valid = timeRegex.test(value);
            errorMsg = '请输入HH:MM格式';
        }
        if (!valid) {
            errors.push(`${field.label}${errorMsg}`);
            input.classList.add('is-invalid');
            continue;
        }
        input.classList.remove('is-invalid');
    }
    return errors;
}

export function initSetting(saved = false, error = false) {
    document.addEventListener('DOMContentLoaded', () => {
        baseInit();
        if (saved) {
            showAlert({ text: '参数设置已保存。', type: 'success' });
        }
        if (error) {
            showAlert({ text: '数据输入有误。', type: 'error' });
        }

        const form = document.querySelector('form');
        if (form) {
            form.addEventListener('submit', (e) => {
                const errors = validateForm(form);
                if (errors.length > 0) {
                    e.preventDefault();
                    showAlert({
                        title: '请检查以下内容',
                        text: errors.join('；'),
                        type: 'warning'
                    });
                }
            });

            // 输入时清除错误状态
            form.querySelectorAll('input').forEach(input => {
                input.addEventListener('input', () => {
                    input.classList.remove('is-invalid');
                });
            });
        }
    });
}
