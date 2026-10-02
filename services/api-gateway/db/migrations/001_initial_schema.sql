-- ============================================================
--  Motorq Platform — PostgreSQL Schema (Third Normal Form)
--  Uses TimescaleDB for time-series telemetry hypertable
-- ============================================================

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for full-text search

-- ============================================================
--  TENANTS (top-level entity — multi-tenant isolation)
-- ============================================================
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id       VARCHAR(50)   PRIMARY KEY,
    name            VARCHAR(200)  NOT NULL,
    plan            VARCHAR(30)   NOT NULL DEFAULT 'standard',
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE
);

-- ============================================================
--  VEHICLES
-- ============================================================
CREATE TABLE IF NOT EXISTS vehicles (
    vin             VARCHAR(17)   PRIMARY KEY,
    tenant_id       VARCHAR(50)   NOT NULL REFERENCES tenants(tenant_id),
    make            VARCHAR(50)   NOT NULL,
    model           VARCHAR(100)  NOT NULL,
    vehicle_type    VARCHAR(50),
    fuel_type       VARCHAR(20)   NOT NULL CHECK (fuel_type IN ('ICE', 'EV', 'Hybrid')),
    battery_kwh     NUMERIC(6,2),
    year            SMALLINT      NOT NULL,
    color           VARCHAR(30),
    fleet_type      VARCHAR(30),
    region          VARCHAR(50),
    home_lat        NUMERIC(9,6),
    home_lon        NUMERIC(9,6),
    registered_at   TIMESTAMPTZ,
    odometer_km     NUMERIC(10,1) NOT NULL DEFAULT 0,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_vehicles_tenant ON vehicles(tenant_id);
CREATE INDEX idx_vehicles_fuel_type ON vehicles(fuel_type);
CREATE INDEX idx_vehicles_region ON vehicles(region);
CREATE INDEX idx_vehicles_fleet_type ON vehicles(fleet_type);

-- ============================================================
--  DRIVERS
-- ============================================================
CREATE TABLE IF NOT EXISTS drivers (
    driver_id       VARCHAR(50)   PRIMARY KEY,
    tenant_id       VARCHAR(50)   NOT NULL REFERENCES tenants(tenant_id),
    full_name       VARCHAR(200)  NOT NULL,
    email           VARCHAR(200),
    phone           VARCHAR(30),
    license_no      VARCHAR(50),
    joined_at       TIMESTAMPTZ,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_drivers_tenant ON drivers(tenant_id);

-- ============================================================
--  VEHICLE-DRIVER ASSIGNMENT (many-to-one at any point in time)
-- ============================================================
CREATE TABLE IF NOT EXISTS vehicle_driver_assignments (
    id              BIGSERIAL     PRIMARY KEY,
    vin             VARCHAR(17)   NOT NULL REFERENCES vehicles(vin),
    driver_id       VARCHAR(50)   NOT NULL REFERENCES drivers(driver_id),
    assigned_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    unassigned_at   TIMESTAMPTZ,
    is_current      BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_vda_vin ON vehicle_driver_assignments(vin);
CREATE INDEX idx_vda_driver ON vehicle_driver_assignments(driver_id);

-- ============================================================
--  TRIPS
-- ============================================================
CREATE TABLE IF NOT EXISTS trips (
    trip_id         UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    vin             VARCHAR(17)   NOT NULL REFERENCES vehicles(vin),
    driver_id       VARCHAR(50)   REFERENCES drivers(driver_id),
    tenant_id       VARCHAR(50)   NOT NULL REFERENCES tenants(tenant_id),
    started_at      TIMESTAMPTZ   NOT NULL,
    ended_at        TIMESTAMPTZ,
    start_lat       NUMERIC(9,6),
    start_lon       NUMERIC(9,6),
    end_lat         NUMERIC(9,6),
    end_lon         NUMERIC(9,6),
    distance_km     NUMERIC(8,2),
    duration_sec    INTEGER,
    avg_speed_kmh   NUMERIC(6,1),
    max_speed_kmh   NUMERIC(6,1),
    harsh_events    INTEGER       NOT NULL DEFAULT 0,
    fuel_consumed_l NUMERIC(6,2),
    energy_used_kwh NUMERIC(6,3),
    carbon_kg       NUMERIC(8,4),
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trips_vin ON trips(vin);
CREATE INDEX idx_trips_driver ON trips(driver_id);
CREATE INDEX idx_trips_started_at ON trips(started_at DESC);
CREATE INDEX idx_trips_tenant ON trips(tenant_id);

-- ============================================================
--  ALERTS
-- ============================================================
CREATE TYPE alert_severity AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE alert_status AS ENUM ('open', 'acknowledged', 'resolved', 'ignored');

CREATE TABLE IF NOT EXISTS alerts (
    alert_id        UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    vin             VARCHAR(17)   NOT NULL REFERENCES vehicles(vin),
    tenant_id       VARCHAR(50)   NOT NULL REFERENCES tenants(tenant_id),
    driver_id       VARCHAR(50)   REFERENCES drivers(driver_id),
    alert_type      VARCHAR(50)   NOT NULL,
    severity        alert_severity NOT NULL DEFAULT 'medium',
    status          alert_status  NOT NULL DEFAULT 'open',
    title           VARCHAR(200)  NOT NULL,
    description     TEXT,
    dtc_code        VARCHAR(10),
    event_ts        TIMESTAMPTZ   NOT NULL,
    lat             NUMERIC(9,6),
    lon             NUMERIC(9,6),
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(100),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alerts_vin ON alerts(vin);
CREATE INDEX idx_alerts_tenant ON alerts(tenant_id);
CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_event_ts ON alerts(event_ts DESC);
CREATE INDEX idx_alerts_type ON alerts(alert_type);
-- Partial index for open alerts (most common query)
CREATE INDEX idx_alerts_open ON alerts(tenant_id, event_ts DESC) WHERE status = 'open';

-- ============================================================
--  MAINTENANCE PREDICTIONS (ML output)
-- ============================================================
CREATE TABLE IF NOT EXISTS maintenance_predictions (
    prediction_id   UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    vin             VARCHAR(17)   NOT NULL REFERENCES vehicles(vin),
    tenant_id       VARCHAR(50)   NOT NULL REFERENCES tenants(tenant_id),
    model_version   VARCHAR(20)   NOT NULL,
    predicted_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    failure_prob_7d NUMERIC(5,4)  NOT NULL,  -- 0.0 to 1.0
    failure_type    VARCHAR(100),
    recommended_action TEXT,
    estimated_cost_usd NUMERIC(8,2),
    confidence      VARCHAR(10)   CHECK (confidence IN ('high', 'medium', 'low')),
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_maint_vin ON maintenance_predictions(vin);
CREATE INDEX idx_maint_tenant ON maintenance_predictions(tenant_id);
CREATE INDEX idx_maint_prob ON maintenance_predictions(failure_prob_7d DESC) WHERE is_active = TRUE;
CREATE INDEX idx_maint_predicted_at ON maintenance_predictions(predicted_at DESC);

-- ============================================================
--  DRIVER SAFETY SCORES
-- ============================================================
CREATE TABLE IF NOT EXISTS driver_safety_scores (
    score_id        BIGSERIAL     PRIMARY KEY,
    driver_id       VARCHAR(50)   NOT NULL REFERENCES drivers(driver_id),
    tenant_id       VARCHAR(50)   NOT NULL REFERENCES tenants(tenant_id),
    period          VARCHAR(10)   NOT NULL CHECK (period IN ('daily', 'weekly', 'monthly')),
    period_start    DATE          NOT NULL,
    overall_score   NUMERIC(5,2)  NOT NULL,  -- 0 to 100
    harsh_brake_cnt INTEGER       NOT NULL DEFAULT 0,
    harsh_accel_cnt INTEGER       NOT NULL DEFAULT 0,
    speeding_cnt    INTEGER       NOT NULL DEFAULT 0,
    night_driving_h NUMERIC(5,2)  NOT NULL DEFAULT 0,
    idle_time_min   NUMERIC(8,2)  NOT NULL DEFAULT 0,
    total_km        NUMERIC(8,2)  NOT NULL DEFAULT 0,
    computed_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (driver_id, period, period_start)
);

CREATE INDEX idx_dss_driver ON driver_safety_scores(driver_id);
CREATE INDEX idx_dss_tenant ON driver_safety_scores(tenant_id);
CREATE INDEX idx_dss_score ON driver_safety_scores(overall_score DESC);

-- ============================================================
--  SUBSCRIPTIONS / BILLING (needs strong ACID — CP store)
-- ============================================================
CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(50)   NOT NULL REFERENCES tenants(tenant_id),
    plan            VARCHAR(50)   NOT NULL,
    vehicle_quota   INTEGER       NOT NULL,
    started_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE
);

-- ============================================================
--  AUDIT LOG (every data access + AI agent action)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    log_id          BIGSERIAL     PRIMARY KEY,
    tenant_id       VARCHAR(50)   NOT NULL,
    actor_id        VARCHAR(100)  NOT NULL,
    actor_type      VARCHAR(30)   NOT NULL CHECK (actor_type IN ('user', 'api_key', 'agent', 'system')),
    action          VARCHAR(100)  NOT NULL,
    resource_type   VARCHAR(50),
    resource_id     VARCHAR(100),
    ip_address      INET,
    user_agent      TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant ON audit_log(tenant_id, created_at DESC);
CREATE INDEX idx_audit_actor ON audit_log(actor_id);
CREATE INDEX idx_audit_action ON audit_log(action);

-- ============================================================
--  TELEMETRY (TimescaleDB Hypertable — partitioned by time + VIN)
--  This is the hot storage (last 7 days); older data moves to cold.
-- ============================================================
CREATE TABLE IF NOT EXISTS telemetry (
    time            TIMESTAMPTZ   NOT NULL,
    vin             VARCHAR(17)   NOT NULL,
    tenant_id       VARCHAR(50)   NOT NULL,
    lat             NUMERIC(9,6),
    lon             NUMERIC(9,6),
    speed_kmh       NUMERIC(5,1),
    soc_pct         NUMERIC(5,1),
    fuel_pct        NUMERIC(5,1),
    odo_km          NUMERIC(10,1),
    heading         NUMERIC(5,1),
    altitude_m      NUMERIC(6,1),
    engine_rpm      INTEGER,
    battery_temp_c  NUMERIC(5,1),
    dtc             TEXT[],
    evt             VARCHAR(50),
    seq             BIGINT,
    event_id        UUID
);

-- Convert to TimescaleDB hypertable (partitioned by time, 1-hour chunks)
SELECT create_hypertable('telemetry', 'time',
    chunk_time_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);

-- Add space partitioning by VIN hash (reduces hot spots)
SELECT add_dimension('telemetry', 'vin', number_partitions => 8, if_not_exists => TRUE);

-- Indexes on hypertable
CREATE INDEX IF NOT EXISTS idx_telemetry_vin_time ON telemetry(vin, time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_tenant_time ON telemetry(tenant_id, time DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_evt ON telemetry(evt, time DESC) WHERE evt IS NOT NULL;

-- Retention policy: keep 7 days of hot telemetry (older goes to cold/Parquet)
SELECT add_retention_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE);

-- Continuous aggregate: hourly vehicle stats (speeds up dashboard queries)
CREATE MATERIALIZED VIEW IF NOT EXISTS telemetry_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS hour,
    vin,
    tenant_id,
    AVG(speed_kmh)              AS avg_speed_kmh,
    MAX(speed_kmh)              AS max_speed_kmh,
    MIN(soc_pct)                AS min_soc_pct,
    MAX(soc_pct)                AS max_soc_pct,
    COUNT(*)                    AS event_count,
    COUNT(*) FILTER (WHERE evt IS NOT NULL) AS harsh_event_count
FROM telemetry
GROUP BY hour, vin, tenant_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('telemetry_hourly',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '10 minutes',
    schedule_interval => INTERVAL '30 minutes',
    if_not_exists => TRUE
);

-- ============================================================
--  Comments (data dictionary)
-- ============================================================
COMMENT ON TABLE telemetry IS 'Hot time-series telemetry — TimescaleDB hypertable, 7-day retention. Older data stored in Parquet/S3 (cold storage).';
COMMENT ON TABLE vehicles IS '3NF vehicle master. Relational core — ACID required. OEM and fleet metadata.';
COMMENT ON TABLE alerts IS 'Real-time and batch-detected alerts. Partial index on open alerts for fast dashboard queries.';
COMMENT ON TABLE maintenance_predictions IS 'ML model output: 7-day breakdown probability per vehicle. Refreshed nightly.';
COMMENT ON TABLE driver_safety_scores IS 'Aggregated safety scores per driver per period (daily/weekly/monthly).';
COMMENT ON TABLE audit_log IS 'Immutable audit trail for every data access and AI agent action. Compliance (GDPR/DPDP).';
