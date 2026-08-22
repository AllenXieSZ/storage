#!/usr/bin/env python3
# 给 zone model 的 getZone 加 Redis 缓存
import sys
f = "/var/www/html/catalog/model/localisation/zone.php"
s = open(f).read()
if "zone.info." in s:
    print("already patched"); sys.exit(0)

old = """	public function getZone(int $zone_id): array {
		$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "zone` `z` LEFT JOIN `" . DB_PREFIX . "zone_description` `zd` ON (`z`.`zone_id` = `zd`.`zone_id`) WHERE `z`.`zone_id` = '" . (int)$zone_id . "' AND `zd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `z`.`status` = '1'");

		return $query->row;
	}"""
new = """	public function getZone(int $zone_id): array {
		$ck = 'zone.info.' . (int)$zone_id . '.' . (int)$this->config->get('config_language_id');
		$data = $this->cache->get($ck);
		if (empty($data)) {
			$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "zone` `z` LEFT JOIN `" . DB_PREFIX . "zone_description` `zd` ON (`z`.`zone_id` = `zd`.`zone_id`) WHERE `z`.`zone_id` = '" . (int)$zone_id . "' AND `zd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `z`.`status` = '1'");
			$data = $query->row;
			$this->cache->set($ck, $data);
		}

		return $data;
	}"""

if old in s:
    s = s.replace(old, new)
    open(f,"w").write(s)
    print("patched getZone")
else:
    print("WARN: getZone pattern not found")
