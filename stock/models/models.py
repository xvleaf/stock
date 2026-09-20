from django.db import models
from django.utils import timezone
from decimal import Decimal
import datetime


# ===================== 资金变化历史 =====================
class CashHistory(models.Model):
    """资金变化历史 —— 记录每次总资金/现金/股票市值的变化节点及原因"""
    REASON_DEPOSIT = 'deposit'       # 存入资金
    REASON_WITHDRAW = 'withdraw'     # 取出资金
    REASON_BUY = 'buy'               # 买入股票
    REASON_SELL = 'sell'             # 卖出股票
    REASON_ADJUST = 'adjust'         # 手动调整
    REASON_DIVIDEND = 'dividend'     # 分红
    REASON_CHOICES = [
        (REASON_DEPOSIT, '存入资金'),
        (REASON_WITHDRAW, '取出资金'),
        (REASON_BUY, '买入股票'),
        (REASON_SELL, '卖出股票'),
        (REASON_ADJUST, '手动调整'),
        (REASON_DIVIDEND, '分红'),
    ]
    date = models.DateField('变化日期', default=timezone.now, db_index=True)
    total = models.DecimalField('总资金', max_digits=14, decimal_places=2, default=0)
    cash = models.DecimalField('现金', max_digits=14, decimal_places=2, default=0)
    stock = models.DecimalField('股票市值', max_digits=14, decimal_places=2, default=0)
    reason = models.CharField('变化原因', max_length=20, choices=REASON_CHOICES, default=REASON_ADJUST)
    amount = models.DecimalField('变化金额', max_digits=14, decimal_places=2, default=0,
                                 help_text='正数=增加, 负数=减少')
    remark = models.CharField('备注', max_length=200, blank=True, default='')
    order = models.ForeignKey('TransOrder', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='cash_histories', verbose_name='关联交易')
    created_at = models.DateField('创建日期', auto_now_add=True)

    class Meta:
        db_table = 'models_cash_history'
        verbose_name = '资金历史'
        verbose_name_plural = verbose_name
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.date:%Y-%m-%d} {self.get_reason_display()} {self.amount:+}'

    @classmethod
    def snapshot(cls, reason, amount, remark='', order=None):
        """
        快照当前资金状态并写入历史记录
        :param reason: 变化原因（REASON_* 常量）
        :param amount: 变化金额（正增负减）
        :param remark: 备注
        :param order: 关联交易订单
        """
        config = CashConfig.get_config()
        cls.objects.create(
            total=config.total,
            cash=config.cash,
            stock=config.stock,
            reason=reason,
            amount=amount,
            remark=remark,
            order=order,
        )


