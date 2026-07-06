-- Create a dedicated database + user for the pipeforge warehouse,
-- separate from Airflow's own metadata database.
CREATE USER pipeforge WITH PASSWORD 'pipeforge';
CREATE DATABASE pipeforge OWNER pipeforge;
GRANT ALL PRIVILEGES ON DATABASE pipeforge TO pipeforge;
