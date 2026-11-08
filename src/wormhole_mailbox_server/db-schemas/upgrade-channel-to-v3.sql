-- Add an explicit, portable tie-breaker for message replay order.
--
-- SQLite cannot add an AUTOINCREMENT primary key with ALTER TABLE, so the
-- table is rebuilt. Existing rows keep their insertion order by copying
-- them in rowid order, which matches the order they were previously read
-- in (the old query only ordered by `server_rx`).

CREATE TABLE `messages_v3`
(
 `id` INTEGER PRIMARY KEY AUTOINCREMENT,
 `app_id` VARCHAR,
 `mailbox_id` VARCHAR,
 `side` VARCHAR,
 `phase` VARCHAR,
 `body` VARCHAR,
 `server_rx` INTEGER,
 `msg_id` VARCHAR
);

INSERT INTO `messages_v3`
 (`app_id`, `mailbox_id`, `side`, `phase`, `body`, `server_rx`, `msg_id`)
SELECT `app_id`, `mailbox_id`, `side`, `phase`, `body`, `server_rx`, `msg_id`
FROM `messages`
ORDER BY `rowid`;

DROP TABLE `messages`;
ALTER TABLE `messages_v3` RENAME TO `messages`;
CREATE INDEX `messages_idx` ON `messages` (`app_id`, `mailbox_id`);

-- The v1->v2 channel upgrade added an unused `ends` column that was never
-- part of the fresh v2 schema. Drop it so upgraded databases match fresh
-- ones. SQLite's DROP COLUMN needs 3.35+, so rebuild instead.
CREATE TABLE `addrid_generation_v3`
(
 `generation` INTEGER,
 `started` INTEGER
);

INSERT INTO `addrid_generation_v3` (`generation`, `started`)
SELECT `generation`, `started` FROM `addrid_generation`;

DROP TABLE `addrid_generation`;
ALTER TABLE `addrid_generation_v3` RENAME TO `addrid_generation`;

DELETE FROM `version`;
INSERT INTO `version` (`version`) VALUES (3);
