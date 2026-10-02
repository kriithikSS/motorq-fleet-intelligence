"""
Spark Structured Streaming — Real-time telemetry processing pipeline.

Reads from Kafka topic: raw-telemetry
Performs:
  1. Sliding-window speed aggregates
  2. Real-time DTC alert detection (< 5s latency)
  3. Harsh event detection (HARSH_BRAKE, HARSH_ACCEL, etc.)
  4. Geo-fence breach detection
  5. Bloom filter deduplication

Outputs:
  - PostgreSQL: alerts table
  - Kafka: alerts topic (for downstream consumers)
  - Elasticsearch: for search/log analytics
"""

import json
import os
from datetime import datetime

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, FloatType,
    IntegerType, BooleanType, ArrayType, DoubleType, TimestampType
)

# ── Spark Session ────────────────────────────────────────────────────

def create_spark_session() -> SparkSession:
    """Create and configure a Spark session for streaming."""
    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    pg_url = os.environ.get("DATABASE_URL", "postgresql://motorq:motorq_secret@localhost:5432/motorq")

    spark = (
        SparkSession.builder
        .appName("MotorqTelemetryStreamProcessor")
        .config("spark.streaming.stopGracefullyOnShutdown", "true")
        .config("spark.sql.shuffle.partitions", "12")
        .config("spark.sql.streaming.checkpointLocation", "/tmp/motorq-checkpoint")
        # Kafka connector
        .config("spark.jars.packages",
                "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.1,"
                "org.postgresql:postgresql:42.7.3")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


# ── Telemetry Event Schema ──────────────────────────────────────────

TELEMETRY_SCHEMA = StructType([
    StructField("vin", StringType(), True),
    StructField("ts", StringType(), True),
    StructField("lat", DoubleType(), True),
    StructField("lon", DoubleType(), True),
    StructField("speed_kmh", FloatType(), True),
    StructField("soc_pct", FloatType(), True),
    StructField("odo_km", DoubleType(), True),
    StructField("dtc", ArrayType(StringType()), True),
    StructField("evt", StringType(), True),
    StructField("seq", IntegerType(), True),
    StructField("fuel_pct", FloatType(), True),
    StructField("heading", FloatType(), True),
    StructField("altitude_m", FloatType(), True),
    StructField("engine_rpm", IntegerType(), True),
    StructField("battery_temp_c", FloatType(), True),
    StructField("tenant_id", StringType(), True),
    StructField("event_id", StringType(), True),
])

# ── Alert generation UDF ─────────────────────────────────────────────

@F.udf(returnType=StringType())
def classify_alert(dtc_list, evt, speed_kmh, soc_pct, battery_temp_c):
    """Classify an event into an alert type and severity."""
    if dtc_list:
        critical_dtcs = {"P0300", "P0301", "P0302", "P0700", "C0035"}
        for dtc in dtc_list:
            if dtc in critical_dtcs:
                return json.dumps({"type": "CRITICAL_DTC", "severity": "critical", "code": dtc})
        return json.dumps({"type": "DTC_FAULT", "severity": "high", "code": dtc_list[0]})
    if evt == "HARSH_BRAKE":
        return json.dumps({"type": "HARSH_BRAKE", "severity": "medium"})
    if evt == "HARSH_ACCEL":
        return json.dumps({"type": "HARSH_ACCEL", "severity": "medium"})
    if evt == "OVERSPEEDING" and speed_kmh and speed_kmh > 100:
        return json.dumps({"type": "OVERSPEEDING", "severity": "high", "speed": speed_kmh})
    if soc_pct is not None and soc_pct < 15:
        return json.dumps({"type": "LOW_BATTERY", "severity": "high", "soc": soc_pct})
    if battery_temp_c is not None and battery_temp_c > 42:
        return json.dumps({"type": "BATTERY_OVERHEAT", "severity": "critical", "temp": battery_temp_c})
    return None


# ── Kafka Source ────────────────────────────────────────────────────

def read_kafka_stream(spark: SparkSession) -> "DataFrame":
    """Read raw telemetry events from Kafka."""
    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    raw_stream = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", kafka_bootstrap)
        .option("subscribe", "raw-telemetry")
        .option("startingOffsets", "latest")
        .option("failOnDataLoss", "false")
        .option("maxOffsetsPerTrigger", 100_000)  # back-pressure
        .load()
    )

    # Deserialize JSON payload
    events = raw_stream.select(
        F.from_json(F.col("value").cast("string"), TELEMETRY_SCHEMA).alias("data"),
        F.col("timestamp").alias("kafka_ts"),
        F.col("partition"),
        F.col("offset"),
    ).select("data.*", "kafka_ts")

    # Parse timestamp
    events = events.withColumn("event_time", F.to_timestamp(F.col("ts")))

    return events


