import { refreshQuotes, chartPageContainer, setPageConfig, initChartPage } from './func.js';

export function initSectorList() {
    const tbody = document.getElementById('stockBody');
    if (!tbody) return;

    refreshQuotes('/sector/list', tbody);
}

export function initSectorView(config) {
    const initChart = config.initChart || {};
    setPageConfig(initChart);

    if (chartPageContainer) {
        chartPageContainer.classList.remove('d-none');
        initChartPage();
    }
}
