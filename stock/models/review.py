from django.db import models

from .focus import FocusStock
from .trans import TransOrder


class ReviewList(models.Model):
    """复盘列表：已清仓交易 / 已关闭关注的汇总记录"""
    TYPE_TRANS = 'trans'
    TYPE_FOCUS = 'focus'
    TYPE_CHOICES = [
        (TYPE_TRANS, '交易'),
        (TYPE_FOCUS, '关注'),
    ]
    RATING_CHOICES = [
        (1, '优'),
        (2, '良'),
        (3, '中'),
        (4, '差'),
    ]

    review_type = models.CharField('复盘类型', max_length=10, choices=TYPE_CHOICES, db_index=True)
    trans_order = models.ForeignKey(TransOrder, on_delete=models.CASCADE, null=True, blank=True,
                                    related_name='reviews', verbose_name='关联交易')
    focus_stock = models.ForeignKey(FocusStock, on_delete=models.CASCADE, null=True, blank=True,
                                    related_name='focus_reviews', verbose_name='关联关注')
    code = models.CharField('股票代码', max_length=20, db_index=True)
    market = models.CharField('股票市场', max_length=10, default='SH')
    name = models.CharField('股票名称', max_length=50)
    cat = models.CharField('股票类型', max_length=10, default='stock')
    open_date = models.DateField('建仓/关注日期', null=True, blank=True)
    close_date = models.DateField('平仓/关闭日期', null=True, blank=True, db_index=True)
    # 交易模式字段
    profit = models.DecimalField('收益金额', max_digits=14, decimal_places=2, default=0)
    profit_ratio = models.DecimalField('综合收益比例(%)', max_digits=10, decimal_places=2, default=0)
    # 关注模式字段
    plan_price = models.DecimalField('计划报价', max_digits=10, decimal_places=3, null=True, blank=True)
    target_price = models.DecimalField('目标价格', max_digits=10, decimal_places=3, null=True, blank=True)
    # 通用字段
    rating = models.IntegerField('评级', choices=RATING_CHOICES, null=True, blank=True)
    comments = models.TextField('备注', blank=True, default='')
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        db_table = 'models_review_list'
        verbose_name = '复盘列表'
        verbose_name_plural = verbose_name
        ordering = ['-close_date', '-id']

    def __str__(self):
        return f'{self.get_review_type_display()}-{self.name}({self.code})'
