CREATE USER zhixi_reader WITH PASSWORD 'reader-local-only' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

REVOKE CREATE, TEMPORARY ON DATABASE factory_demo FROM zhixi_reader;
GRANT CONNECT ON DATABASE factory_demo TO zhixi_reader;

CREATE TABLE production_orders (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_no text NOT NULL UNIQUE,
    product_code text NOT NULL,
    planned_quantity integer NOT NULL CHECK (planned_quantity > 0),
    completed_quantity integer NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE quality_inspections (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id bigint NOT NULL REFERENCES production_orders(id),
    inspected_quantity integer NOT NULL,
    defect_quantity integer NOT NULL DEFAULT 0,
    result text NOT NULL CHECK (result IN ('passed', 'failed')),
    inspected_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_quality_inspections_order_id ON quality_inspections(order_id);
CREATE INDEX ix_quality_inspections_inspected_at ON quality_inspections(inspected_at);

INSERT INTO production_orders (order_no, product_code, planned_quantity, completed_quantity)
VALUES ('MO-2026-001', 'MOTOR-A', 1000, 960), ('MO-2026-002', 'MOTOR-B', 800, 620);

INSERT INTO quality_inspections (order_id, inspected_quantity, defect_quantity, result)
VALUES (1, 200, 3, 'passed'), (1, 200, 8, 'failed'), (2, 100, 1, 'passed');

GRANT USAGE ON SCHEMA public TO zhixi_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO zhixi_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO zhixi_reader;
