# -*- coding: utf-8 -*-
"""全站自定义中间件"""
from django.conf import settings
from django.contrib.auth.views import redirect_to_login


class LoginRequiredMiddleware:
    """
    全站强制登录中间件。

    未认证的请求一律重定向到登录页（LOGIN_URL，携带 next 参数），
    白名单路径（settings.LOGIN_EXEMPT_PATHS，按路径前缀匹配）除外：
    - /login：登录页本身，避免重定向死循环
    - /admin：Django admin 自带 staff 登录流程（含 /admin/setup 超管初始化引导）
    - /static/：静态文件（生产由 Nginx 服务，开发由 Django 服务）
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_prefixes = tuple(getattr(settings, 'LOGIN_EXEMPT_PATHS', ()))

    def __call__(self, request):
        if not request.user.is_authenticated and not self._is_exempt(request.path):
            # 携带完整路径（含查询串）作为 next，登录后跳回
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)

    def _is_exempt(self, path):
        return any(path.startswith(prefix) for prefix in self.exempt_prefixes)
