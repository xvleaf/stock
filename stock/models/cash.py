from django.db import models
from django.utils import timezone


# ===================== 账户资金配置 =====================
class CashConfig(models.Model):
    total = models.DecimalField('资产', max_digits=14, decimal_places=2, default=100000)
    cash = models.DecimalField('现金', max_digits=14, decimal_places=2, default=100000)
    stock = models.DecimalField('股票', max_digits=14, decimal_places=2, default=0)
    allowance = models.DecimalField('风险额度', max_digits=14, decimal_places=2, default=2000)
    risk = models.DecimalField('风险资金', max_digits=14, decimal_places=2, default=0)
    profit = models.DecimalField('投资收益', max_digits=14, decimal_places=2, default=0)
    updated_at = models.DateField('更新日期', auto_now=True)

    class Meta:        
        # 自定义模型在数据库中的显示名称
        db_table = 'models_cash_config'
        verbose_name = '资金配置'
        verbose_name_plural = verbose_name

    @classmethod
    def get_config(cls):
        obj = cls.objects.filter(pk=1).first()
        if obj:
            return obj
        # 数据库为空时，资产/现金/股票/额度/风险/收益返回0，不创建记录
        return cls(
            pk=1, total=0, cash=0, stock=0,
            allowance=0, risk=0, profit=0,
        )

    @classmethod
    def has_config(cls):
        return cls.objects.filter(pk=1).exists()

    def __str__(self):
        return f'资金配置(风险额度:{self.allowance})'


# ===================== 资金变化历史 =====================
class CashHistory(models.Model):
    """资金变化历史 —— 记录每次总资金/现金/股票市值的变化节点及原因"""
    EVENT_DEPOSIT = 'deposit'       # 存入资金
    EVENT_WITHDRAW = 'withdraw'     # 取出资金
    EVENT_BUY = 'buy'               # 买入股票
    EVENT_SELL = 'sell'             # 卖出股票
    EVENT_DIVIDEND = 'dividend'     # 分红
    EVENT_ADJUST = 'adjust'         # 调整计划（修改目标/止损）
    EVENT_CHOICES = [
        (EVENT_DEPOSIT, '存入资金'),
        (EVENT_WITHDRAW, '取出资金'),
        (EVENT_BUY, '买入股票'),
        (EVENT_SELL, '卖出股票'),
        (EVENT_DIVIDEND, '股票分红'),
        (EVENT_ADJUST, '调整计划'),
    ]
    date = models.DateField('变化日期', default=timezone.now, db_index=True)
    total = models.DecimalField('资产', max_digits=14, decimal_places=2, default=0)
    cash = models.DecimalField('现金', max_digits=14, decimal_places=2, default=0)
    stock = models.DecimalField('股票', max_digits=14, decimal_places=2, default=0)
    risk = models.DecimalField('风险资金', max_digits=14, decimal_places=2, default=0)
    current_profit = models.DecimalField('本次收益', max_digits=14, decimal_places=2, default=0)
    total_profit = models.DecimalField('累计收益', max_digits=14, decimal_places=2, default=0)
    event = models.CharField('事项', max_length=20, choices=EVENT_CHOICES, default=EVENT_DEPOSIT)
    change = models.DecimalField('变动', max_digits=14, decimal_places=2, default=0,
                                 help_text='正数=增加, 负数=减少')
    remark = models.CharField('备注', max_length=200, blank=True, default='')
    order = models.ForeignKey('TransOrder', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='cash_histories', verbose_name='关联交易')
    created_at = models.DateField('创建日期', auto_now_add=True)

    class Meta:
        db_table = 'models_cash_history'
        verbose_name = '资金历史'
        verbose_name_plural = verbose_name
        # 资金历史仅按 id 排序（不按日期），撤销/取最新均以创建顺序为准
        ordering = ['-id']

    def __str__(self):
        return f'{self.date:%Y-%m-%d} {self.get_event_display()} {self.change:+}'

    @classmethod
    def snapshot(cls, event, change, remark='', order=None, date=None, current_profit=0):
        """
        快照当前资金状态并写入历史记录
        :param event: 变化事项（EVENT_* 常量）
        :param change: 变化金额（正增负减）
        :param remark: 备注
        :param order: 关联交易订单
        :param date: 指定变化日期，默认当天
        :param current_profit: 本次操作实际收益（正收益负损失）
        """
        config = CashConfig.get_config()
        cls.objects.create(
            total=config.total,
            cash=config.cash,
            stock=config.stock,
            risk=config.risk,
            current_profit=current_profit,
            total_profit=config.profit,
            event=event,
            change=change,
            remark=remark,
            order=order,
            date=date or timezone.now,
        )
