-- Run once as a MySQL administrator. This creates only synthetic exercise data.
-- Replace the password placeholder before running this file.
CREATE DATABASE IF NOT EXISTS inetz_analytics_practice;
USE inetz_analytics_practice;
CREATE TABLE IF NOT EXISTS teams (id INT PRIMARY KEY, name VARCHAR(80));
CREATE TABLE IF NOT EXISTS employees (id INT PRIMARY KEY, name VARCHAR(80), team_id INT, salary DECIMAL(12,2));
CREATE TABLE IF NOT EXISTS orders (id INT PRIMARY KEY, region VARCHAR(80), amount DECIMAL(12,2), status VARCHAR(30));
INSERT IGNORE INTO teams VALUES (1,'Engineering'),(2,'Analytics'),(3,'Design');
INSERT IGNORE INTO employees VALUES (1,'Ada',1,125000),(2,'Sam',1,105000),(3,'Maya',2,98000),(4,'Lin',2,112000),(5,'Ari',3,96000);
INSERT IGNORE INTO orders VALUES (1,'South',1200,'Complete'),(2,'North',800,'Complete'),(3,'South',450,'Pending'),(4,'West',1700,'Complete'),(5,'North',250,'Complete');
CREATE USER 'inetz_analytics_reader'@'127.0.0.1' IDENTIFIED BY 'REPLACE_WITH_A_UNIQUE_PASSWORD';
GRANT SELECT ON inetz_analytics_practice.* TO 'inetz_analytics_reader'@'127.0.0.1';