# ===================== 账户资金配置 =====================
class CashConfig(models.Model):
    total = models.DecimalField('总资金', max_digits=14, decimal_places=2, default=100000)
    cash = models.DecimalField('现金', max_digits=14, decimal_places=2, default=100000)
    stock = models.DecimalField('股票', max_digits=14, decimal_places=2, default=100000)
    available = models.DecimalField('可用资金', max_digits=14, decimal_places=2, default=100000)
    commission_ratio = models.DecimalField('佣金费率', max_digits=8, decimal_places=5, default=Decimal('0.00025'))
    commission_min = models.DecimalField('最低佣金', max_digits=8, decimal_places=2, default=Decimal('5'))
    stamp_buy_ratio = models.DecimalField('印花税率(买入)', max_digits=8, decimal_places=5, default=Decimal('0.0005'))
    stamp_sell_ratio = models.DecimalField('印花税率(卖出)', max_digits=8, decimal_places=5, default=Decimal('0.0005'))
    updated_at = models.DateField('更新日期', auto_now=True)

    class Meta:        
        # 自定义模型在数据库中的显示名称
        db_table = 'models_cash_config'
        verbose_name = '资金配置'
        verbose_name_plural = verbose_name

    @classmethod
    def get_config(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'资金配置(可用资金:{self.available})'


# ===================== 板块列表 =====================
class SectorList(models.Model):
    code = models.CharField('代码', max_length=20, db_index=True)
    name = models.CharField('板块', max_length=50)
    market = models.CharField('市场', max_length=10, default='L1')
    cat = models.CharField('类别', max_length=10, default='SI')
    mark = models.CharField('标记', max_length=50, default='')

    class Meta: 
        # 自定义模型在数据库中的显示名称
        db_table = 'models_secotr_list'
        verbose_name = '板块列表'
        verbose_name_plural = verbose_name

# ===================== 股票-板块关联 =====================
class StockSector(models.Model):
    stock_code = models.CharField(max_length=20, db_index=True)
    stock_market = models.CharField(max_length=10)
    sector_code = models.CharField(max_length=20, db_index=True)
    sector_market = models.CharField(max_length=10, default='SW')

    class Meta:
        db_table = 'models_stock_sector'
        unique_together = ('stock_code', 'stock_market', 'sector_code', 'sector_market')

# ===================== 股票列表 =====================
class StockList(models.Model):
    code = models.CharField('代码', max_length=20, db_index=True)
    name = models.CharField('名称', max_length=50)
    market = models.CharField('市场', max_length=10, default='SH')
    cat = models.CharField('类别', max_length=10, default='stock')
    industry = models.CharField('行业', max_length=50)    
    mark = models.CharField('标记', max_length=50, default='')
    hide = models.CharField('隐藏', max_length=50, default='')

    class Meta: 
        # 自定义模型在数据库中的显示名称
        db_table = 'models_stock_list'
        verbose_name = '股票列表'
        verbose_name_plural = verbose_name


# ===================== 关注股票 =====================
class FocusStock(models.Model):
    STATUS_WATCHING = 'watching'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_WATCHING, '关注中'),
        (STATUS_CLOSED, '已关闭'),
    ]
    CLOSE_REASON_MANUAL = 'manual'
    CLOSE_REASON_BOUGHT = 'bought'
    CLOSE_REASON_CHOICES = [
        (CLOSE_REASON_MANUAL, '手动关闭'),
        (CLOSE_REASON_BOUGHT, '已买入'),
    ]
    INTENT_BUY = 'B'
    INTENT_SELL = 'S'
    INTENT_CHOICES = [
        (INTENT_BUY, '买入'),
        (INTENT_SELL, '卖出'),
    ]
    code = models.CharField('股票代码', max_length=20, db_index=True)
    name = models.CharField('股票名称', max_length=50)
    market = models.CharField('股票市场', max_length=10, default='SH')
    cat = models.CharField('股票类型', max_length=10, default='stock')

    focus_date = models.DateField('关注日期', default=timezone.now)
    intent = models.CharField('交易方向', max_length=1, choices=INTENT_CHOICES, default=INTENT_BUY)
    plan_price = models.DecimalField('计划填报', max_digits=10, decimal_places=3, default=0)
    plan_qty = models.IntegerField('计划数量', default=0)
    target_price = models.DecimalField('目标价格', max_digits=10, decimal_places=3, default=0)
    stop_price = models.DecimalField('止损价格', max_digits=10, decimal_places=3, default=0)
    allowed_qty = models.IntegerField('允许数量', default=0)
    win_ratio = models.DecimalField('盈利概率', max_digits=5, decimal_places=2, default=0)

    status = models.CharField('状态', max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_WATCHING, db_index=True)
    close_date = models.DateField('关闭日期', null=True, blank=True)
    close_reason = models.CharField('关闭原因', max_length=20, choices=CLOSE_REASON_CHOICES,
                                    blank=True, default='')

    sort_order = models.IntegerField('排序', default=1)

    comments = models.TextField('备注', blank=True, default='')
    created_at = models.DateField('创建日期', auto_now_add=True)
    updated_at = models.DateField('更新日期', auto_now=True)

    class Meta: 
        # 自定义模型在数据库中的显示名称
        db_table = 'models_focus_stock'
        verbose_name = '关注股票'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', '-focus_date']
        indexes = [models.Index(fields=['code', 'status'])]

    def __str__(self):
        return f'{self.name}({self.code})'

    @property
    def is_watching(self):
        return self.status == self.STATUS_WATCHING

    @property
    def tscode(self):
        return f'{self.code}.{self.market}'

    @property
    def risk_reward_ratio(self):
        buy = self.plan_price
        if buy and self.target_price and self.stop_price and buy > self.stop_price:
            return (self.target_price - buy) / (buy - self.stop_price)
        return Decimal('0')

    def save_history(self, action='edit'):
        """保存当前关注信息到历史记录"""
        FocusHistory.objects.create(
            focus=self, 
            action=action,
            edit_date=self.updated_at,
            plan_price=self.plan_price,
            plan_qty=self.plan_qty,
            target_price=self.target_price,
            stop_price=self.stop_price,
            win_ratio=self.win_ratio,
            comments=self.comments,
        )


