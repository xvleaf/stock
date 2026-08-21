# Ashare 股票行情数据双核心版 ( https://github.com/mpquant/Ashare )
import json, requests, datetime
import pandas as pd

# --- 腾讯日线 ---  2025-12-21 正常使用
def get_price_day_tx(code, end_date='', count=10, frequency='1d'):     # 日线获取  
    unit = 'week' if frequency in '1w' else 'month' if frequency in '1M' else 'day'
    if end_date:
        end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.date) else end_date.split(' ')[0]
    end_date = '' if end_date == datetime.datetime.now().strftime('%Y-%m-%d') else end_date
    URL = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{unit},,{end_date},{count},qfq'
    st = json.loads(requests.get(URL).content)
    ms = 'qfq' + unit
    stk = st['data'][code]
    buf = stk[ms] if ms in stk else stk[unit]       # 指数返回不是 qfqday，是 day
    df = pd.DataFrame(buf, columns=['time', 'open', 'close', 'high', 'low', 'volume'], dtype='float')
    df.time = pd.to_datetime(df.time)
    df.set_index(['time'], inplace=True)
    df.index.name = ''
    return df

# 腾讯分钟线
def get_price_min_tx(code, end_date=None, count=10, frequency='1d'):    # 分钟线获取 
    ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1
    if end_date:
        end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.date) else end_date.split(' ')[0]
    URL = f'http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={code},m{ts},,{count}'
    st = json.loads(requests.get(URL).content)
    buf = st['data'][code]['m' + str(ts)]
    df = pd.DataFrame(buf, columns=['time', 'open', 'close', 'high', 'low', 'volume', 'n1', 'n2'])
    df = df[['time', 'open', 'close', 'high', 'low', 'volume']]
    df[['open', 'close', 'high', 'low', 'volume']] = df[['open', 'close', 'high', 'low', 'volume']].astype('float')
    df.time = pd.to_datetime(df.time)
    df.set_index(['time'], inplace=True)
    df.index.name = ''
    # 修复 FutureWarning：使用 iloc + get_loc 替代链式赋值和整数键
    df.iloc[-1, df.columns.get_loc('close')] = float(st['data'][code]['qt'][code][3])  # 最新基金数据是3位的
    return df

# sina新浪全周期获取函数，分钟线 5m,15m,30m,60m  日线1d=240m   周线1w=1200m  1月=7200m
def get_price_sina(code, end_date='', count=10, frequency='60m'):    # 新浪全周期获取函数    
    frequency = frequency.replace('1d', '240m').replace('1w', '1200m').replace('1M', '7200m')
    mcount = count
    ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1
    if (end_date != '') and (frequency in ['240m', '1200m', '7200m']):
        end_date = pd.to_datetime(end_date) if not isinstance(end_date, datetime.date) else end_date
        unit = 4 if frequency == '1200m' else 29 if frequency == '7200m' else 1
        count = count + (datetime.datetime.now() - end_date).days // unit
    URL = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale={ts}&ma=5&datalen={count}'
    dstr = json.loads(requests.get(URL).content)
    df = pd.DataFrame(dstr, columns=['day', 'open', 'high', 'low', 'close', 'volume'])
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df.day = pd.to_datetime(df.day)
    df.set_index(['day'], inplace=True)
    df.index.name = ''
    if (end_date != '') and (frequency in ['240m', '1200m', '7200m']):
        return df[df.index <= end_date][-mcount:]
    return df

def get_price(code, end_date='', count=10, frequency='1d', fields=[]):        # 对外暴露只有唯一函数
    xcode = code.replace('.XSHG', '').replace('.XSHE', '')
    xcode = 'sh' + xcode if ('XSHG' in code) else 'sz' + xcode if ('XSHE' in code) else code

    if frequency in ['1d', '1w', '1M']:   # 日线、周线、月线
        try:            
            return get_price_day_tx(xcode, end_date=end_date, count=count, frequency=frequency)
        except:
            return get_price_sina(xcode, end_date=end_date, count=count, frequency=frequency)
    if frequency in ['1m', '5m', '15m', '30m', '60m']:  # 分钟线
        if frequency in '1m':
            return get_price_min_tx(xcode, end_date=end_date, count=count, frequency=frequency)
        try:
            return get_price_sina(xcode, end_date=end_date, count=count, frequency=frequency)
        except:
            return get_price_min_tx(xcode, end_date=end_date, count=count, frequency=frequency)

if __name__ == '__main__':
    df = get_price('sh000001', frequency='1d', count=10)      # 支持 '1d' 日, '1w' 周, '1M' 月
    print('上证指数日线行情\n', df)

    df = get_price('000001.XSHG', frequency='15m', count=10)  # 支持 '1m','5m','15m','30m','60m'
    print('上证指数分钟线\n', df)