CREATE TABLE `client_versions`
(
 `app_id` VARCHAR,
 `side` VARCHAR, -- for deduplication of reconnects
 `connect_time` INTEGER, -- seconds since epoch, rounded to "blur time"
 -- the client sends us a 'client_version' tuple of (implementation, version)
 -- the Python client sends e.g. ("python", "0.11.0")
 `implementation` VARCHAR,
 `version` VARCHAR
);
CREATE INDEX `client_versions_time_idx` on `client_versions` (`connect_time`);
CREATE INDEX `client_versions_appid_time_idx` on `client_versions` (`app_id`, `connect_time`);

DELETE FROM `version`;
INSERT INTO `version` (`version`) VALUES (2);
