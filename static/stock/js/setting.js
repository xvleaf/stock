/**
 * 全站参数设置页面 JS
 */
import { baseInit } from "/static/base/js/base.js";
import { showAlert } from "/static/stock/js/func.js";

// 需要验证的字段配置
const FIELDS = [
    { name: 'commission_ratio', label: '佣金费率' },
    { name: 'commission_min', label: '最低佣金' },
    { name: 'stamp_buy_ratio', label: '印花税率（买入）' },
    { name: 'stamp_sell_ratio', label: '印花税率（卖出）' },
    { name: 'transfer_fee_sh', label: '过户费（沪市）' },
    { name: 'transfer_fee_sz', label: '过户费（深市）' },
    { name: 'transfer_fee_bj', label: '过户费（北交所）' },
    { name: 'dividend_tax_long', label: '分红税（持股 > 1年）' },
    { name: 'dividend_tax_mid', label: '分红税（持股 ≥ 1月）' },
    { name: 'dividend_tax_short', label: '分红税（持股 < 1月）' },
];

function validateForm(form) {
    const errors = [];
    // 严格数字正则：允许整数和小数，不允许字母等非法字符
    const numRegex = /^\d+(\.\d+)?$/;
    for (const field of FIELDS) {
        const input = form.querySelector(`[name="${field.name}"]`);
        if (!input) continue;
        const value = input.value.trim();
        // 检查是否为空
        if (value === '') {
            errors.push(`${field.label}不能为空`);
            input.classList.add('is-invalid');
            continue;
        }
        // 严格检查是否为有效数字（纯数字，不允许字母等）
        if (!numRegex.test(value)) {
            errors.push(`${field.label}格式错误，请输入数字`);
            input.classList.add('is-invalid');
            continue;
        }
        // 检查是否为负数
        const num = parseFloat(value);
        if (num < 0) {
            errors.push(`${field.label}不能为负数`);
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
