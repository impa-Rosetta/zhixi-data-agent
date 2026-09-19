CREATE TABLE production_orders (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'Identity',
    order_no VARCHAR(64) NOT NULL,
    product_code VARCHAR(64) NOT NULL,
    planned_quantity INT NOT NULL,
    completed_quantity INT NOT NULL DEFAULT 0,
    started_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT pk_production_orders PRIMARY KEY (id),
    CONSTRAINT uq_production_orders_order_no UNIQUE (order_no),
    CONSTRAINT ck_production_orders_planned_quantity CHECK (planned_quantity > 0)
) COMMENT = 'Production orders';

CREATE TABLE quality_inspections (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id BIGINT UNSIGNED NOT NULL,
    inspected_quantity INT NOT NULL,
    defect_quantity INT NOT NULL DEFAULT 0,
    result VARCHAR(16) NOT NULL,
    inspected_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT pk_quality_inspections PRIMARY KEY (id),
    CONSTRAINT fk_quality_inspections_order
        FOREIGN KEY (order_id) REFERENCES production_orders (id),
    CONSTRAINT ck_quality_inspections_result CHECK (result IN ('passed', 'failed')),
    INDEX ix_quality_inspections_inspected_at (inspected_at)
) COMMENT = 'Quality inspection results';

CREATE VIEW order_quality_summary AS
SELECT
    po.id AS order_id,
    po.order_no,
    COUNT(qi.id) AS inspection_count,
    COALESCE(SUM(qi.defect_quantity), 0) AS defect_quantity
FROM production_orders po
LEFT JOIN quality_inspections qi ON qi.order_id = po.id
GROUP BY po.id, po.order_no;

INSERT INTO production_orders
    (order_no, product_code, planned_quantity, completed_quantity, started_at)
VALUES
    ('MO-2025-010', 'MOTOR-A', 1000, 955, '2025-10-02 08:00:00'),
    ('MO-2025-011', 'MOTOR-B', 1000, 948, '2025-11-02 08:00:00'),
    ('MO-2025-012', 'MOTOR-A', 1000, 962, '2025-12-02 08:00:00'),
    ('MO-2026-001', 'MOTOR-B', 1000, 951, '2026-01-02 08:00:00'),
    ('MO-2026-002', 'MOTOR-A', 1000, 966, '2026-02-02 08:00:00'),
    ('MO-2026-003', 'MOTOR-B', 1000, 944, '2026-03-02 08:00:00'),
    ('MO-2026-004', 'MOTOR-A', 1000, 958, '2026-04-02 08:00:00'),
    ('MO-2026-005', 'MOTOR-B', 1000, 969, '2026-05-02 08:00:00'),
    ('MO-2026-006', 'MOTOR-A', 1000, 953, '2026-06-02 08:00:00'),
    ('MO-2026-007', 'MOTOR-B', 1000, 972, '2026-07-02 08:00:00'),
    ('MO-2026-008', 'MOTOR-A', 1000, 961, '2026-08-02 08:00:00'),
    ('MO-2026-009', 'MOTOR-B', 1000, 947, '2026-09-02 08:00:00');

INSERT INTO quality_inspections
    (order_id, inspected_quantity, defect_quantity, result, inspected_at)
VALUES
    (1, 200, 5, 'failed', '2025-10-05 09:00:00'),
    (1, 200, 4, 'failed', '2025-10-20 09:00:00'),
    (2, 200, 3, 'passed', '2025-11-05 09:00:00'),
    (2, 200, 5, 'failed', '2025-11-20 09:00:00'),
    (3, 200, 2, 'passed', '2025-12-05 09:00:00'),
    (3, 200, 3, 'passed', '2025-12-20 09:00:00'),
    (4, 200, 4, 'failed', '2026-01-05 09:00:00'),
    (4, 200, 5, 'failed', '2026-01-20 09:00:00'),
    (5, 200, 2, 'passed', '2026-02-05 09:00:00'),
    (5, 200, 4, 'failed', '2026-02-20 09:00:00'),
    (6, 200, 6, 'failed', '2026-03-05 09:00:00'),
    (6, 200, 7, 'failed', '2026-03-20 09:00:00'),
    (7, 200, 3, 'passed', '2026-04-05 09:00:00'),
    (7, 200, 4, 'failed', '2026-04-20 09:00:00'),
    (8, 200, 2, 'passed', '2026-05-05 09:00:00'),
    (8, 200, 3, 'passed', '2026-05-20 09:00:00'),
    (9, 200, 4, 'failed', '2026-06-05 09:00:00'),
    (9, 200, 5, 'failed', '2026-06-20 09:00:00'),
    (10, 200, 3, 'passed', '2026-07-05 09:00:00'),
    (10, 200, 4, 'failed', '2026-07-20 09:00:00'),
    (11, 200, 5, 'failed', '2026-08-05 09:00:00'),
    (11, 200, 6, 'failed', '2026-08-20 09:00:00'),
    (12, 200, 8, 'failed', '2026-09-05 09:00:00'),
    (12, 200, 4, 'failed', '2026-09-20 09:00:00');

CREATE USER 'zhixi_reader'@'%' IDENTIFIED BY 'reader-local-only';
GRANT SELECT, SHOW VIEW ON factory_demo.* TO 'zhixi_reader'@'%';

CREATE USER 'zhixi_writer'@'%' IDENTIFIED BY 'writer-local-only';
GRANT SELECT, INSERT ON factory_demo.* TO 'zhixi_writer'@'%';
