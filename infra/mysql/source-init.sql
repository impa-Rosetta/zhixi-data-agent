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

INSERT INTO production_orders (order_no, product_code, planned_quantity, completed_quantity)
VALUES
    ('MO-2026-001', 'MOTOR-A', 1000, 960),
    ('MO-2026-002', 'MOTOR-B', 800, 620);

INSERT INTO quality_inspections
    (order_id, inspected_quantity, defect_quantity, result)
VALUES
    (1, 200, 3, 'passed'),
    (1, 200, 8, 'failed'),
    (2, 100, 1, 'passed');

CREATE USER 'zhixi_reader'@'%' IDENTIFIED BY 'reader-local-only';
GRANT SELECT, SHOW VIEW ON factory_demo.* TO 'zhixi_reader'@'%';

CREATE USER 'zhixi_writer'@'%' IDENTIFIED BY 'writer-local-only';
GRANT SELECT, INSERT ON factory_demo.* TO 'zhixi_writer'@'%';
