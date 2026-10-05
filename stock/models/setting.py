from django.db import models


# ===================== 全站参数配置（Key-Value） =====================
# 默认配置定义：key -> {value, type, group, label, sort, remark}
WEB_SETTING_DEFAULTS = {
    # 通用设置（4项）
    'icp_number':           {'value': '',         'type': 'string', 'group': 'general', 'label': '备案编号',       'sort': 1, 'remark': '网站ICP备案编号，显示在页面底部'},
    'icp_website':          {'value': '',         'type': 'string', 'group': 'general', 'label': '备案官网',       'sort': 2, 'remark': '备案查询链接地址，点击备案编号跳转'},
    'default_page_size':    {'value': '10',       'type': 'int',    'group': 'general', 'label': '分页默认数量',   'sort': 3, 'remark': '所有列表每页默认显示的记录条数'},
    'quote_interval':       {'value': '60000',    'type': 'int',    'group': 'general', 'label': '行情刷新间隔',   'sort': 4, 'remark': '列表页股价和涨幅自动刷新的间隔时间，单位秒'},
    'cash_stat_start':      {'value': '',         'type': 'string', 'group': 'general', 'label': '资金统计起始',   'sort': 5, 'remark': '资金页面统计的起始日期，空=一年前'},
    'cash_stat_end':        {'value': '',         'type': 'string', 'group': 'general', 'label': '资金统计结束',   'sort': 6, 'remark': '资金页面统计的结束日期，空=今天'},
    'cash_stat_end_set_day':{'value': '',         'type': 'string', 'group': 'general', 'label': '资金统计结束设置日', 'sort': 7, 'remark': '内部字段，记录结束日期设置日期'},
    'review_stat_start':    {'value': '',         'type': 'string', 'group': 'general', 'label': '复盘统计起始',   'sort': 8, 'remark': '复盘页面统计的起始日期，空=一年前'},
    'review_stat_end':      {'value': '',         'type': 'string', 'group': 'general', 'label': '复盘统计结束',   'sort': 9, 'remark': '复盘页面统计的结束日期，空=今天'},
    'review_stat_end_set_day': {'value': '',      'type': 'string', 'group': 'general', 'label': '复盘统计结束设置日', 'sort': 10, 'remark': '内部字段，记录结束日期设置日期'},
    # 交易费用（10项）
    'commission_ratio':     {'value': '0.000085', 'type': 'float',  'group': 'fee', 'label': '佣金费率',       'sort': 1, 'remark': '券商佣金费率，按成交金额比例收取，买卖双向'},
    'commission_min':       {'value': '0',        'type': 'float',  'group': 'fee', 'label': '最低佣金',       'sort': 2, 'remark': '单笔交易最低佣金金额，不足按此收取'},
    'stamp_buy_ratio':      {'value': '0',        'type': 'float',  'group': 'fee', 'label': '印花税率(买入)', 'sort': 3, 'remark': '买入时印花税率，A股目前买入免征'},
    'stamp_sell_ratio':     {'value': '0.0005',   'type': 'float',  'group': 'fee', 'label': '印花税率(卖出)', 'sort': 4, 'remark': '卖出时印花税率，按成交金额比例收取'},
    'transfer_fee_sh':      {'value': '0.00001',  'type': 'float',  'group': 'fee', 'label': '过户费(沪市)',   'sort': 5, 'remark': '沪市股票过户费率，按成交金额比例收取'},
    'transfer_fee_sz':      {'value': '0.00001',  'type': 'float',  'group': 'fee', 'label': '过户费(深市)',   'sort': 6, 'remark': '深市股票过户费率，按成交金额比例收取'},
    'transfer_fee_bj':      {'value': '0.00001',  'type': 'float',  'group': 'fee', 'label': '过户费(北交所)', 'sort': 7, 'remark': '北交所股票过户费率，按成交金额比例收取'},
    'dividend_tax_long':    {'value': '0',        'type': 'float',  'group': 'fee', 'label': '分红税(>1年)',   'sort': 8, 'remark': '持股超过1年的现金分红税率，目前免征'},
    'dividend_tax_mid':     {'value': '0.1',      'type': 'float',  'group': 'fee', 'label': '分红税(1月~1年)', 'sort': 9, 'remark': '持股1个月至1年的现金分红税率，卖出时补缴'},
    'dividend_tax_short':   {'value': '0.2',      'type': 'float',  'group': 'fee', 'label': '分红税(<1月)',   'sort': 10, 'remark': '持股不足1个月的现金分红税率，卖出时补缴'},
    # 交易时间（4项）
    'trade_am_start':       {'value': '34200',    'type': 'int',    'group': 'trade_time', 'label': '上午开始时间', 'sort': 1, 'remark': '上午交易开始时间，用于判断行情刷新和分时图数据范围'},
    'trade_am_end':         {'value': '41400',    'type': 'int',    'group': 'trade_time', 'label': '上午结束时间', 'sort': 2, 'remark': '上午交易结束时间（午休开始）'},
    'trade_pm_start':       {'value': '46800',    'type': 'int',    'group': 'trade_time', 'label': '下午开始时间', 'sort': 3, 'remark': '下午交易开始时间（午休结束）'},
    'trade_pm_end':         {'value': '54000',    'type': 'int',    'group': 'trade_time', 'label': '下午结束时间', 'sort': 4, 'remark': '下午交易结束时间，用于判断收盘状态'},
    # K线参数（18项）
    'kline_start_date_day':   {'value': '19801020', 'type': 'string', 'group': 'kline', 'label': '日线起始日期',  'sort': 1, 'remark': '日K线数据获取的起始日期，格式YYYYMMDD'},
    'kline_start_date_week':  {'value': '19801020', 'type': 'string', 'group': 'kline', 'label': '周线起始日期',  'sort': 2, 'remark': '周K线数据获取的起始日期，格式YYYYMMDD'},
    'kline_start_date_month': {'value': '19801020', 'type': 'string', 'group': 'kline', 'label': '月线起始日期',  'sort': 3, 'remark': '月K线数据获取的起始日期，格式YYYYMMDD'},
    'kline_ma_day':           {'value': '200',      'type': 'int',    'group': 'kline', 'label': '日线MA周期',    'sort': 4, 'remark': '日K线均线（MA）的计算周期'},
    'kline_ma_week':          {'value': '60',       'type': 'int',    'group': 'kline', 'label': '周线MA周期',    'sort': 5, 'remark': '周K线均线（MA）的计算周期'},
    'kline_ma_month':         {'value': '30',       'type': 'int',    'group': 'kline', 'label': '月线MA周期',    'sort': 6, 'remark': '月K线均线（MA）的计算周期'},
    'kline_mv_day':           {'value': '60',       'type': 'int',    'group': 'kline', 'label': '日线MV周期',    'sort': 7, 'remark': '日K线成交量均线（MV）的计算周期'},
    'kline_mv_week':          {'value': '30',       'type': 'int',    'group': 'kline', 'label': '周线MV周期',    'sort': 8, 'remark': '周K线成交量均线（MV）的计算周期'},
    'kline_mv_month':         {'value': '30',       'type': 'int',    'group': 'kline', 'label': '月线MV周期',    'sort': 9, 'remark': '月K线成交量均线（MV）的计算周期'},
    'kline_ema_k_day':        {'value': '10',       'type': 'int',    'group': 'kline', 'label': '日线EMA-K值',   'sort': 10, 'remark': '日K线EMA指标的快线周期（K值）'},
    'kline_ema_k_week':       {'value': '20',       'type': 'int',    'group': 'kline', 'label': '周线EMA-K值',   'sort': 11, 'remark': '周K线EMA指标的快线周期（K值）'},
    'kline_ema_k_month':      {'value': '20',       'type': 'int',    'group': 'kline', 'label': '月线EMA-K值',   'sort': 12, 'remark': '月K线EMA指标的快线周期（K值）'},
    'kline_ema_d_day':        {'value': '30',       'type': 'int',    'group': 'kline', 'label': '日线EMA-D值',   'sort': 13, 'remark': '日K线EMA指标的慢线周期（D值）'},
    'kline_ema_d_week':       {'value': '30',       'type': 'int',    'group': 'kline', 'label': '周线EMA-D值',   'sort': 14, 'remark': '周K线EMA指标的慢线周期（D值）'},
    'kline_ema_d_month':      {'value': '30',       'type': 'int',    'group': 'kline', 'label': '月线EMA-D值',   'sort': 15, 'remark': '月K线EMA指标的慢线周期（D值）'},
    'density_max':            {'value': '20',       'type': 'int',    'group': 'kline', 'label': 'K线最大密度',    'sort': 16, 'remark': 'K线图每屏最多显示的K线数量'},
    'density_std':            {'value': '13',       'type': 'int',    'group': 'kline', 'label': 'K线标准密度',    'sort': 17, 'remark': 'K线图默认每屏显示的K线数量'},
    'density_min':            {'value': '5',        'type': 'int',    'group': 'kline', 'label': 'K线最小密度',    'sort': 18, 'remark': 'K线图每屏最少显示的K线数量'},
    # 界面配置 - 通用布局（6项）
    'stock_chart_visible':     {'value': 'true',  'type': 'bool', 'group': 'ui', 'label': '股票图表',       'sort': 1, 'remark': '控制所有页面股票图表的显示与隐藏'},
    'nav_locked_screen_height': {'value': '800',  'type': 'int',  'group': 'ui', 'label': '导航栏隐藏阈值', 'sort': 2, 'remark': '-1=锁定导航栏始终显示；大于0时，屏幕高度超过此值则滚动自动隐藏'},
    'gap_height':              {'value': '2',     'type': 'int',  'group': 'ui', 'label': '导航间隔',       'sort': 3, 'remark': '导航栏与内容区域之间的间距，单位像素'},
    'nav_height':              {'value': '50',    'type': 'int',  'group': 'ui', 'label': '导航高度(桌面)', 'sort': 4, 'remark': '桌面端顶部导航栏的高度，单位像素'},
    'nav_height_mobile':       {'value': '40',    'type': 'int',  'group': 'ui', 'label': '导航高度(移动)', 'sort': 5, 'remark': '移动端顶部导航栏的高度，单位像素'},
    'navi_bar_height':         {'value': '25',    'type': 'int',  'group': 'ui', 'label': '底部导航高度',   'sort': 6, 'remark': '图表页面底部导航栏（prev/next）的高度'},
    # 界面配置 - 内容布局（8项）
    'mobile_breakpoint':       {'value': '992',   'type': 'int',  'group': 'ui', 'label': '移动断点',       'sort': 7, 'remark': '屏幕宽度低于此值时切换为移动端布局（汉堡菜单）'},
    'bp1':                     {'value': '1200',  'type': 'int',  'group': 'ui', 'label': '断点一',         'sort': 8, 'remark': '第一档宽度断点，低于此值使用宽度一'},
    'bp2':                     {'value': '1440',  'type': 'int',  'group': 'ui', 'label': '断点二',         'sort': 9, 'remark': '第二档宽度断点，低于此值使用宽度二'},
    'bp3':                     {'value': '1920',  'type': 'int',  'group': 'ui', 'label': '断点三',         'sort': 10, 'remark': '第三档宽度断点，低于此值使用宽度三'},
    'w1':                      {'value': '100',   'type': 'int',  'group': 'ui', 'label': '宽度一（正常）', 'sort': 11, 'remark': '非全屏、屏幕<断点一时的内容宽度百分比'},
    'w2':                      {'value': '85',    'type': 'int',  'group': 'ui', 'label': '宽度二（正常）', 'sort': 12, 'remark': '非全屏、断点一~二之间的内容宽度百分比'},
    'w3':                      {'value': '70',    'type': 'int',  'group': 'ui', 'label': '宽度三（正常）', 'sort': 13, 'remark': '非全屏、断点二~三之间的内容宽度百分比'},
    'w4':                      {'value': '60',    'type': 'int',  'group': 'ui', 'label': '宽度四（正常）', 'sort': 14, 'remark': '非全屏、屏幕≥断点三时的内容宽度百分比'},
    # 界面配置 - 图表布局（20项）
    'h1l':                     {'value': '90',    'type': 'int',  'group': 'ui', 'label': '高度一（正常横屏）', 'sort': 15, 'remark': '横屏、屏幕<断点一时的图表高度百分比'},
    'h2l':                     {'value': '80',    'type': 'int',  'group': 'ui', 'label': '高度二（正常横屏）', 'sort': 16, 'remark': '横屏、断点一~二之间的图表高度百分比'},
    'h3l':                     {'value': '70',    'type': 'int',  'group': 'ui', 'label': '高度三（正常横屏）', 'sort': 17, 'remark': '横屏、断点二~三之间的图表高度百分比'},
    'h4l':                     {'value': '60',    'type': 'int',  'group': 'ui', 'label': '高度四（正常横屏）', 'sort': 18, 'remark': '横屏、屏幕≥断点三时的图表高度百分比'},
    'h1':                      {'value': '35',    'type': 'int',  'group': 'ui', 'label': '高度一（正常竖屏）', 'sort': 19, 'remark': '竖屏、屏幕<断点一时的图表高度百分比'},
    'h2':                      {'value': '40',    'type': 'int',  'group': 'ui', 'label': '高度二（正常竖屏）', 'sort': 20, 'remark': '竖屏、断点一~二之间的图表高度百分比'},
    'h3':                      {'value': '45',    'type': 'int',  'group': 'ui', 'label': '高度三（正常竖屏）', 'sort': 21, 'remark': '竖屏、断点二~三之间的图表高度百分比'},
    'h4':                      {'value': '50',    'type': 'int',  'group': 'ui', 'label': '高度四（正常竖屏）', 'sort': 22, 'remark': '竖屏、屏幕≥断点三时的图表高度百分比'},
    'w5':                      {'value': '100',   'type': 'int',  'group': 'ui', 'label': '宽度一（全屏）', 'sort': 23, 'remark': '全屏、屏幕<断点一时的图表宽度百分比'},
    'w6':                      {'value': '90',    'type': 'int',  'group': 'ui', 'label': '宽度二（全屏）', 'sort': 24, 'remark': '全屏、断点一~二之间的图表宽度百分比'},
    'w7':                      {'value': '80',    'type': 'int',  'group': 'ui', 'label': '宽度三（全屏）', 'sort': 25, 'remark': '全屏、断点二~三之间的图表宽度百分比'},
    'w8':                      {'value': '70',    'type': 'int',  'group': 'ui', 'label': '宽度四（全屏）', 'sort': 26, 'remark': '全屏、屏幕≥断点三时的图表宽度百分比'},
    'h5':                      {'value': '100',   'type': 'int',  'group': 'ui', 'label': '高度一（全屏）', 'sort': 27, 'remark': '全屏、屏幕<断点一时的图表高度百分比'},
    'h6':                      {'value': '90',    'type': 'int',  'group': 'ui', 'label': '高度二（全屏）', 'sort': 28, 'remark': '全屏、断点一~二之间的图表高度百分比'},
    'h7':                      {'value': '80',    'type': 'int',  'group': 'ui', 'label': '高度三（全屏）', 'sort': 29, 'remark': '全屏、断点二~三之间的图表高度百分比'},
    'h8':                      {'value': '70',    'type': 'int',  'group': 'ui', 'label': '高度四（全屏）', 'sort': 30, 'remark': '全屏、屏幕≥断点三时的图表高度百分比'},
    'cash_chart_height':       {'value': '400',   'type': 'int',  'group': 'ui', 'label': '资金曲线高度',   'sort': 31, 'remark': '资金页面资金变化趋势图的固定高度，单位像素'},
    'chart_vertical_align_fullscreen': {'value': 'flex-start', 'type': 'string', 'group': 'ui', 'label': '高度对齐（全屏）', 'sort': 32, 'remark': '全屏时图表在垂直方向的对齐方式：顶部/居中/底部'},
    'trend_main_ratio':        {'value': '75',    'type': 'int',  'group': 'ui', 'label': '分时主图比例',   'sort': 33, 'remark': '分时图主图（价格）占总高度的百分比，副图为剩余部分'},
    'kline_main_ratio':        {'value': '80',    'type': 'int',  'group': 'ui', 'label': 'K线主图比例',    'sort': 34, 'remark': 'K线图主图（K线）占总高度的百分比，副图为剩余部分'},
}


class WebSetting(models.Model):
    """全站参数配置（Key-Value模式）"""
    key = models.CharField('配置键', max_length=50, unique=True)
    value = models.CharField('配置值', max_length=200, default='')
    value_type = models.CharField('值类型', max_length=10, default='string')
    group_name = models.CharField('分组', max_length=20, default='general')
    label = models.CharField('显示名称', max_length=50, default='')
    remark = models.CharField('说明', max_length=200, default='')
    sort_order = models.IntegerField('排序', default=0)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'models_web_setting'
        verbose_name = '全站参数配置'
        verbose_name_plural = verbose_name
        ordering = ['group_name', 'sort_order']

    def __str__(self):
        return f'{self.key}={self.value}'
