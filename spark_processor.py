from pyspark.sql import SparkSession
from pyspark.sql.functions import col, lag, when, avg, lit
from pyspark.sql.window import Window
import json
import sys

# 创建Spark会话
spark = SparkSession.builder \
    .appName("StockIndicatorProcessor") \
    .getOrCreate()

# 从Kafka读取数据
df = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", "localhost:9092") \
    .option("subscribe", "stock_data") \
    .load()

# 定义JSON schema
from pyspark.sql.types import StructType, StructField, StringType, DoubleType

schema = StructType([
    StructField("ts_code", StringType()),
    StructField("trade_date", StringType()),
    StructField("open", DoubleType()),
    StructField("high", DoubleType()),
    StructField("low", DoubleType()),
    StructField("close", DoubleType()),
    StructField("pre_close", DoubleType()),
    StructField("change", DoubleType()),
    StructField("pct_chg", DoubleType()),
    StructField("vol", DoubleType()),
    StructField("amount", DoubleType())
])

# 解析JSON数据
from pyspark.sql.functions import from_json

parsed_df = df.select(
    from_json(col("value").cast("string"), schema).alias("data")
).select("data.*")

# 计算相对强弱指标(RSI)
def calculate_rsi(df, period=14):
    window = Window.orderBy("trade_date")
    delta = df.withColumn("delta", col("close") - lag("close", 1).over(window))
    gain = delta.withColumn("gain", when(col("delta") > 0, col("delta")).otherwise(0))
    loss = delta.withColumn("loss", when(col("delta") < 0, -col("delta")).otherwise(0))
    
    avg_gain = gain.withColumn("avg_gain", avg("gain").over(window.rowsBetween(-period, 0)))
    avg_loss = loss.withColumn("avg_loss", avg("loss").over(window.rowsBetween(-period, 0)))
    
    rs = avg_gain.join(avg_loss, "trade_date").withColumn("rs", col("avg_gain")/col("avg_loss"))
    rsi = rs.withColumn("rsi", 100 - (100 / (1 + col("rs"))))
    return rsi

# 计算抛物线转向指标(PSAR)
def calculate_psar(df, acceleration=0.02, maximum=0.2):
    window = Window.orderBy("trade_date")
    
    # 初始化PSAR值为第一天的收盘价
    first_close = df.select("close").first()[0]
    df = df.withColumn("psar", lit(first_close))
    
    # 计算趋势和PSAR值
    df = df.withColumn("trend", 
        when(col("close") > col("psar"), lit(1)).otherwise(lit(-1))
    )
    
    # 计算极值点
    df = df.withColumn("extreme_point",
        when(col("trend") == 1, col("high"))
        .otherwise(col("low"))
    )
    
    # 计算PSAR值
    df = df.withColumn("psar",
        col("psar") + (col("extreme_point") - col("psar")) * acceleration
    )
    
    return df

# 处理数据流
def process_batch(batch_df, batch_id):
    # 检查批次数据是否为空
    if batch_df.count() == 0:
        print("警告: 收到空批次数据，跳过处理", file=sys.stderr)
        return
    
    try:
        # 计算指标
        rsi_df = calculate_rsi(batch_df)
        psar_df = calculate_psar(batch_df)
        
        # 合并结果
        result_df = batch_df.join(rsi_df, "trade_date") \
            .join(psar_df, "trade_date") \
            .select(
                "ts_code", "trade_date", "close",
                "rsi", "psar"
            )
        
        # 发送到Kafka
        result_df.selectExpr("to_json(struct(*)) AS value") \
            .write \
            .format("kafka") \
            .option("kafka.bootstrap.servers", "localhost:9092") \
            .option("topic", "stock_indicators") \
            .save()
    except Exception as e:
        print(f"处理批次数据时出错: {str(e)}", file=sys.stderr)

# 启动流处理
query = parsed_df.writeStream \
    .foreachBatch(process_batch) \
    .start()

query.awaitTermination()
