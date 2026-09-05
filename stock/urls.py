from django.urls import path
from . import chart, func, sector, focus, cash

urlpatterns = [
    # ---- 板块 ----
    path('sector/list', sector.sector_list, name='sector_list'),
    path('sector/view/<str:market>/<str:code>', sector.sector_view, name='sector_view'),

    # ---- 关注 ----
    path('focus', focus.focus_list, name='focus'),
    path('focus/list', focus.focus_list, name='focus_list'),
    path('focus/plus', focus.focus_plus, name='focus_plus'),
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
