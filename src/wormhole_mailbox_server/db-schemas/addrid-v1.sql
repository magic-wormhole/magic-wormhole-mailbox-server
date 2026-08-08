CREATE TABLE `version`
(
 `version` INTEGER -- contains one row, set to 1
);

CREATE TABLE `address_ids`
(
  `generation` INTEGER,
  `counter` INTEGER,
  `type` VARCHAR, -- "ipv4" or "ipv6"
  `address` VARCHAR, -- "1.2.3.4" or "1:2::3:4"
  `retain` INTEGER
);
