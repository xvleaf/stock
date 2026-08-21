# -*- coding: utf-8 -*-
"""项目根 URL 配置"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    # ---- 默认页 ----
    path('', RedirectView.as_view(url='/focus', permanent=False), name='home'),
    path('', include('stock.urls')),
]
