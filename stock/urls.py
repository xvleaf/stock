from django.urls import path
from . import chart, func, sector, focus, cash, filter, trans

urlpatterns = [
    # ---- 板块 ----
    path('sector/list', sector.sector_list, name='sector_list'),
    path('sector/view/<str:market>/<str:code>', sector.sector_view, name='sector_view'),
    path('sector/rebuild', sector.rebuild_stock_sector, name='rebuild_stock_sector'),
    path('stocks/list/<str:market>/<str:code>', sector.stocks_list, name='stocks_list'),
    path('stocks/sectors/<str:market>/<str:code>', sector.stock_sectors, name='stock_sectors'),

    # ---- 股票筛选 ----
    path('filter/list', filter.filter_list, name='filter_list'),
    path('filter/run', filter.filter_run, name='filter_run'),
    path('filter/run/status', filter.filter_run_status, name='filter_run_status'),
    path('filter/run/stop', filter.filter_run_stop, name='filter_run_stop'),
    path('refer/list', filter.refer_list, name='refer_list'),
    path('filter/config', filter.filter_config, name='filter_config'),
    path('filter/view/<str:market>/<str:code>', filter.filter_view, name='filter_view'),
    path('stocks/view/<str:market>/<str:code>', filter.filter_view, name='stocks_view'),
    path('refer/view/<str:market>/<str:code>', filter.filter_view, name='refer_view'),

    # ---- 关注 ----
    path('focus', focus.focus_list, name='focus'),
    path('focus/list', focus.focus_list, name='focus_list'),
    path('focus/plus', focus.focus_plus, name='focus_plus'),
    path('focus/calc', focus.focus_calc, name='focus_calc'),
    path('focus/close/<str:market>/<str:code>', focus.focus_close, name='focus_close'),
    path('focus/view/<str:market>/<str:code>', focus.focus_view, name='focus_view'),
    path('focus/edit/<str:market>/<str:code>', focus.focus_edit, name='focus_edit'),
    # ---- 图表 ----
    path('chart/data', chart.chart_data_api, name='chart_data_api'),
    path('chart/view', chart.chart_view_api, name='chart_view_api'),
    # ---- 资金 ----
    path('cash', cash.cash_view, name='cash'),
    path('cash/history', cash.cash_history_api, name='cash_history'),
    path('cash/adjust', cash.cash_adjust_api, name='cash_adjust'),
    path('cash/revoke', cash.cash_revoke, name='cash_revoke'),
    path('cash/init', cash.cash_init, name='cash_init'),
    path('cash/quota', cash.cash_quota, name='cash_quota'),
    path('cash/setting', cash.cash_setting, name='cash_setting'),

    # ---- 交易 ----
    path('trans/list', trans.trans_list, name='trans_list'),
    path('trans/deal/<str:market>/<str:code>', trans.trans_deal, name='trans_deal'),
    path('trans/calc', trans.trans_calc, name='trans_calc'),
    path('trans/view/<str:market>/<str:code>', trans.trans_view, name='trans_view'),
    path('trans/edit/<str:market>/<str:code>', trans.trans_edit, name='trans_edit'),

    path('api/stock-name', func.stock_name_api, name='stock_name_api'),
]
