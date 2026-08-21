# -*- coding: utf-8 -*-
from django.apps import AppConfig


class StockConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stock'
    verbose_name = '股票管理系统'
