from django.db import models
from django.utils import timezone
from decimal import Decimal
import datetime

from .focus import FocusStock


# ===================== 交易订单 =====================
class TransOrder(models.Model):
    STATUS_OPEN = 'open'
    STATUS_CLOSED = 'closed'
    STATUS_CHOICES = [
        (STATUS_OPEN, '持仓中'),
        (STATUS_CLOSED, '已平仓'),
    ]
    INTENT_BUY = 'B'
    INTENT_SELL = 'S'
    INTENT_CHOICES = [
        (INTENT_BUY, '买入'),
        (INTENT_SELL, '卖出'),
    ]
    focus = models.ForeignKey(FocusStock, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='orders', verbose_name='关联关注')
    code = models.CharField('股票代码', max_length=20, db_index=True)
    name = models.CharField('股票名称', max_length=50)
    market = models.CharField('股票市场', max_length=10, default='SH')
    cat = models.CharField('股票类型', max_length=10, default='stock')
    intent = models.CharField('交易方向', max_length=1, choices=INTENT_CHOICES, default=INTENT_BUY)
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
    risk_amount = models.DecimalField('风险资金占用', max_digits=14, decimal_places=2, default=0)
    # 含手续费持仓成本 = 当前持仓的含手续费成本（多头为正，空头为负）
    # 反手做空时为负数，表示欠股票的含手续费成本
    # 用于计算 avg_cost（含手续费持仓均价）= abs(position_cost / position_qty)
    position_cost = models.DecimalField('含手续费持仓成本', max_digits=14, decimal_places=2, default=0)
    # 不含手续费持仓成本 = 当前持仓的不含手续费成本（多头为正，空头为负）
    # 用于计算 avg_cost_no_fee（不含手续费持仓均价）和盈利机会
    position_cost_no_fee = models.DecimalField('不含手续费持仓成本', max_digits=14, decimal_places=2, default=0)
    # 含手续费累计卖出成本 = 每次卖出平仓时按当时含手续费均价 × 平仓数量 的累加
    # 用于计算 position_cost（含手续费持仓成本）= buy_amount + buy_fee - sold_cost
    # 进而计算 avg_cost（含手续费持仓均价）= position_cost / position_qty
    sold_cost = models.DecimalField('含手续费累计卖出成本', max_digits=14, decimal_places=2, default=0)
    # 盈利机会（0-99整数），每次交易或修改目标价/止损价后重新计算并保存
    # 计算方式：calc_win_ratio(avg_cost, target_price, stop_price, intent)
    win_ratio = models.IntegerField('盈利机会', default=0)
    created_at = models.DateField('创建日期', auto_now_add=True)
    updated_at = models.DateField('更新日期', auto_now=True)

    class Meta:
        # 自定义模型在数据库中的显示名称
        db_table = 'models_trans_order'
        verbose_name = '交易订单'
        verbose_name_plural = verbose_name
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name}({self.code})-{self.get_status_display()}'

    @property
    def tscode(self):        
        return f'{self.code}.{self.market}'

    @property
    def position_qty(self):
        return self.buy_qty - self.sell_qty

    @property
    def avg_cost(self):
        qty = self.position_qty
        if qty != 0:
            return abs(self.position_cost / qty)
        return Decimal('0')

    @property
    def avg_cost_no_fee(self):
        qty = self.position_qty
        if qty != 0:
            return abs(self.position_cost_no_fee / qty)
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
        histories = self.histories.all().order_by('date', 'id')
        position_qty = 0
        position_cost = Decimal('0')        # 含手续费，用于avg_cost显示
        position_cost_no_fee = Decimal('0') # 不含手续费，用于profit计算
        sold_cost = Decimal('0')
        buy_qty = 0
        sell_qty = 0
        buy_amount = Decimal('0')
        sell_amount = Decimal('0')
        buy_fee = Decimal('0')
        sell_fee = Decimal('0')
        profit = Decimal('0')
        first_buy_date = None
        short_avg_cost = Decimal('0')  # 卖空均价（不含费）

        for d in histories:
            if d.action == TransHistory.ACTION_EDIT:
                continue  # 编辑记录不参与持仓计算
            if d.action == TransHistory.ACTION_DIVIDEND:
                # 分红记录：实时处理
                if d.dividend_amount > 0:
                    # 现金分红：折减持仓成本（含手续费和不含手续费都扣除）
                    position_cost -= d.dividend_amount
                    position_cost_no_fee -= d.dividend_amount
                if d.qty > 0 and position_qty != 0:
                    # 送股：按比例增加持仓数量，成本不变，均价摊薄
                    position_qty += d.qty
                    # 送股同时累加到累计买卖数量，保证 buy_qty - sell_qty == position_qty
                    # 否则 recalculate 重算 buy_qty/sell_qty 会丢失送股数，
                    # 导致 position_qty（property）偏小、avg_cost 偏大（未摊薄送股）
                    if position_qty > 0:
                        buy_qty += d.qty
                    else:
                        sell_qty += d.qty
                continue
            if d.intent == TransHistory.INTENT_BUY:
                if position_qty >= 0:
                    # 多头或空仓：买入建仓/加仓
                    if position_qty == 0:
                        first_buy_date = d.date
                    position_qty += d.qty
                    position_cost += d.price * d.qty + d.fee
                    position_cost_no_fee += d.price * d.qty
                    profit -= d.fee  # 买入手续费计入损失
                else:
                    # 空头持仓：买入平仓（可能反手）
                    short_qty = abs(position_qty)
                    if d.qty <= short_qty:
                        # 全部用于空头平仓
                        close_qty = d.qty
                        close_amount = d.price * close_qty
                        close_fee = d.fee * (Decimal(close_qty) / Decimal(d.qty)) if d.qty > 0 else d.fee
                        profit += short_avg_cost * close_qty - close_amount - close_fee
                        # 按比例减少 position_cost 和 position_cost_no_fee
                        avg = position_cost / abs(position_qty)
                        avg_no_fee = position_cost_no_fee / abs(position_qty)
                        position_cost -= avg * close_qty
                        position_cost_no_fee -= avg_no_fee * close_qty
                        position_qty += close_qty
                        # 空头减少，short_avg_cost 不变
                    else:
                        # 先平空头，再买多建仓
                        close_qty = short_qty
                        close_amount = d.price * close_qty
                        close_fee = d.fee * (Decimal(close_qty) / Decimal(d.qty))
                        profit += short_avg_cost * close_qty - close_amount - close_fee
                        position_qty += close_qty  # 变为0
                        # 剩余部分买多建仓
                        remain_qty = d.qty - close_qty
                        remain_fee = d.fee - close_fee
                        first_buy_date = d.date
                        position_qty += remain_qty
                        position_cost = d.price * remain_qty + remain_fee
                        position_cost_no_fee = d.price * remain_qty
                        profit -= remain_fee
                        short_avg_cost = Decimal('0')
                buy_qty += d.qty
                buy_amount += d.price * d.qty
                buy_fee += d.fee
            else:
                # 卖出
                if position_qty <= 0:
                    # 空头或空仓：卖出建仓/加仓
                    if position_qty == 0:
                        first_buy_date = d.date
                        short_avg_cost = d.price  # 卖空均价（不含费）
                        position_cost = -(d.price * d.qty + d.fee)
                        position_cost_no_fee = -(d.price * d.qty)
                    else:
                        # 卖空加仓，更新加权平均
                        total_short = abs(position_qty) + d.qty
                        short_avg_cost = (short_avg_cost * abs(position_qty) + d.price * d.qty) / total_short
                        position_cost -= (d.price * d.qty + d.fee)
                        position_cost_no_fee -= d.price * d.qty
                    position_qty -= d.qty
                    profit -= d.fee  # 卖出手续费计入损失
                else:
                    # 多头持仓：卖出平仓（可能反手）
                    if d.qty <= position_qty:
                        # 全部用于多头平仓
                        avg = position_cost / position_qty
                        avg_no_fee = position_cost_no_fee / position_qty
                        close_qty = d.qty
                        sold_cost += avg * close_qty
                        profit += d.price * close_qty - d.fee - avg_no_fee * close_qty
                        position_cost -= avg * close_qty
                        position_cost_no_fee -= avg_no_fee * close_qty
                        position_qty -= close_qty
                    else:
                        # 先平多头，再卖空建仓
                        avg = position_cost / position_qty
                        avg_no_fee = position_cost_no_fee / position_qty
                        close_qty = position_qty
                        close_fee = d.fee * (Decimal(close_qty) / Decimal(d.qty))
                        sold_cost += avg * close_qty
                        profit += d.price * close_qty - close_fee - avg_no_fee * close_qty
                        position_cost = Decimal('0')
                        position_cost_no_fee = Decimal('0')
                        position_qty = 0
                        # 剩余部分卖空建仓
                        remain_qty = d.qty - close_qty
                        remain_fee = d.fee - close_fee
                        short_avg_cost = d.price
                        position_cost = -(d.price * remain_qty + remain_fee)
                        position_cost_no_fee = -(d.price * remain_qty)
                        position_qty -= remain_qty
                        profit -= remain_fee
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
        # profit 不加上分红金额（分红不算收益，仅是市值转现金；分红已在遍历中实时扣除持仓成本）
        self.profit = profit.quantize(Decimal('0.01'))
        # 保存含手续费持仓成本（多头为正，空头为负），用于从数据库重新获取时正确计算 avg_cost
        self.position_cost = position_cost.quantize(Decimal('0.01'))
        self.position_cost_no_fee = position_cost_no_fee.quantize(Decimal('0.01'))
        # 保存含手续费累计卖出成本
        self.sold_cost = sold_cost.quantize(Decimal('0.01'))

        # 更新 intent
        if position_qty > 0:
            self.intent = TransHistory.INTENT_BUY
        elif position_qty < 0:
            self.intent = TransHistory.INTENT_SELL

        if position_qty == 0 and sell_qty > 0:
            self.status = self.STATUS_CLOSED
            # 从 histories 中获取最后一笔实际交易（非编辑、非分红）的日期作为平仓日期
            last_close_date = None
            for d in reversed(list(histories)):
                if d.action not in (TransHistory.ACTION_EDIT, TransHistory.ACTION_DIVIDEND):
                    last_close_date = d.date
                    break
            if last_close_date:
                self.close_date = last_close_date
            elif not self.close_date:
                self.close_date = timezone.now()
        elif position_qty != 0:
            self.status = self.STATUS_OPEN
            self.close_date = None

        if first_buy_date and not self.open_date:
            self.open_date = datetime.datetime.combine(first_buy_date, datetime.time.min)

        self.save()
        return self


