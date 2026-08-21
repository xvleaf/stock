from . import ashare


def get_last_price(tscode, deci=2):
    
    """
    获取指定股票当前最新价格及基于前一交易日收盘价的涨跌幅（百分比）
    :param tscode: tscode: str 000333.SZ
    :return: (current_close, change_percent) 
             current_close: float，最新成交价
             change_percent: float，涨跌幅（%），例如 3.5 表示上涨3.5%
             失败或无法计算时返回 (--, --)
    """
    tscode = tscode.upper()
    if tscode.endswith('.SZ'):
        code = 'sz' + tscode.replace('.SZ', '')
    else:
        code = 'sh' + tscode.replace('.SH', '')

    try:
        # ashare 获取的 frequency='1d' 数据不含当天交易数据，因此采用 1 分钟来计算
        df = ashare.get_price(code, frequency='1m', count=300)
        if df is None or df.empty:
            return '--', '--'

        df = df.sort_index()
        trade_dates = sorted(df.index.normalize().unique().date)
        if not trade_dates:
            return '--', '--'

        # 最新交易日
        latest_date = trade_dates[-1]
        latest_df = df[df.index.date == latest_date]
        if latest_df.empty:
            return '--', '--'

        # 当前价（最新一笔成交）
        current_close = float(latest_df.iloc[-1]['close'])

        # 计算前收盘价
        if len(trade_dates) >= 2:
            prev_date = trade_dates[-2]
            prev_df = df[df.index.date == prev_date]
            if prev_df.empty:
                return '--', '--'
            pre_close = float(prev_df.iloc[-1]['close'])
        else:
            # 仅一个交易日（如新股首日）
            return current_close, '--'

        # 计算涨跌幅（百分比）
        change_percent = (current_close - pre_close) / pre_close * 100
        return current_close, round(change_percent, 2)

    except Exception:
        return '--', '--'
