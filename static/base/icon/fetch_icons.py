#!/usr/bin/env python3
"""
================================================================================
 iconify 离线图标生成工具
================================================================================

【功能说明】
    从 iconify 官方 API 批量下载项目中使用的图标 SVG 数据，
    生成离线图标文件 iconify-icons.js，使网站无需请求外部 API
    （api.iconify.design / api.simplesvg.com / api.unisvg.com）
    即可显示所有图标。

【使用步骤】
    1. 确认图标列表：
       - TABLER_ICONS：Tabler Icons 图标名称列表（前缀 tabler:）
       - FA6_SOLID_ICONS：Font Awesome 6 Solid 图标名称列表（前缀 fa6-solid:）
       如需新增图标，将图标名称（不含前缀）添加到对应列表中。

    2. 将本脚本放在 static/base/icon/ 目录下（与 iconify-icon.min.js 同目录）。

    3. 运行脚本：
       cd static/base/icon
       python3 fetch_icons.py

    4. 脚本会自动：
       - 分批从 https://api.iconify.design 下载图标数据（每批10个，避免URL过长）
       - 保留各图标集的原始尺寸（tabler=24x24, fa6-solid=512x512）
       - 在当前目录生成 iconify-icons.js

    5. 部署 iconify-icons.js 到服务器。

    6. 浏览器强制刷新（Ctrl+Shift+R）清除缓存。

【验证方法】
    - 打开浏览器控制台，应输出：[iconify] 离线图标注册完成: tabler(xx个), fa6-solid(xx个)
    - 打开网络面板，不应有 api.iconify.design 的请求
    - 页面所有图标应正常显示

【注意事项】
    1. 运行此脚本需要能访问外网（api.iconify.design）。
    2. 生成的 iconify-icons.js 必须在 iconify-icon.min.js 之前加载，
       通过 window.IconifyPreload 实现预加载。
    3. 请勿手动修改 iconify-icons.js，如需更新请修改本脚本后重新运行。
    4. 图标名称可在 https://icon-sets.iconify.design/ 查找。

【输出文件】
    iconify-icons.js（与本脚本同目录，即 static/base/icon/ 下）

================================================================================
"""

import json
import os
import urllib.request

# ==============================================================================
# 图标列表配置
# ==============================================================================
# Tabler Icons（图标前缀：tabler:）
# 图标名称不含前缀，例如 "check" 对应 <iconify-icon icon="tabler:check">
TABLER_ICONS = [
    # 列表/标记类
    "check", "star", "star-filled", "filter", "trash",
    # 导航箭头类
    "circle-arrow-left", "circle-chevron-up", "circle-chevron-down", "circle-arrow-right",
    # 图表操作类
    "circle-plus", "x", "edit", "diamond", "percentage",
    # 资金调整类
    "plus", "minus", "exposure-minus-1",
    # K线周期类
    "repeat", "repeat-off",
    "sun-filled", "sparkles-2-filled", "moon-filled",
    # 弹窗提示类
    "circle-check", "circle-x", "alert-triangle", "info-circle",
    # 图表标记类
    "menu-2", "current-location", "current-location-filled",
    "hexagon-number-1", "hexagon-number-1-filled",
    "hexagon-number-2", "hexagon-number-2-filled", "hexagon-minus",
    # 全屏类
    "maximize", "maximize-off",
]

# Font Awesome 6 Solid（图标前缀：fa6-solid:）
# 图标名称不含前缀，例如 "gear" 对应 <iconify-icon icon="fa6-solid:gear">
FA6_SOLID_ICONS = [
    "chart-line",        # 筛选（导航栏）
    "square-check",      # 关注（导航栏）
    "sack-dollar",       # 交易（导航栏）
    "circle-nodes",      # Logo（导航栏）
    "clock-rotate-left", # 复盘（导航栏）
    "gear",              # 设置（导航栏）
]


