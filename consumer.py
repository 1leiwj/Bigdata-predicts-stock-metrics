from kafka import KafkaConsumer
import json
import numpy as np
from flask_socketio import SocketIO, emit

# 创建Kafka消费者
consumer = KafkaConsumer(
    'stock_data',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda m: json.loads(m.decode('utf-8'))
)

def calculate_kdj(prices, period=9):
    """
    计算KDJ指标
    prices: 包含high, low, close的价格列表
    period: 计算周期(默认9日)
    返回: K, D, J 值
    """
    if len(prices) < period:
        return None, None, None
    
    closes = [p['close'] for p in prices]
    highs = [p['high'] for p in prices]
    lows = [p['low'] for p in prices]
    
    # 计算RSV
    rsv = []
    for i in range(period-1, len(prices)):
        c = closes[i]
        h = max(highs[i-period+1:i+1])
        l = min(lows[i-period+1:i+1])
        rsv.append((c - l) / (h - l) * 100 if h != l else 50)
    
    # 计算K,D,J
    K, D = 50, 50  # 初始值
    K_values = []
    D_values = []
    for r in rsv:
        K = 2/3 * K + 1/3 * r
        D = 2/3 * D + 1/3 * K
        K_values.append(K)
        D_values.append(D)
    
    J = [3*K - 2*D for K,D in zip(K_values, D_values)]
    return K_values[-1], D_values[-1], J[-1]

def calculate_obv(prices):
    """
    计算简化版OBV指标(直接累加成交量)
    prices: 包含volume的价格列表
    返回: OBV累计值
    """
    if len(prices) == 0:
        print("OBV错误: 空数据")
        return 0
    
    # 检查是否有成交量数据
    if not any('vol' in p or 'volume' in p for p in prices):
        print("OBV错误: 数据中未找到成交量字段")
        return 0
    
    try:
        # 简单累加所有成交量
        total_volume = sum(p.get('vol', p.get('volume', 0)) for p in prices)
        print(f"OBV计算完成: 累计成交量={total_volume}")
        return total_volume
    except Exception as e:
        print(f"OBV计算异常: {str(e)}")
        return 0

def calculate_psar(prices, af_step=0.02, af_max=0.2):
    high = prices['high']
    low = prices['low']
    close = prices['close']
    
    psar = close[0]
    trend = 1  # 1 for uptrend, -1 for downtrend
    ep = high[0] if trend == 1 else low[0]
    af = af_step
    
    for i in range(1, len(close)):
        if trend == 1:
            psar = psar + af * (ep - psar)
            if low[i] < psar:
                trend = -1
                psar = ep
                ep = low[i]
                af = af_step
            else:
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            psar = psar + af * (ep - psar)
            if high[i] > psar:
                trend = 1
                psar = ep
                ep = high[i]
                af = af_step
            else:
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)
    
    return psar

def start_consumer(socketio):
    # 预加载历史数据
    price_history = []
    try:
        import tushare as ts
        pro = ts.pro_api('538f15d889d98a8c358d0dbbf10ebaf3b9742864049409dee3a9ea4a')
        # 预加载更多历史数据以满足MACD计算需求(至少35个数据点)
        df = pro.daily(**{
            "ts_code": "000001.SZ",
            "start_date": "20250101",  # 更早的起始日期
            "end_date": "20250519"
        }, fields=["trade_date", "close", "high", "low", "vol"])
        
        # 填充price_history(包含完整K线数据)
        for _, row in df.iterrows():
            price_history.append({
                'trade_date': row['trade_date'],
                'close': row['close'],
                'high': row['high'],
                'low': row['low'],
                'volume': row['vol']
            })
        
        print(f"预加载{len(price_history)}条历史数据")
    except Exception as e:
        print(f"预加载历史数据失败: {str(e)}")
    for message in consumer:
        data = message.value
        if 'close' not in data or 'high' not in data or 'low' not in data:
            print("Warning: Missing required fields in data")
            continue
            
        # 统一数据结构，保存完整的K线数据(包含成交量)
        price_history.append({
            'close': data['close'],
            'high': data['high'],
            'low': data['low'],
            'volume': data.get('vol', data.get('volume', 0)),  # 兼容vol/volume字段
            'trade_date': data.get('trade_date', '')
        })
        print(f"Current price history length: {len(price_history)}")
        print(f"Latest price data: {price_history[-1]}")
        
        if len(price_history) > 14:  # 需要有足够的数据计算指标
            try:
                # 计算KDJ指标
                kdj_data = price_history[-9:]  # 使用9日数据计算KDJ
                print(f"KDJ calculation using {len(kdj_data)} data points")
                
                # 计算KDJ指标
                k, d, j = calculate_kdj(kdj_data)
                data.update({
                    'k': k,
                    'd': d,
                    'j': j
                })
                print(f"Calculated KDJ: K={k}, D={d}, J={j}")
            except Exception as e:
                print(f"Error calculating KDJ: {str(e)}")
                data.update({
                    'k': None,
                    'd': None,
                    'j': None
                })
            
            try:
                # 计算OBV指标
                print(f"Calculating OBV using {len(price_history)} data points")
                print(f"Sample price history data: {price_history[-1]}")
                data['obv'] = calculate_obv(price_history)
                print(f"Calculated OBV: {data['obv']}")
            except Exception as e:
                print(f"Error calculating OBV: {str(e)}")
                data['obv'] = None
            
            try:
                # 计算PSAR指标
                psar_data = {
                    'high': [d.get('high') for d in price_history[-10:]],
                    'low': [d.get('low') for d in price_history[-10:]],
                    'close': [d.get('close') for d in price_history[-10:]]
                }
                print(f"PSAR input data: {psar_data}")
                data['psar'] = calculate_psar(psar_data)
                print(f"Calculated PSAR: {data['psar']}")
            except Exception as e:
                print(f"Error calculating PSAR: {str(e)}")
                data['psar'] = None
        else:
            data['rsi'] = None
            print("Not enough data points for RSI calculation")
        
        # 通过Socket.IO发送到前端
        socketio.emit('stock_update', data)
