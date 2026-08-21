from django import forms
from stock.models.models import CashConfig, FocusStock, TransDeal, TransReview
from django.utils import timezone

class DateInput(forms.DateInput):
    input_type = 'date'


class FocusStockForm(forms.ModelForm):
    cat_choice = forms.ChoiceField(
        label='股票类型',
        choices=[('stock', '股票'), ('fund', '基金'), ('bond', '债券')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
    )

    market_choice = forms.ChoiceField(
        label='股票市场',
        choices=[('SH', '上海'), ('SZ', '深圳'), ('BJ', '北京')],
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True,
    )

    intent_choice = forms.ChoiceField(
        label='交易方向',
        choices=[('B', '买入'), ('S', '卖出')],
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
                'class': 'form-control', 'step': '0.01', 'id': 'id_plan_price',
            }),
            'plan_qty': forms.NumberInput(attrs={
                'class': 'form-control', 'id': 'id_plan_qty',
            }),
            'target_price': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'id': 'id_target_price',
            }),
            'stop_price': forms.NumberInput(attrs={
                'class': 'form-control', 'step': '0.01', 'id': 'id_stop_price',
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
