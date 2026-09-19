import { chartPageContainer, initChartPage, setPageConfig } from './chart.js';
import { refreshQuotes, showRadioModal, postRequest } from './func.js';

export function initSectorList(opts) {
    const tbody = document.getElementById('stockBody');
    if (!tbody) return;

    refreshQuotes('/sector/list', tbody);

    // 表头"标记"按钮：弹窗选择后 POST 提交，后端过滤+重新分页（与筛选清单一致）
    let currentMarkFilter = opts.currentMarkFilter || 'all';
    document.addEventListener('click', (e) => {
        const btn = e.target.closest('.mark-filter-btn');
        if (!btn) return;
        showRadioModal({
            title: '标记筛选',
            options: [['all', '全部'], ['1', '优选股'], ['2', '潜力股']],
            defaultValue: currentMarkFilter,
        }).then((value) => {
            if (value === null) return;
            currentMarkFilter = value;
            postRequest('/sector/list', { mark_filter: value }).then(() => {
                window.location.reload();
            });
        });
    });
}

export function initSectorView(config) {
    const initChart = config.initChart || {};
    setPageConfig(initChart);

    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }
}
