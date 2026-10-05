# -*- coding: utf-8 -*-
"""Django Admin 后台注册：全部模型可查改"""
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import (
    WebSetting, CashConfig, CashHistory, SectorList, StockSector,
    StockList, FocusStock, FocusHistory,
    TransOrder, TransHistory, DividendRecord,
    FilterTask, FilterResult, FilterConfig, ReviewList,
)


class SetupAwareAdminSite(admin.AdminSite):
    """无超管时，admin 登录入口重定向到管理员初始化页"""

    def login(self, request, extra_context=None):
        from django.contrib.auth.models import User
        if not User.objects.filter(is_superuser=True).exists():
            return redirect(reverse('admin_setup'))
        return super().login(request, extra_context)


class SingletonAdmin(admin.ModelAdmin):
    """单例模型后台：仅允许维护唯一一条记录，禁止新增多条、禁止删除"""

    def has_add_permission(self, request):
        # 已存在记录时隐藏“新增”
        return not self.model.objects.exists()

    def has_delete_permission(self, request, obj=None):
        # 单例记录不允许删除（业务逻辑依赖该记录存在）
        return False

    def change_view(self, request, object_id=False, form_url='', extra_context=None):
        # 直接定位到唯一记录，无需经过列表选择
        obj = self.model.objects.first()
        if obj is not None:
            object_id = str(obj.pk)
        return super().change_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        # CashConfig 业务逻辑固定使用 pk=1（get_config/has_config 均按 pk=1 读取）
        if not change and self.model is CashConfig:
            obj.pk = 1
        super().save_model(request, obj, form, change)


# ===================== 全站参数（Key-Value）=====================
@admin.register(WebSetting)
class WebSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'value_type', 'group_name', 'label', 'sort_order')
    search_fields = ('key', 'label')
    list_filter = ('group_name', 'value_type')


# ===================== 资金 =====================
@admin.register(CashConfig)
class CashConfigAdmin(SingletonAdmin):
    list_display = ('total', 'cash', 'stock', 'allowance', 'risk', 'profit', 'updated_at')


@admin.register(CashHistory)
class CashHistoryAdmin(admin.ModelAdmin):
    list_display = ('date', 'event', 'total', 'cash', 'stock', 'change', 'current_profit')
    list_filter = ('event',)
    date_hierarchy = 'date'


# ===================== 基础数据 =====================
@admin.register(StockList)
class StockListAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'market', 'cat', 'industry', 'hide')
    search_fields = ('code', 'name')
    list_filter = ('market', 'cat', 'hide')


@admin.register(SectorList)
class SectorListAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'market', 'cat', 'mark')
    search_fields = ('code', 'name')
    list_filter = ('market', 'cat')


@admin.register(StockSector)
class StockSectorAdmin(admin.ModelAdmin):
    list_display = ('stock_code', 'stock_market', 'sector_code', 'sector_market')
    search_fields = ('stock_code', 'sector_code')
    list_filter = ('sector_market',)


# ===================== 关注 =====================
@admin.register(FocusStock)
class FocusStockAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'market', 'intent', 'status', 'focus_date', 'close_date')
    search_fields = ('code', 'name')
    list_filter = ('intent', 'status', 'market')
    date_hierarchy = 'focus_date'


@admin.register(FocusHistory)
class FocusHistoryAdmin(admin.ModelAdmin):
    list_display = ('focus', 'action', 'edit_date', 'intent')
    list_filter = ('action', 'intent')
    date_hierarchy = 'edit_date'


# ===================== 交易 =====================
@admin.register(TransOrder)
class TransOrderAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'market', 'intent', 'status', 'open_date', 'close_date')
    search_fields = ('code', 'name')
    list_filter = ('intent', 'status', 'market')
    date_hierarchy = 'open_date'


@admin.register(TransHistory)
class TransHistoryAdmin(admin.ModelAdmin):
    list_display = ('order', 'action', 'intent', 'date', 'price', 'qty', 'fee')
    search_fields = ('order__code',)
    list_filter = ('action', 'intent')
    date_hierarchy = 'date'


@admin.register(DividendRecord)
class DividendRecordAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'date', 'dividend_type', 'per_share', 'amount')
    search_fields = ('code', 'name')
    list_filter = ('dividend_type',)
    date_hierarchy = 'date'


# ===================== 筛选 =====================
@admin.register(FilterTask)
class FilterTaskAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'source', 'status', 'stock_count', 'created_at')
    list_filter = ('source', 'status')
    date_hierarchy = 'created_at'


@admin.register(FilterResult)
class FilterResultAdmin(admin.ModelAdmin):
    list_display = ('task', 'code', 'name', 'market', 'mark', 'hide')
    search_fields = ('code', 'name')
    list_filter = ('mark', 'market')


@admin.register(FilterConfig)
class FilterConfigAdmin(SingletonAdmin):
    list_display = ('enabled_boards', 'exclude_st', 'default_task_id',
                    'filter_timeout', 'target_profit_ratio', 'stop_loss_ratio')


# ===================== 复盘列表 =====================
@admin.register(ReviewList)
class ReviewListAdmin(admin.ModelAdmin):
    list_display = ('review_type', 'code', 'name', 'market', 'rating',
                    'open_date', 'close_date')
    search_fields = ('code', 'name')
    list_filter = ('review_type', 'rating')
    date_hierarchy = 'close_date'