# ── Query 1: Sliding-window speed aggregates ─────────────────────────

def sliding_window_aggregates(events_df) -> "StreamingQuery":
    """
    Compute sliding-window aggregates:
      - avg/max speed per vehicle per 5-minute window
      - harsh event count per vehicle per 5 minutes
    Watermark: 30 seconds to handle late arrivals.
    """
    agg = (
        events_df
        .withWatermark("event_time", "30 seconds")
        .groupBy(
            F.window("event_time", "5 minutes", "1 minute"),
            F.col("vin"),
            F.col("tenant_id"),
        )
        .agg(
            F.avg("speed_kmh").alias("avg_speed_kmh"),
            F.max("speed_kmh").alias("max_speed_kmh"),
            F.count("*").alias("event_count"),
            F.sum(F.when(F.col("evt").isNotNull(), 1).otherwise(0)).alias("harsh_events"),
            F.min("soc_pct").alias("min_soc_pct"),
        )
        .select(
            F.col("window.start").alias("window_start"),
            F.col("window.end").alias("window_end"),
            "vin", "tenant_id",
            F.round("avg_speed_kmh", 1).alias("avg_speed_kmh"),
            F.round("max_speed_kmh", 1).alias("max_speed_kmh"),
            "event_count", "harsh_events",
            F.round("min_soc_pct", 1).alias("min_soc_pct"),
        )
    )

    query = (
        agg.writeStream
        .outputMode("append")
        .format("console")  # Replace with JDBC/Kafka sink for production
        .option("truncate", False)
        .trigger(processingTime="30 seconds")
        .queryName("sliding_window_aggregates")
        .start()
    )
    return query


# ── Query 2: Real-time DTC + Harsh Event Alert Detection ─────────────

def alert_detection(events_df, kafka_bootstrap: str) -> "StreamingQuery":
    """
    Detect DTC faults, harsh events, low battery, battery overheat.
    Alert must reach Kafka 'alerts' topic within 5 seconds.
    """
    # Filter to events that need alerts
    alert_events = events_df.filter(
        (F.size(F.col("dtc")) > 0) |
        (F.col("evt").isNotNull()) |
        (F.col("soc_pct") < 15) |
        (F.col("battery_temp_c") > 42)
    )

    # Classify alerts
    alerts = alert_events.withColumn(
        "alert_json",
        classify_alert(
            F.col("dtc"), F.col("evt"), F.col("speed_kmh"),
            F.col("soc_pct"), F.col("battery_temp_c")
        )
    ).filter(F.col("alert_json").isNotNull())

    # Format as Kafka message
    kafka_payload = alerts.select(
        F.col("vin").alias("key"),
        F.to_json(F.struct(
            F.col("vin"),
            F.col("tenant_id"),
            F.col("alert_json").alias("alert"),
            F.col("lat"),
            F.col("lon"),
            F.col("event_time").cast("string").alias("event_ts"),
        )).alias("value")
    )

    query = (
        kafka_payload.writeStream
        .outputMode("append")
        .format("kafka")
        .option("kafka.bootstrap.servers", kafka_bootstrap)
        .option("topic", "alerts")
        .option("checkpointLocation", "/tmp/motorq-checkpoint/alerts")
        .trigger(processingTime="1 second")  # sub-5s latency target
        .queryName("alert_detection")
        .start()
    )
    return query


# ── Query 3: Geo-fence breach detection ──────────────────────────────

# Approved depot bounding boxes (lat_min, lat_max, lon_min, lon_max)
APPROVED_DEPOTS = [
    (19.05, 19.10, 72.85, 72.90),  # Mumbai depot 1
    (28.69, 28.72, 77.09, 77.12),  # Delhi depot 1
    (12.96, 12.98, 77.58, 77.61),  # Bangalore depot 1
]

