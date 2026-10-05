from django.db import models


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
        ordering = ['code']

    def __str__(self):
        return f'{self.name}({self.code})'


# ===================== 股票-板块关联 =====================
class StockSector(models.Model):
    stock_code = models.CharField(max_length=20, db_index=True)
    stock_market = models.CharField(max_length=10)
    sector_code = models.CharField(max_length=20, db_index=True)
    sector_market = models.CharField(max_length=10, default='SW')

    class Meta:
        db_table = 'models_stock_sector'
        verbose_name = '板块关联'
        verbose_name_plural = verbose_name
        unique_together = ('stock_code', 'stock_market', 'sector_code', 'sector_market')
        ordering = ['stock_code']

    def __str__(self):
        return f'{self.stock_code}-{self.sector_code}'
