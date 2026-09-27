/**
 * 全站参数设置页面 JS
 */
import { baseInit } from "/static/base/js/base.js";
import { showAlert } from "/static/stock/js/func.js";

export function initSetting(saved = false) {
    document.addEventListener('DOMContentLoaded', () => {
        baseInit();
        if (saved) {
            showAlert({ text: '参数设置已保存。', type: 'success' });
        }
    });
}