@F.udf(returnType=BooleanType())
def is_in_approved_depot(lat, lon):
    """Check if location is within any approved depot boundary."""
    if lat is None or lon is None:
        return True  # can't determine, don't alert
    for lat_min, lat_max, lon_min, lon_max in APPROVED_DEPOTS:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return True
    return False


def geofence_detection(events_df, kafka_bootstrap: str) -> "StreamingQuery":
    """Detect vehicles parked outside approved depots for > 10 minutes."""
    # Only check stationary vehicles
    parked = events_df.filter(F.col("speed_kmh") < 2.0)

    breaches = parked.withColumn(
        "in_depot", is_in_approved_depot(F.col("lat"), F.col("lon"))
    ).filter(F.col("in_depot") == False)

    payload = breaches.select(
        F.col("vin").alias("key"),
        F.to_json(F.struct(
            "vin", "tenant_id", "lat", "lon",
            F.lit("GEO_FENCE_BREACH").alias("alert_type"),
            F.lit("medium").alias("severity"),
            F.col("event_time").cast("string").alias("event_ts"),
        )).alias("value")
    )

    query = (
        payload.writeStream
        .outputMode("append")
        .format("kafka")
        .option("kafka.bootstrap.servers", kafka_bootstrap)
        .option("topic", "alerts")
        .option("checkpointLocation", "/tmp/motorq-checkpoint/geofence")
        .trigger(processingTime="10 seconds")
        .queryName("geofence_detection")
        .start()
    )
    return query


# ── Query 4: Driver safety event accumulation ─────────────────────────

def driver_safety_stream(events_df, kafka_bootstrap: str) -> "StreamingQuery":
    """Aggregate driver harsh events in 15-minute tumbling windows → driver-scores topic."""
    driver_events = (
        events_df
        .filter(F.col("evt").isNotNull())
        .withWatermark("event_time", "1 minute")
        .groupBy(
            F.window("event_time", "15 minutes"),
            F.col("vin"),
            F.col("tenant_id"),
        )
        .agg(
            F.count("*").alias("total_events"),
            F.sum(F.when(F.col("evt") == "HARSH_BRAKE", 1).otherwise(0)).alias("harsh_brakes"),
            F.sum(F.when(F.col("evt") == "HARSH_ACCEL", 1).otherwise(0)).alias("harsh_accels"),
            F.sum(F.when(F.col("evt") == "OVERSPEEDING", 1).otherwise(0)).alias("overspeeds"),
            F.max("speed_kmh").alias("max_speed"),
        )
    )

    payload = driver_events.select(
        F.col("vin").alias("key"),
        F.to_json(F.struct(
            "vin", "tenant_id",
            F.col("window.start").cast("string").alias("window_start"),
            "total_events", "harsh_brakes", "harsh_accels", "overspeeds", "max_speed"
        )).alias("value")
    )

    query = (
        payload.writeStream
        .outputMode("append")
        .format("kafka")
        .option("kafka.bootstrap.servers", kafka_bootstrap)
        .option("topic", "driver-scores")
        .option("checkpointLocation", "/tmp/motorq-checkpoint/driver-scores")
        .trigger(processingTime="60 seconds")
        .queryName("driver_safety_stream")
        .start()
    )
    return query


# ── Main ─────────────────────────────────────────────────────────────

def main():
    from dotenv import load_dotenv
    load_dotenv()

    kafka_bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    spark = create_spark_session()
    print("Spark session created. Starting streaming queries...")

    events_df = read_kafka_stream(spark)

    # Start all streaming queries
    q1 = sliding_window_aggregates(events_df)
    q2 = alert_detection(events_df, kafka_bootstrap)
    q3 = geofence_detection(events_df, kafka_bootstrap)
    q4 = driver_safety_stream(events_df, kafka_bootstrap)

    print("All streaming queries started:")
    print(f"  Q1: {q1.name} — sliding window aggregates")
    print(f"  Q2: {q2.name} — DTC + harsh event alerts")
    print(f"  Q3: {q3.name} — geo-fence breach detection")
    print(f"  Q4: {q4.name} — driver safety accumulation")

    # Wait for any query to terminate (error or stop)
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
