// 需与 main.css 一起修改
export const BREAKPOINT_MD = 992;
// 屏幕高度阈值：视口高度小于该值才允许滚动自动隐藏导航栏，大于等于始终显示
export const SCREEN_HEIGHT_THRESHOLD = 800;
export const RESIZE_DELAY_LAYOUT = 150;
// 初始化保护时长
const INIT_PROTECT_DELAY = 500;
// 用于外部控制导航锁定状态，false 为不锁定
const NAV_LOCKED = false;
let nav = null;
let pageContent = null;
let gapEl = null;
let navHeight = 0;
let layoutResizeTimer = null;
let frameTicking = false;
let lastScrollY = 0;
let disableNavAutoHide = false;
let isNavVisible = true;
let isInitializing = false;
let lastIsMobile = null;
let subMenuAbortController = null;
let isBaseInited = false;
let baseGlobalAbort = null;
// 路由匹配优先级，长前缀放前面
const NAV_ACTIVE_RULES = [
    { selector: 'a.nav-link[href="/review/trans/list"]', prefixes: ['/review/trans'] },
    { selector: '#reviewDropdown', prefixes: ['/review', '/setting', '/files', '/admin', '/logout'] },
    { selector: '#focusDropdown', prefixes: ['/focus', '/fund', '/sector', '/filter', '/focus/view'] },
    { selector: 'a.nav-link[href="/trans/list"]', prefixes: ['/trans'] },
    { selector: 'a.nav-link[href="/capital"]', prefixes: ['/capital'] },
];
// ====================== 对外导航工具函数 ======================
/** 获取导航是否隐藏 */
export function isMainNavHidden() {
    if (!nav) return false;
    return nav.classList.contains('hidden');
}
/** 获取导航高度 */
export function getMainNavHeight() {
    return navHeight || 0;
}
/** 导出屏幕高度阈值供外部读取 */
export function getScreenHeightThreshold() {
    return SCREEN_HEIGHT_THRESHOLD;
}
// ====================== 工具纯函数 ======================
export function isMobileSize() {
    return window.innerWidth < BREAKPOINT_MD;
}
export function debounceLayout(cb, delay) {
    clearTimeout(layoutResizeTimer);
    layoutResizeTimer = setTimeout(cb, delay);
}
function pathMatchRule(path, rule) {
    return rule.prefixes.some((prefix) => path.startsWith(prefix));
}
function clearAllTimer() {
    clearTimeout(layoutResizeTimer);
    layoutResizeTimer = null;
}
// ====================== 导航下拉菜单 ======================
function bindDesktopSubMenu(items, signal) {
    items.forEach((item) => {
        item.addEventListener('mouseenter', () => item.classList.add('show'), { signal });
        item.addEventListener('mouseleave', () => item.classList.remove('show'), { signal });
    });
}
function bindMobileSubMenu(items, signal) {
    items.forEach((item) => {
        const toggle = item.querySelector('.dropdown-toggle');
        if (!toggle) return;
        toggle.addEventListener(
            'click',
            (e) => {
                e.preventDefault();
                e.stopPropagation();
                item.classList.toggle('show');
            },
            { signal }
        );
    });
}
function bindClearSubmenuOnDropdownClose(signal) {
    const focusDrop = document.getElementById('focusDropdown');
    const reviewDrop = document.getElementById('reviewDropdown');
    const clearAllSub = () => {
        document.querySelectorAll('.dropdown-submenu.show').forEach((el) => el.classList.remove('show'));
    };
    focusDrop?.addEventListener('hide.bs.dropdown', clearAllSub, { signal });
    reviewDrop?.addEventListener('hide.bs.dropdown', clearAllSub, { signal });
}
// ====================== 初始化子菜单交互 ======================
function initNavSubMenu(signal) {
    const subItems = document.querySelectorAll('.dropdown-submenu');
    if (isMobileSize()) {
        bindMobileSubMenu(subItems, signal);
        bindClearSubmenuOnDropdownClose(signal);
    } else {
        bindDesktopSubMenu(subItems, signal);
        bindClearSubmenuOnDropdownClose(signal);
    }
}
// ====================== 全局点击收拢菜单 ======================
function closeAllSubMenus(target) {
    const subs = document.querySelectorAll('.dropdown-submenu.show');
    let clickInside = false;
    subs.forEach((el) => {
        if (el.contains(target)) clickInside = true;
    });
    if (!clickInside) subs.forEach((el) => el.classList.remove('show'));
}
function closeTopLevelDropdown(target) {
    const toggles = [document.getElementById('focusDropdown'), document.getElementById('reviewDropdown')];
    toggles.forEach((toggle) => {
        if (!toggle) return;
        const menu = toggle.nextElementSibling;
        if (!menu) return;
        const isClickInside = toggle.contains(target) || menu.contains(target);
        if (menu.classList.contains('show') && !isClickInside) {
            bootstrap.Dropdown.getInstance(toggle)?.hide();
        }
    });
}
function closeMobileNavPanel(target) {
    const navPanel = document.getElementById('navbarNav');
    const clickInNav = nav.contains(target);
    if (!clickInNav && navPanel?.classList.contains('show')) {
        bootstrap.Collapse.getInstance(navPanel)?.hide();
    }
}
function bindGlobalClickCollapseMenu(e) {
    if (!isMobileSize()) return;
    const target = e.composedPath()[0];
    closeAllSubMenus(target);
    closeTopLevelDropdown(target);
    closeMobileNavPanel(target);
}
// ====================== 导航路由高亮 ======================
function setActiveNavLink() {
    const currentPath = window.location.pathname;
    document.querySelectorAll('#mainNav .nav-link.active').forEach((el) => el.classList.remove('active'));
    for (const rule of NAV_ACTIVE_RULES) {
        if (pathMatchRule(currentPath, rule)) {
            const dom = document.querySelector(rule.selector);
            dom?.classList.add('active');
            break;
        }
    }
}
// ====================== 页面布局控制 ======================
function updatePageLayoutByNavState() {
    if (!gapEl || !pageContent) return;
    const navHidden = isMainNavHidden();
    if (navHidden) {
        gapEl.style.display = 'none';
        pageContent.style.paddingTop = '0px';
    } else {
        gapEl.style.display = 'block';
        pageContent.style.paddingTop = `calc(var(--nav-height) + var(--gap-height))`;
    }
}
export function toggleNavVisible() {
    if (!nav) return;
    // true = 强制锁定导航永久显示，禁用自动隐藏逻辑
    // false = 取消锁定，交给滚动自动控制显隐，不会主动隐藏导航
    if (NAV_LOCKED) {
        nav.classList.remove('hidden');
        isNavVisible = true;
        disableNavAutoHide = true;
        // 布局更新，锁定导航时同步调整页面内边距与间隙显隐
        updatePageLayoutByNavState(); 
    } else {
        disableNavAutoHide = false;
        // 取消锁定后，同步 isNavVisible 为当前导航实际可见状态（从 DOM 读取）
        isNavVisible = !nav.classList.contains('hidden');
        // 仅更新布局，不操作 nav hidden 类
        updatePageLayoutByNavState();
    }
    // 触发自定义事件，通知其他模块导航状态已变更
    window.dispatchEvent(new CustomEvent('navVisibilityChanged'));
}
function initBasePageLayout() {
    if (!nav || !pageContent || !gapEl) return;
    // 初始化强制显示导航
    nav.classList.remove('hidden');
    isNavVisible = true;
    disableNavAutoHide = false;
    updatePageLayoutByNavState();
}
// ====================== 滚动节流 ======================
function handleWindowScrollFrame() {
    const scrollY = window.scrollY;
    // 初始化阶段：只记录位置，不改变导航状态
    if (isInitializing) {
        lastScrollY = scrollY;
        frameTicking = false;
        return;
    }
    const threshold = 2;
    const viewHeight = window.innerHeight;
    const totalScrollHeight = document.documentElement.scrollHeight;
    const isPageBottom = viewHeight + scrollY >= totalScrollHeight - 5;
    const isPageOverflow = totalScrollHeight > viewHeight;
    // 底部回弹抑制
    if (isPageBottom) {
        lastScrollY = scrollY;
        frameTicking = false;
        return;
    }
    // 下滑（滚动变小）→ 恢复导航
    if (scrollY < lastScrollY - threshold) {
        if (!isNavVisible) {
            nav.classList.remove('hidden');
            isNavVisible = true;
            updatePageLayoutByNavState();
            // 确保所有监听导航状态的模块都能收到通知同步更新
            window.dispatchEvent(new CustomEvent('navVisibilityChanged'));
        }
        lastScrollY = scrollY;
        frameTicking = false;
        return;
    }
    // 上滑（滚动变大）→ 检查是否允许隐藏
    if (viewHeight >= SCREEN_HEIGHT_THRESHOLD) {
        lastScrollY = scrollY;
        frameTicking = false;
        return;
    }
    if (!isPageOverflow) {
        lastScrollY = scrollY;
        frameTicking = false;
        return;
    }
    if (disableNavAutoHide) {
        lastScrollY = scrollY;
        frameTicking = false;
        return;
    }
    if (scrollY <= lastScrollY + threshold || scrollY <= navHeight || !isNavVisible) {
        lastScrollY = scrollY;
        frameTicking = false;
        return;
    }
    // 执行隐藏
    nav.classList.add('hidden');
    isNavVisible = false;
    updatePageLayoutByNavState();
    // 确保所有监听导航状态的模块都能收到通知同步更新
    window.dispatchEvent(new CustomEvent('navVisibilityChanged'));
    lastScrollY = scrollY;
    frameTicking = false;
}
export function handleWindowScroll() {
    if (!frameTicking) {
        window.requestAnimationFrame(handleWindowScrollFrame);
        frameTicking = true;
    }
}
// ====================== 全局初始化 ======================
export function baseInit() {
    // 重复初始化时先销毁旧实例，避免事件重复绑定与内存泄漏
    if (isBaseInited && baseGlobalAbort) {
        baseInit.destroy();
    }
    const globalAbort = new AbortController();
    baseGlobalAbort = globalAbort;
    const signal = globalAbort.signal;
    
    nav = document.getElementById('mainNav');
    pageContent = document.getElementById('pageContent');
    gapEl = document.getElementById('gap');
    // 开启初始化保护
    isInitializing = true;
    subMenuAbortController = new AbortController();
    initNavSubMenu(subMenuAbortController.signal);
    lastIsMobile = isMobileSize();
    setActiveNavLink();
    // 强制显示导航
    initBasePageLayout();
    // 记录当前滚动位置
    lastScrollY = window.scrollY;
    // 计算初始导航高度
    navHeight = nav?.offsetHeight ?? 0;
    // 显示/隐藏导航控制
    toggleNavVisible()
    setTimeout(() => {
        isInitializing = false;
        // 可额外同步一次，确保导航状态正确
        handleWindowScroll();
    }, INIT_PROTECT_DELAY);
    document.addEventListener('click', bindGlobalClickCollapseMenu, { signal });
    window.addEventListener(
        'resize',
        () => {
            debounceLayout(() => {
                const tempHidden = isMainNavHidden();
                if (tempHidden) nav.classList.remove('hidden');
                navHeight = nav.offsetHeight;
                if (tempHidden) nav.classList.add('hidden');
                updatePageLayoutByNavState();
                handleWindowScroll();
                window.dispatchEvent(new CustomEvent('navVisibilityChanged'));
                // 检测是否跨越移动端断点，跨越则重新绑定子菜单交互
                const currentIsMobile = isMobileSize();
                if (currentIsMobile !== lastIsMobile) {
                    // 销毁旧的事件监听
                    subMenuAbortController.abort();
                    // 创建新的信号量，重新绑定对应模式的子菜单事件
                    subMenuAbortController = new AbortController();
                    initNavSubMenu(subMenuAbortController.signal);
                    lastIsMobile = currentIsMobile;
                }
            }, RESIZE_DELAY_LAYOUT);
        },
        { passive: true, signal }
    );
    window.addEventListener('scroll', handleWindowScroll, { passive: true, signal });
    baseInit.destroy = () => {
        globalAbort.abort();
        // 销毁子菜单专属事件监听
        subMenuAbortController?.abort();
        clearAllTimer();
        // 重置初始化状态与引用
        isBaseInited = false;
        baseGlobalAbort = null;
    };
    isBaseInited = true;
}