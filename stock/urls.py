from django.urls import path
from . import chart, func, sector, focus, cash, filter

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
    path('focus/close/<str:market>/<str:code>', focus.focus_close, name='focus_close'),
    path('focus/view/<str:market>/<str:code>', focus.focus_view, name='focus_view'),
    # ---- 图表 ----
    path('chart/data', chart.chart_data_api, name='chart_data_api'),
    path('chart/view', chart.chart_view_api, name='chart_view_api'),
    # ---- 资金 ----
    path('capital', cash.capital_view, name='capital'),
    path('capital/history', cash.capital_history_api, name='capital_history'),
    path('capital/adjust', cash.capital_adjust_api, name='capital_adjust'),
    path('capital/setting', cash.capital_setting, name='capital_setting'),

    path('api/stock-name', func.stock_name_api, name='stock_name_api'),
]