# ===================== 关注调整历史 =====================
class FocusHistory(models.Model):
    """关注股票调整历史 —— 记录每次创建/编辑/关闭/买入时的关注信息快照"""
    ACTION_CREATE = 'create'
    ACTION_EDIT = 'edit'
    ACTION_CLOSE = 'close'
    ACTION_DEAL = 'deal'
    ACTION_CHOICES = [
        (ACTION_CREATE, '创建关注'),
        (ACTION_EDIT, '调整计划'),
        (ACTION_CLOSE, '关闭关注'),
        (ACTION_DEAL, '已交易')
    ]
    INTENT_BUY = 'B'
    INTENT_SELL = 'S'
    INTENT_CHOICES = [
        (INTENT_BUY, '买入'),
        (INTENT_SELL, '卖出'),
    ]
    focus = models.ForeignKey(FocusStock, on_delete=models.CASCADE,
                              related_name='histories', verbose_name='关联关注')
    action = models.CharField('操作', max_length=10, choices=ACTION_CHOICES, default=ACTION_EDIT)
    edit_date = models.DateField('操作日期', default=timezone.now)

    intent = models.CharField('交易方向', max_length=1, choices=INTENT_CHOICES, default=INTENT_BUY)
    plan_price = models.DecimalField('计划填报', max_digits=10, decimal_places=3, default=0)
    plan_qty = models.IntegerField('计划数量', default=0)
    target_price = models.DecimalField('目标价格', max_digits=10, decimal_places=3, default=0)
    stop_price = models.DecimalField('止损价格', max_digits=10, decimal_places=3, default=0)
    win_ratio = models.DecimalField('盈利概率', max_digits=5, decimal_places=2, default=0)
    comments = models.TextField('备注', blank=True, default='')

    class Meta:
        # 自定义模型在数据库中的显示名称
        db_table = 'models_focus_history'
        verbose_name = '关注历史'
        verbose_name_plural = verbose_name
        ordering = ['-edit_date']

    def __str__(self):
        return f'{self.focus.code} {self.get_action_display()} {self.edit_date:%Y-%m-%d}'