# ===================== 交易历史（成交+编辑） =====================
class TransHistory(models.Model):
    INTENT_BUY = 'B'
    INTENT_SELL = 'S'
    INTENT_CHOICES = [
        (INTENT_BUY, '买入'),
        (INTENT_SELL, '卖出'),
    ]
    ACTION_BUY = 'buy'
    ACTION_SELL = 'sell'
    ACTION_EDIT = 'edit'
    ACTION_DIVIDEND = 'dividend'
    ACTION_CHOICES = [
        (ACTION_BUY, '买入'),
        (ACTION_SELL, '卖出'),
        (ACTION_EDIT, '调整'),
        (ACTION_DIVIDEND, '分红'),
    ]
    order = models.ForeignKey(TransOrder, on_delete=models.CASCADE,
                              related_name='histories', verbose_name='所属交易')
    action = models.CharField('操作类型', max_length=10, choices=ACTION_CHOICES, default=ACTION_BUY)
    intent = models.CharField('交易方向', max_length=1, choices=INTENT_CHOICES, default=INTENT_BUY)
    date = models.DateField('操作日期', default=timezone.now)
    price = models.DecimalField('成交价格', max_digits=10, decimal_places=3, default=0)
    qty = models.IntegerField('成交数量', default=0)
    amount = models.DecimalField('成交金额', max_digits=14, decimal_places=2, default=0)
    fee = models.DecimalField('交易费用', max_digits=10, decimal_places=2, default=0)
    target_price = models.DecimalField('目标价格', max_digits=10, decimal_places=3, default=0)
    stop_price = models.DecimalField('止损价格', max_digits=10, decimal_places=3, default=0)
    comments = models.TextField('备注', blank=True, default='')
    created_at = models.DateField('创建日期', auto_now_add=True)
    # 该笔交易后的持仓快照
    profit = models.DecimalField('账面收益', max_digits=14, decimal_places=2, default=0)
    win_ratio = models.IntegerField('盈利机会', default=0)
    risk_amount = models.DecimalField('风险资金', max_digits=14, decimal_places=2, default=0)
    position_qty = models.IntegerField('持仓数量', default=0)
    avg_cost = models.DecimalField('持仓均价', max_digits=10, decimal_places=3, default=0)
    avg_cost_no_fee = models.DecimalField('不含费持仓均价', max_digits=10, decimal_places=3, default=0)
    dividend_amount = models.DecimalField('分红金额', max_digits=14, decimal_places=2, default=0)
    dividend_tax = models.DecimalField('红利税', max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = 'models_trans_history'
        verbose_name = '交易历史'
        verbose_name_plural = verbose_name
        ordering = ['date', 'id']

    def __str__(self):
        if self.action == self.ACTION_EDIT:
            return f'编辑 {self.order.code} 目标={self.target_price} 止损={self.stop_price}'
        action = '买入' if self.intent == self.INTENT_BUY else '卖出'
        return f'{action} {self.order.code} {self.qty}@{self.price}'

    def save(self, *args, **kwargs):
        if self.action not in (self.ACTION_EDIT, self.ACTION_DIVIDEND):
            self.amount = (Decimal(str(self.price)) * self.qty).quantize(Decimal('0.01'))
        elif self.action == self.ACTION_DIVIDEND:
            self.amount = Decimal('0')
        super().save(*args, **kwargs)
        self.order.recalculate()

    def delete(self, *args, **kwargs):
        order = self.order
        super().delete(*args, **kwargs)
        order.recalculate()


# ===================== 分红记录 =====================
class DividendRecord(models.Model):
    """股票分红记录（现金分红/送股）"""
    DIVIDEND_CASH = 'cash'
    DIVIDEND_BONUS = 'bonus'
    DIVIDEND_CHOICES = [
        (DIVIDEND_CASH, '分红'),
        (DIVIDEND_BONUS, '送股'),
    ]
    order = models.ForeignKey(TransOrder, on_delete=models.CASCADE,
                              related_name='dividends', verbose_name='所属交易')
    code = models.CharField('股票代码', max_length=20, db_index=True)
    name = models.CharField('股票名称', max_length=50)
    market = models.CharField('股票市场', max_length=10, default='SH')
    date = models.DateField('分红日期', default=timezone.now)
    dividend_type = models.CharField('分红类型', max_length=10, choices=DIVIDEND_CHOICES, default=DIVIDEND_CASH)
    per_share = models.DecimalField('每股分红(税前)', max_digits=10, decimal_places=4, default=0)
    bonus_ratio = models.DecimalField('送股比例', max_digits=8, decimal_places=4, default=0)
    amount = models.DecimalField('税前分红总额', max_digits=14, decimal_places=2, default=0)
    qty_change = models.IntegerField('持仓变化数量', default=0)
    remark = models.CharField('备注', max_length=200, blank=True, default='')
    created_at = models.DateField('创建日期', auto_now_add=True)

    class Meta:
        db_table = 'models_dividend_record'
        verbose_name = '分红记录'
        verbose_name_plural = verbose_name
        ordering = ['-date', '-id']

    def __str__(self):
        return f'{self.date:%Y-%m-%d} {self.name} {self.get_dividend_type_display()}'


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
