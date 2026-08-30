from django import forms
from decimal import Decimal, ROUND_HALF_UP
from stock.models.models import CashConfig, FocusStock, TransDeal, TransReview
from django.utils import timezone

CAT_CHOICES = [
    ('stock', '股票'),
    ('fund', '基金'),
    ('bond', '债券'),
    ('index', '指数')
]
MARKET_CHOICES = [
    ('SH', '上海'),
    ('SZ', '深圳'),
    ('BJ', '北京')
]
INTENT_CHOICES = [
    ('B', '买入'), 
    ('S', '卖出')
]


class DateInput(forms.DateInput):
    input_type = 'date'


class FocusStockForm(forms.ModelForm):
    cat_choice = forms.ChoiceField(
        label='股票类型',
        choices=CAT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
    )

    market_choice = forms.ChoiceField(
        label='股票市场',
        choices=MARKET_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
    )

    intent_choice = forms.ChoiceField(
        label='交易方向',
        choices=INTENT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
    )

    focus_date = forms.DateField(
        label='关注日期',
        widget=forms.DateInput(
            attrs={'class': 'form-control', 'type': 'date'}, 
            format='%Y-%m-%d'
        ),
        input_formats=['%Y-%m-%d'],
        required=True,
        initial=timezone.now,
    )
    
    class Meta:
        model = FocusStock
        fields = ['code', 'name', 'focus_date',
                  'plan_price', 'plan_qty', 'target_price',
                  'stop_price', 'allowed_qty', 'win_ratio',
                  'comments']
        widgets = {
            'code': forms.TextInput(attrs={
                'class': 'form-control', 'id': 'id_code_input',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control', 'id': 'id_name_input', 'readonly': 'readonly',
            }),
            'plan_price': forms.NumberInput(attrs={
                'class': 'form-control','step': '0.01', 'id': 'id_plan_price',
            }),
            'plan_qty': forms.NumberInput(attrs={
                'class': 'form-control', 'id': 'id_plan_qty',
            }),
            'target_price': forms.NumberInput(attrs={
                'class': 'form-control','step': '0.01', 'id': 'id_target_price',
            }),
            'stop_price': forms.NumberInput(attrs={
                'class': 'form-control','step': '0.01', 'id': 'id_stop_price',
            }),
            'allowed_qty': forms.NumberInput(attrs={
                'class': 'form-control', 'readonly': True, 'id': 'id_allowed_qty',
            }),
            'win_ratio': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '1', 'min': '0', 'max': '99',
                'id': 'id_win_ratio', 'readonly': 'readonly',
            }),
            'comments': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3, 'style': 'resize:none;',
            }),
        }

    def __init__(self, *args, **kwargs):
        # 从 kwargs 中提取 view_mode 参数，默认 False（添加页）
        view_mode = kwargs.pop('view_mode', False)
        instance = kwargs.get('instance')
        super().__init__(*args, **kwargs)


        # 设置小数位数
        cat = instance.cat if instance else 'stock'  # 默认股票
        deci = 2 if cat == 'stock' else 3
        step = '0.01' if cat == 'stock' else '0.001'
        for field_name in ['plan_price', 'target_price', 'stop_price']:
            if instance and field_name in self.fields:
                value = getattr(instance, field_name)
                if value is not None:
                    # 四舍五入到指定位数，并格式化为字符串（保留指定位数的小数）
                    quantized = value.quantize(Decimal('0.' + '0' * deci), rounding=ROUND_HALF_UP)
                    self.initial[field_name] = quantized

        if view_mode:
            # 获取显示名称
            cat_display = dict(CAT_CHOICES).get(instance.cat, instance.cat) if instance else ''
            market_display = dict(MARKET_CHOICES).get(instance.market, instance.market) if instance else ''
            intent_display = dict(INTENT_CHOICES).get(instance.intent, instance.intent) if instance else ''

            # 只读模式（详情页）：将 cat_choice 和 market_choice 改为只读文本输入框
            self.fields['cat_choice'] = forms.CharField(
                label='股票类型',
                widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
                required=False,
                initial=cat_display
            )
            self.fields['market_choice'] = forms.CharField(
                label='股票市场',
                widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
                required=False,
                initial=market_display
            )
            self.fields['intent_choice'] = forms.CharField(
                label='交易方向',
                widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
                required=False,
                initial=intent_display
            )
        else:
            # 添加页：保持下拉菜单
            # 如果有 instance（编辑时），设置初始值
            if instance:
                self.fields['cat_choice'].initial = instance.cat
                self.fields['market_choice'].initial = instance.market
                self.fields['intent_choice'].initial = instance.intent


class TransDealForm(forms.ModelForm):
    """成交填报表单"""
    class Meta:
        model = TransDeal
        fields = ['intent', 'date', 'price', 'qty', 'fee', 'comments']
        widgets = {
            'intent': forms.Select(
                attrs={'class': 'form-select'},
                choices=[('B', '买入'), ('S', '卖出')]
            ),
            'date': DateInput(attrs={'class': 'form-control'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'qty': forms.NumberInput(attrs={'class': 'form-control'}),
            'fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'comments': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2, 'style': 'resize:none;',
            }),
        }


class CashConfigForm(forms.ModelForm):
    """账户资金与费率设置"""
    class Meta:
        model = CashConfig
        fields = [
            'total', 'available', 'commission_ratio', 'commission_min', 
            'stamp_buy_ratio', 'stamp_sell_ratio'
        ]
        widgets = {
            'total': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'available': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'commission_ratio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.00001'}),
            'commission_min': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'stamp_buy_ratio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.00001'}),
            'stamp_sell_ratio': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.00001'}),
        }


class ReviewForm(forms.ModelForm):
    """复盘表单（仅备注+评分）"""
    RATING_CHOICES = [
        ('', '未评分'), (1, '★'), (2, '★★'),
        (3, '★★★'), (4, '★★★★'), (5, '★★★★★'),
    ]
    rating = forms.IntegerField(
        label='评分', required=False,
        widget=forms.Select(attrs={'class': 'form-select'}, choices=RATING_CHOICES),
    )

    def clean_rating(self):
        val = self.cleaned_data.get('rating')
        return val if val else None

    class Meta:
        model = TransReview
        fields = ['rating', 'comments']
        widgets = {
            'comments': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3, 'style': 'resize:none;',
            }),
        }
        labels = {
            'comments': '备注',
        }