# ===================== 交易订单 =====================
class TransOrder(models.Model):
    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN, '持仓中'),
        (STATUS_CLOSED, '已平仓'),
    ]
    focus = models.ForeignKey(FocusStock, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='orders', verbose_name='关联关注')
    code = models.CharField('股票代码', max_length=20, db_index=True)
    name = models.CharField('股票名称', max_length=50)
    market = models.CharField('股票市场', max_length=10, default='SH')
    cat = models.CharField('股票类型', max_length=10, default='stock')
    status = models.CharField('交易状态', max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_OPEN, db_index=True)
    target_price = models.DecimalField('目标价格', max_digits=10, decimal_places=3,
                                       null=True, blank=True, default=0)
    stop_price = models.DecimalField('止损价格', max_digits=10, decimal_places=3,
                                     null=True, blank=True, default=0)
    open_date = models.DateField('建仓日期', null=True, blank=True)
    close_date = models.DateField('平仓日期', null=True, blank=True)

    buy_qty = models.IntegerField('累计买入数量', default=0)
    sell_qty = models.IntegerField('累计卖出数量', default=0)
    buy_amount = models.DecimalField('累计买入金额', max_digits=14, decimal_places=2, default=0)
    sell_amount = models.DecimalField('累计卖出金额', max_digits=14, decimal_places=2, default=0)
    buy_fee = models.DecimalField('累计买入费用', max_digits=10, decimal_places=2, default=0)
    sell_fee = models.DecimalField('累计卖出费用', max_digits=10, decimal_places=2, default=0)
    total_fee = models.DecimalField('费用总计', max_digits=10, decimal_places=2, default=0)
    profit = models.DecimalField('盈利金额', max_digits=14, decimal_places=2, default=0)
    comments = models.TextField('备注', blank=True, default='')
    created_at = models.DateField('创建日期', auto_now_add=True)
    updated_at = models.DateField('更新日期', auto_now=True)

    _sold_cost = Decimal('0')

    class Meta:
        # 自定义模型在数据库中的显示名称
        db_table = 'models_trans_order'
        verbose_name = '交易订单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sold_cost = Decimal('0')

    def __str__(self):
        return f'{self.name}({self.code})-{self.get_status_display()}'

    @property
    def tscode(self):        
        return f'{self.code}.{self.market}'

    @property
    def position_qty(self):
        return self.buy_qty - self.sell_qty

    @property
    def position_cost(self):
        return self.buy_amount + self.buy_fee - getattr(self, '_sold_cost', Decimal('0'))

    @property
    def avg_cost(self):
        qty = self.position_qty
        if qty > 0:
            return self.position_cost / qty
        return Decimal('0')

    @property
    def hold_days(self):
        if self.open_date:
            end = self.close_date or timezone.now()
            return (end.date() - self.open_date.date()).days
        return 0

    @property
    def profit_ratio(self):
        cost = self.buy_amount + self.buy_fee
        if cost > 0:
            return (self.profit / cost * 100).quantize(Decimal('0.01'))
        return Decimal('0')

    def recalculate(self):
        deals = self.deals.all().order_by('date', 'id')
        position_qty = 0
        position_cost = Decimal('0')
        sold_cost = Decimal('0')
        buy_qty = 0
        sell_qty = 0
        buy_amount = Decimal('0')
        sell_amount = Decimal('0')
        buy_fee = Decimal('0')
        sell_fee = Decimal('0')
        profit = Decimal('0')
        first_buy_date = None

        for d in deals:
            if d.intent == TransDeal.INTENT_BUY:
                if position_qty == 0:
                    first_buy_date = d.date
                position_qty += d.qty
                position_cost += d.price * d.qty + d.fee
                buy_qty += d.qty
                buy_amount += d.price * d.qty
                buy_fee += d.fee
            else:
                if position_qty > 0:
                    avg = position_cost / position_qty
                    sold_cost += avg * d.qty
                    profit += d.price * d.qty - d.fee - avg * d.qty
                    position_cost -= avg * d.qty
                position_qty -= d.qty
                sell_qty += d.qty
                sell_amount += d.price * d.qty
                sell_fee += d.fee

        self.buy_qty = buy_qty
        self.sell_qty = sell_qty
        self.buy_amount = buy_amount
        self.sell_amount = sell_amount
        self.buy_fee = buy_fee
        self.sell_fee = sell_fee
        self.total_fee = buy_fee + sell_fee
        self.profit = profit.quantize(Decimal('0.01'))
        self._sold_cost = sold_cost

        if position_qty == 0 and sell_qty > 0:
            self.status = self.STATUS_CLOSED
            if not self.close_date:
                self.close_date = timezone.now()
        elif position_qty > 0:
            self.status = self.STATUS_OPEN
            self.close_date = None

        if first_buy_date and not self.open_date:
            self.open_date = datetime.datetime.combine(first_buy_date, datetime.time.min)

        self.save()
        return self


# ===================== 成交明细 =====================
class TransDeal(models.Model):
    INTENT_BUY = 'B'
    INTENT_SELL = 'S'
    INTENT_CHOICES = [
        (INTENT_BUY, '买入'),
        (INTENT_SELL, '卖出'),
    ]
    order = models.ForeignKey(TransOrder, on_delete=models.CASCADE,
                              related_name='deals', verbose_name='所属交易')
    intent = models.CharField('交易方向', max_length=1, choices=INTENT_CHOICES, default=INTENT_SELL)
    date = models.DateField('成交日期', default=timezone.now)
    price = models.DecimalField('成交价格', max_digits=10, decimal_places=3)
    qty = models.IntegerField('成交数量')
    amount = models.DecimalField('成交金额', max_digits=14, decimal_places=2, default=0)
    fee = models.DecimalField('成交费用', max_digits=10, decimal_places=2, default=0)
    comments = models.TextField('备注', blank=True, default='')
    created_at = models.DateField('创建日期', auto_now_add=True)

    class Meta:
        # 自定义模型在数据库中的显示名称
        db_table = 'models_trans_deal'
        verbose_name = '成交明细'
        verbose_name_plural = verbose_name
        ordering = ['date', 'id']

    def __str__(self):
        action = '买入' if self.intent == self.INTENT_BUY else '卖出'
        return f'{action} {self.order.code} {self.qty}@{self.price}'

    def save(self, *args, **kwargs):
        self.amount = (self.price * self.qty).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)
        self.order.recalculate()
        # 成交后记录资金变化快照
        self._record_cash_history()

    def _record_cash_history(self):
        """成交后更新资金配置并记录历史快照"""
        config = CashConfig.get_config()
        qty = Decimal(str(self.qty))
        amount = self.amount
        fee = self.fee

        if self.intent == self.INTENT_BUY:
            # 买入：现金减少，股票持仓成本增加，总资金因费用减少
            total_change = -fee
            cash_change = -(amount + fee)
            stock_change = amount
            reason = CashHistory.REASON_BUY
            remark = f'买入 {self.order.code} {self.qty}股@{self.price}'
        else:
            # 卖出：现金增加，股票持仓成本减少，总资金变化=盈亏
            avg_cost = self.order.avg_cost
            cost_part = (avg_cost * qty).quantize(Decimal('0.01'))
            total_change = (amount - fee - cost_part).quantize(Decimal('0.01'))
            cash_change = amount - fee
            stock_change = -cost_part
            reason = CashHistory.REASON_SELL
            remark = f'卖出 {self.order.code} {self.qty}股@{self.price}'

        config.total = (config.total + total_change).quantize(Decimal('0.01'))
        config.cash = (config.cash + cash_change).quantize(Decimal('0.01'))
        config.stock = (config.stock + stock_change).quantize(Decimal('0.01'))
        config.available = (config.available + cash_change).quantize(Decimal('0.01'))
        config.save()

        CashHistory.objects.create(
            total=config.total,
            cash=config.cash,
            stock=config.stock,
            reason=reason,
            amount=total_change,
            remark=remark,
            order=self.order,
        )

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        order.recalculate()


