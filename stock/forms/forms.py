from django import forms
from decimal import Decimal, ROUND_HALF_UP
from stock.models.models import CashConfig, FocusStock, TransDeal, TransReview
from django.utils import timezone

CAT_CHOICES = [
    ('stock', '股票'),
    # ('fund', '基金'),
    # ('bond', '债券'),
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

        if instance:
            # 根据股票类型设置价格字段精度
            step = '0.001' if instance.cat in ('fund', 'bond') else '0.01'
            for field_name in ('plan_price', 'target_price', 'stop_price'):
                if field_name in self.fields:
                    self.fields[field_name].widget.attrs['step'] = step

        # 处理编辑（非只读）时的初始值
        if instance and not view_mode:
            self.fields['cat_choice'].initial = instance.cat
            self.fields['market_choice'].initial = instance.market
            self.fields['intent_choice'].initial = instance.intent

        # 处理只读模式（详情页）
        if view_mode:
            self._make_readonly()

    def _make_readonly(self):
        """将表单中所有字段设为只读（适用于详情页）"""
        # 处理原生 Model 字段（来自 Meta.fields）
        for field_name in self.Meta.fields:
            widget = self.fields[field_name].widget
            # 若 widget 是 TextInput/NumberInput/Textarea 等，直接加 readonly
            if hasattr(widget, 'attrs'):
                widget.attrs['readonly'] = 'readonly'
            # 若 widget 是 Select 等，替换为只读文本框（显示显示值）
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                # 获取当前字段的显示值（需实例存在）
                instance = getattr(self, 'instance', None)
                if instance:
                    display_val = getattr(instance, 'get_{}_display'.format(field_name), lambda: None)()
                    if display_val is None:  # fallback
                        display_val = getattr(instance, field_name, '')
                else:
                    display_val = ''
                self.fields[field_name] = forms.CharField(
                    label=self.fields[field_name].label,
                    widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
                    required=False,
                    initial=display_val,
                )

        # 处理额外的三个 ChoiceField（cat_choice, market_choice, intent_choice）
        choice_field_names = ['cat_choice', 'market_choice', 'intent_choice']
        for name in choice_field_names:
            # 获取当前实例的显示值
            instance = getattr(self, 'instance', None)
            if instance:
                # 假设字段名与模型字段对应（cat→cat_choice）
                model_field = name.replace('_choice', '')
                choices = getattr(self.fields[name], 'choices', [])
                display_val = dict(choices).get(getattr(instance, model_field, ''), '')
            else:
                display_val = ''
            self.fields[name] = forms.CharField(
                label=self.fields[name].label,
                widget=forms.TextInput(attrs={'class': 'form-control', 'readonly': 'readonly'}),
                required=False,
                initial=display_val,
            )


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
