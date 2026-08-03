CREATE TABLE `addrid_generation` -- one row
(
 `generation` INTEGER, -- current generation ID, increments from one
 `started` INTEGER, -- time when this generation started
 `ends` INTEGER -- scheduled end of this generation
);

CREATE TABLE `connections`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `addrid_generation` INTEGER,
 `addrid_counter` INTEGER,
 `connected` INTEGER, -- seconds since epoch: websocket establishment
 `side` VARCHAR,
 `implementation` VARCHAR,
 `version` VARCHAR,
 `active` INTEGER -- second since epoch: last command received
);

CREATE TABLE `connection_messages`
(
 `id` REFERENCES `connections`(`id`),
 `when` INTEGER,
 `name` VARCHAR
);

DELETE FROM `version`;
INSERT INTO `version` (`version`) VALUES (2);