# ==============================================================================
# 核心函数
# ==============================================================================
def fetch_icons(prefix, icons):
    """
    从 iconify API 分批下载指定图标集的图标数据。

    参数:
        prefix (str): 图标集前缀，如 "tabler"、"fa6-solid"
        icons (list): 图标名称列表（不含前缀）

    返回:
        dict: 完整的 iconify collection 数据，包含：
            - prefix: 图标集前缀
            - width/height: 图标集默认尺寸（保留 API 返回的原始值）
            - icons: 图标数据字典 {图标名: {body, ...}}
            - aliases/not_found/lastModified: 其他元数据（如有）

    说明:
        - 分批下载，每批10个图标，避免 URL 过长导致 403 错误
        - 保留 API 返回的原始尺寸，不强制覆盖（tabler=24x24, fa6-solid=512x512）
        - 添加 User-Agent 请求头，避免被 API 拒绝
    """
    all_icons = {}          # 存储所有图标的数据
    collection_meta = {}    # 存储 collection 元数据（尺寸、别名等）
    batch_size = 10         # 每批下载的图标数量

    for i in range(0, len(icons), batch_size):
        batch = icons[i:i + batch_size]
        # 构造 API 请求 URL
        url = f"https://api.iconify.design/{prefix}.json?icons={','.join(batch)}"
        print(f"  下载 {prefix} 批次 {i//batch_size + 1}: {batch}")

        # 添加 User-Agent，避免被 API 拒绝
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # 合并图标数据
        all_icons.update(data.get("icons", {}))

        # 保留 collection 元数据（只在第一批时获取）
        if not collection_meta:
            for key in ("prefix", "width", "height", "aliases", "not_found", "lastModified"):
                if key in data:
                    collection_meta[key] = data[key]

    # 构建完整的 collection 数据
    result = dict(collection_meta)
    result["icons"] = all_icons
    if "prefix" not in result:
        result["prefix"] = prefix
    return result


# ==============================================================================
# 主函数
# ==============================================================================
def main():
    """
    主函数：下载图标数据并生成离线图标 JS 文件。

    生成的文件包含：
        1. window.IconifyPreload：iconify-icon 初始化时自动读取的预加载数据
        2. Iconify.addCollection()：兜底注册方式，兼容动态加载场景

    输出文件路径：
        iconify-icons.js（与本脚本同目录）
    """
    # 步骤1：下载所有图标数据
    print("开始下载图标数据...")
    tabler_data = fetch_icons("tabler", TABLER_ICONS)
    fa6_data = fetch_icons("fa6-solid", FA6_SOLID_ICONS)

    # 步骤2：生成 JS 文件内容
    # 使用 json.dumps 将 Python 字典转为 JSON，嵌入到 JS 代码中
    js_content = """/**
 * iconify 离线图标数据
 * 预注册项目中使用的所有图标，避免运行时请求外部 API
 * 自动生成，请勿手动修改
 *
 * 注意：此文件必须在 iconify-icon.min.js 之前加载，
 * 通过 window.IconifyPreload 实现预加载。
 *
 * 生成工具：fetch_icons.py
 */
(function() {
    // Tabler Icons 图标集数据
    const tablerCollection = """ + json.dumps(tabler_data, ensure_ascii=False) + """;

    // Font Awesome 6 Solid 图标集数据
    const fa6Collection = """ + json.dumps(fa6_data, ensure_ascii=False) + """;

    // 方式1：通过 IconifyPreload 预加载（主要方式）
    // iconify-icon.min.js 初始化时会自动读取 window.IconifyPreload 并注册图标
    // 必须在 iconify-icon.min.js 加载前定义
    window.IconifyPreload = [tablerCollection, fa6Collection];

    // 方式2：如果 Iconify 对象已经可用，直接注册（兜底方式，兼容动态加载场景）
    function registerIcons() {
        const Iconify = window.Iconify;
        if (Iconify && typeof Iconify.addCollection === 'function') {
            Iconify.addCollection(tablerCollection);
            Iconify.addCollection(fa6Collection);
            console.log('[iconify] 离线图标注册完成: tabler(' + Object.keys(tablerCollection.icons).length + '个), fa6-solid(' + Object.keys(fa6Collection.icons).length + '个)');
            return true;
        }
        return false;
    }

    // 立即尝试注册，如果 Iconify 还未就绪则在 DOMContentLoaded 后再试
    if (!registerIcons()) {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', registerIcons);
        } else {
            registerIcons();
        }
    }
})();
"""

    # 步骤3：写入文件
    # 输出文件与本脚本同目录（static/base/icon/iconify-icons.js）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, "iconify-icons.js")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(js_content)

    # 步骤4：输出统计信息
    print(f"\n离线图标文件已生成: {output_path}")
    print(f"  - Tabler Icons: {len(TABLER_ICONS)} 个")
    print(f"  - Font Awesome 6 Solid: {len(FA6_SOLID_ICONS)} 个")
    print(f"  - 总计: {len(TABLER_ICONS) + len(FA6_SOLID_ICONS)} 个")
    print(f"\n部署后请强制刷新浏览器（Ctrl+Shift+R）清除缓存。")


# ==============================================================================
# 脚本入口
# ==============================================================================
if __name__ == "__main__":
    main()
