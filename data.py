# coding: utf-8
from kafka import KafkaProducer
import tushare as ts
import json
import time
import sys

# 初始化tushare和Kafka
try:
    pro = ts.pro_api('538f15d889d98a8c358d0dbbf10ebaf3b9742864049409dee3a9ea4a')
    producer = KafkaProducer(bootstrap_servers='localhost:9092',
                           value_serializer=lambda v: json.dumps(v).encode('utf-8'))
    print("成功初始化Kafka生产者", file=sys.stderr)
except Exception as e:
    print(f"初始化失败: {str(e)}", file=sys.stderr)
    sys.exit(1)

# 获取股票数据并发送到Kafka
def fetch_and_send_stock_data():
    try:
        print("正在获取股票数据...", file=sys.stderr)
        df = pro.daily(**{
            "ts_code": "000001.SZ",
            "trade_date": "",
            "start_date": "20250501",
            "end_date": "20250519",
            "offset": "",
            "limit": ""
        }, fields=[
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "pre_close",
            "change",
            "pct_chg",
            "vol",
            "amount"
        ])
        print(f"成功获取{len(df)}条数据", file=sys.stderr)
        
        # 发送每条记录到Kafka
        for _, row in df.iterrows():
            data = row.to_dict()
            print(f"发送数据: {data}", file=sys.stderr)
            producer.send('stock_data', data)
            time.sleep(0.1)  # 控制发送速率
        
        print("数据发送完成", file=sys.stderr)
    except Exception as e:
        print(f"获取或发送数据失败: {str(e)}", file=sys.stderr)

if __name__ == '__main__':
    fetch_and_send_stock_data()
