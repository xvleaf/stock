from django.db import models
from django.utils import timezone
from decimal import Decimal


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
        ordering = ['code']

    def __str__(self):
        return f'{self.name}({self.code})'


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

    def save_history(self, action='edit', comments=''):
        """保存当前关注信息到历史记录"""
        FocusHistory.objects.create(
            focus=self, 
            action=action,
            edit_date=self.focus_date,
            intent=self.intent,
            plan_price=self.plan_price,
            plan_qty=self.plan_qty,
            target_price=self.target_price,
            stop_price=self.stop_price,
            win_ratio=self.win_ratio,
            comments=comments,
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