# ===================== 复盘记录 =====================
class TransReview(models.Model):
    """
    复盘记录：
    1. 已交易股票复盘：关联 TransOrder（order 不为空）
    2. 结束关注未交易复盘：仅关联 FocusStock（order 为空，focus 不为空）
    """
    order = models.OneToOneField(TransOrder, on_delete=models.CASCADE, null=True, blank=True,
                                 related_name='review', verbose_name='关联交易')
    focus = models.ForeignKey(FocusStock, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='reviews', verbose_name='关联关注')
    rating = models.IntegerField('评分', null=True, blank=True)
    comments = models.TextField('备注', blank=True, default='')
    created_at = models.DateField('创建日期', auto_now_add=True)
    updated_at = models.DateField('更新日期', auto_now=True)

    class Meta:
        # 自定义模型在数据库中的显示名称
        db_table = 'models_trans_review'
        verbose_name = '复盘记录'
        verbose_name_plural = verbose_name
        ordering = ['-updated_at']

    def __str__(self):
        if self.order:
            return f'复盘-{self.order.code}'
        if self.focus:
            return f'复盘(未交易)-{self.focus.code}'
        return '复盘-未知'

    @property
    def review_type(self):
        return 'traded' if self.order else 'focus_only'

    @property
    def display_code(self):
        if self.order:
            return self.order.code
        if self.focus:
            return self.focus.code
        return ''

    @property
    def display_name(self):
        if self.order:
            return self.order.name
        if self.focus:
            return self.focus.name
        return ''


# ===================== 股票筛选任务 =====================
class FilterTask(models.Model):
    """
    一次股票筛选（一个批次）。
    - 基于全量样本（StockList 中 hide 为空）的全新筛选：parent 为空
    - 在某次筛选结果上的二次筛选：parent 指向上次任务，样本取其结果
    conditions 以 JSON 文本存储条件列表，结构见 stock/filter.py
    """
    SOURCE_STOCK = 'stock'   # 全量样本
    SOURCE_TASK = 'task'     # 基于上次结果
    SOURCE_CHOICES = [
        (SOURCE_STOCK, '全量样本'),
        (SOURCE_TASK, '上次结果'),
    ]

    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_CHOICES = [
        (STATUS_RUNNING, '运行中'),
        (STATUS_DONE, '已完成'),
    ]

    name = models.CharField('任务名称', max_length=100, default='')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='children', verbose_name='上级筛选')
    source = models.CharField('样本来源', max_length=10, choices=SOURCE_CHOICES,
                             default=SOURCE_STOCK, db_index=True)
    conditions = models.TextField('筛选条件(JSON)', blank=True, default='[]')
    stock_count = models.IntegerField('结果数量', default=0)
    status = models.CharField('状态', max_length=10, choices=STATUS_CHOICES,
                              default=STATUS_DONE, db_index=True)
    remark = models.CharField('备注', max_length=200, blank=True, default='')
    created_at = models.DateField('创建日期', auto_now_add=True)
    updated_at = models.DateField('更新日期', auto_now=True)

    class Meta:
        db_table = 'models_filter_task'
        verbose_name = '筛选任务'
        verbose_name_plural = verbose_name
        ordering = ['-id']

    def __str__(self):
        return f'{self.name or self.id}({self.stock_count})'

    @property
    def condition_list(self):
        """解析 conditions JSON 为列表"""
        import json
        try:
            data = json.loads(self.conditions or '[]')
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def source_display_label(self):
        if self.parent_id:
            return f'基于 #{self.parent_id}'
        return '全量样本'


