import pytest
import os
import json
from confluent_kafka import Producer, Consumer
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

# We use Testcontainers to spin up real infrastructure for integration testing

@pytest.fixture(scope="session")
def kafka_container():
    with KafkaContainer("confluentinc/cp-kafka:7.6.0") as kafka:
        yield kafka

@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:15-alpine") as postgres:
        yield postgres

@pytest.fixture(scope="session")
def redis_container():
    with RedisContainer("redis:7-alpine") as redis:
        yield redis

def test_telemetry_ingestion_to_kafka(kafka_container, redis_container):
    """
    Integration test: Ensure that sending a valid telemetry event results 
    in it being published to Kafka.
    """
    bootstrap_servers = kafka_container.get_bootstrap_server()
    
    # 1. Setup Consumer to verify
    consumer = Consumer({
        'bootstrap.servers': bootstrap_servers,
        'group.id': 'integration-test-group',
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe(['raw-telemetry'])
    
    # 2. Setup Producer (Mocking the Ingestion Service)
    producer = Producer({
        'bootstrap.servers': bootstrap_servers
    })
    
    test_event = {
        "vin": "1HGCM82633A004352",
        "ts": "2026-10-01T10:00:00Z",
        "speed_kmh": 60.5
    }
    
    producer.produce(
        'raw-telemetry', 
        key=test_event["vin"].encode(), 
        value=json.dumps(test_event).encode()
    )
    producer.flush()
    
    # 3. Consume and assert
    msg = consumer.poll(10.0)
    assert msg is not None
    assert not msg.error()
    
    received_event = json.loads(msg.value().decode())
    assert received_event["vin"] == "1HGCM82633A004352"
    assert received_event["speed_kmh"] == 60.5
    
    consumer.close()
