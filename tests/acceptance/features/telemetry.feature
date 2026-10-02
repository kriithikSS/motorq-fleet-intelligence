Feature: Telemetry Ingestion and Processing

  Scenario: Valid telemetry is ingested and triggers an alert if DTC is critical
    Given the IoT Ingestion Service is running
    And the Stream Processor is active
    When a vehicle with VIN "1HGCM82633A004352" emits a telemetry event with DTC "P0300"
    Then the API Gateway should return a 202 Accepted status
    And within 5 seconds, an alert should be generated for VIN "1HGCM82633A004352"
    And the alert severity should be "CRITICAL"
    
  Scenario: Invalid telemetry is rejected by the schema validator
    Given the IoT Ingestion Service is running
    When a vehicle with an invalid VIN "1HGOM82633A004352" emits a telemetry event
    Then the API Gateway should return a 422 Unprocessable Entity status
    And the event should not be published to the raw-telemetry topic