# ===================== 筛选结果股票 =====================
class FilterResult(models.Model):
    """某次筛选任务命中的单只股票，并支持在结果内打标记(1优先股/2潜力股)"""
    MARK_PREF = '1'   # 优先股
    MARK_POT = '2'    # 潜力股
    MARK_CHOICES = [
        ('', '无标记'),
        (MARK_PREF, '优先股'),
        (MARK_POT, '潜力股'),
    ]

    task = models.ForeignKey(FilterTask, on_delete=models.CASCADE,
                             related_name='results', verbose_name='所属筛选')
    code = models.CharField('代码', max_length=20, db_index=True)
    name = models.CharField('名称', max_length=50, default='')
    market = models.CharField('市场', max_length=10, default='SH')
    cat = models.CharField('类别', max_length=10, default='stock')
    mark = models.CharField('标记', max_length=2, choices=MARK_CHOICES, default='', blank=True)
    hide = models.CharField('隐藏', max_length=2, default='', blank=True,
                            help_text='1=已隐藏，同步 StockList.hide')
    sort_order = models.IntegerField('排序', default=1)

    class Meta:
        db_table = 'models_filter_result'
        verbose_name = '筛选结果'
        verbose_name_plural = verbose_name
        ordering = ['sort_order', 'id']
        unique_together = ('task', 'code', 'market')
        indexes = [models.Index(fields=['task', 'mark'])]

    def __str__(self):
        return f'{self.name}({self.code})'


# A股板块定义：(key, 中文名, 代码前缀元组)
BOARD_DEFS = [
    ('SH_MAIN', '上证主板', ('600', '601', '603', '605')),
    ('STAR',    '科创板',   ('688',)),
    ('SZ_MAIN', '深证主板', ('000', '001', '002', '003')),
    ('CHINEXT', '创业板',   ('300', '301')),
    ('BSE',     '北交所',   ('43', '83', '87', '88', '92')),
]
BOARD_KEYS = [b[0] for b in BOARD_DEFS]
BOARD_LABELS = {b[0]: b[1] for b in BOARD_DEFS}
BOARD_PREFIXES = {b[0]: b[2] for b in BOARD_DEFS}


def board_of_code(code):
    c = str(code)
    for key, _label, prefixes in BOARD_DEFS:
        if c.startswith(prefixes):
            return key
    return ''


class FilterGlobalConfig(models.Model):
    """全局筛选样本板块开关（单例表，不绑定 task）。"""
    enabled_boards = models.CharField('启用板块', max_length=100, default='', blank=True,
                                      help_text='逗号分隔的板块 key，空=全部启用')
    exclude_st = models.CharField('排除ST', max_length=2, default='1', blank=True,
                                  help_text='1=样本中排除名称含 ST 的股票')
    default_task_id = models.IntegerField('默认筛选任务ID', default=0, blank=True,
                                           help_text='筛选清单默认显示的任务ID，0=最新任务')

    class Meta:
        db_table = 'models_filter_global_config'
        verbose_name = '筛选全局配置'
        verbose_name_plural = verbose_name

    def is_exclude_st(self):
        return (self.exclude_st or '') == '1'

    def set_exclude_st(self, flag):
        self.exclude_st = '1' if flag else ''
        self.save()

    def get_enabled(self):
        raw = (self.enabled_boards or '').strip()
        if not raw:
            return set(BOARD_KEYS)
        return {k for k in raw.split(',') if k in BOARD_KEYS}

    def set_enabled(self, keys):
        keys = [k for k in keys if k in BOARD_KEYS]
        self.enabled_boards = ','.join(keys)
        self.save()

    @classmethod
    def load(cls):
        obj = cls.objects.first()
        if obj is None:
            obj = cls.objects.create(enabled_boards='', exclude_st='1')
        return obj
