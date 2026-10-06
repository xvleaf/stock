from django.db import models
from decimal import Decimal


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


class FilterConfig(models.Model):
    """全局筛选样本板块开关（单例表，不绑定 task）。"""
    enabled_boards = models.CharField('启用板块', max_length=100, default='', blank=True,
                                      help_text='逗号分隔的板块 key，空=全部启用')
    exclude_st = models.CharField('排除ST', max_length=2, default='1', blank=True,
                                  help_text='1=样本中排除名称含 ST 的股票')
    default_task_id = models.IntegerField('默认筛选任务ID', default=-1, blank=True,
                                           help_text='筛选清单默认显示的任务ID，-1=无任务')
    # 筛选通用设置
    filter_timeout = models.IntegerField('筛选超时时间(秒)', default=3600)
    target_profit_ratio = models.DecimalField('添加关注目标价', max_digits=5, decimal_places=2, default=Decimal('1.1'))
    stop_loss_ratio = models.DecimalField('添加关注止损价', max_digits=5, decimal_places=2, default=Decimal('0.98'))

    class Meta:
        db_table = 'models_filter_config'
        verbose_name = '筛选配置'
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

    def __str__(self):
        return '筛选配置'
