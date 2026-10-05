# -*- coding: utf-8 -*-
"""模板上下文处理器"""


def ui_config(request):
    """模板上下文处理器：注入界面配置到所有页面"""
    from .fetch.config import get_ui_config
    return {'ui_config': get_ui_config()}
