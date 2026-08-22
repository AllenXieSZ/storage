#!/usr/bin/env python3
# 给 country model 的 getCountry/getCountryByIsoCode2/3 加 Redis 缓存包装
import sys, re

f = "/var/www/html/catalog/model/localisation/country.php"
s = open(f).read()

if "country.info." in s or "country.iso2." in s:
    print("already patched"); sys.exit(0)

# --- getCountry ---
old_getcountry = """	public function getCountry(int $country_id): array {
		$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "country` `c` LEFT JOIN `" . DB_PREFIX . "country_description` `cd` ON (`c`.`country_id` = `cd`.`country_id`) WHERE `c`.`country_id` = '" . (int)$country_id . "' AND `cd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `c`.`status` = '1'");

		return $query->row;
	}"""
new_getcountry = """	public function getCountry(int $country_id): array {
		$ck = 'country.info.' . (int)$country_id . '.' . (int)$this->config->get('config_language_id');
		$data = $this->cache->get($ck);
		if (empty($data)) {
			$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "country` `c` LEFT JOIN `" . DB_PREFIX . "country_description` `cd` ON (`c`.`country_id` = `cd`.`country_id`) WHERE `c`.`country_id` = '" . (int)$country_id . "' AND `cd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `c`.`status` = '1'");
			$data = $query->row;
			$this->cache->set($ck, $data);
		}

		return $data;
	}"""

# --- getCountryByIsoCode2 ---
old_iso2 = """	public function getCountryByIsoCode2(string $iso_code_2): array {
		$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "country` `c` LEFT JOIN `" . DB_PREFIX . "country_description` `cd` ON (`c`.`country_id` = `cd`.`country_id`) WHERE `iso_code_2` = '" . $this->db->escape($iso_code_2) . "' AND `cd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `c`.`status` = '1'");

		return $query->row;
	}"""
new_iso2 = """	public function getCountryByIsoCode2(string $iso_code_2): array {
		$ck = 'country.iso2.' . strtolower($iso_code_2) . '.' . (int)$this->config->get('config_language_id');
		$data = $this->cache->get($ck);
		if (empty($data)) {
			$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "country` `c` LEFT JOIN `" . DB_PREFIX . "country_description` `cd` ON (`c`.`country_id` = `cd`.`country_id`) WHERE `iso_code_2` = '" . $this->db->escape($iso_code_2) . "' AND `cd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `c`.`status` = '1'");
			$data = $query->row;
			$this->cache->set($ck, $data);
		}

		return $data;
	}"""

# --- getCountryByIsoCode3 ---
old_iso3 = """	public function getCountryByIsoCode3(string $iso_code_3): array {
		$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "country` `c` LEFT JOIN `" . DB_PREFIX . "country_description` `cd` ON (`c`.`country_id` = `cd`.`country_id`) WHERE `iso_code_3` = '" . $this->db->escape($iso_code_3) . "' AND `cd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `c`.`status` = '1'");

		return $query->row;
	}"""
new_iso3 = """	public function getCountryByIsoCode3(string $iso_code_3): array {
		$ck = 'country.iso3.' . strtolower($iso_code_3) . '.' . (int)$this->config->get('config_language_id');
		$data = $this->cache->get($ck);
		if (empty($data)) {
			$query = $this->db->query("SELECT * FROM `" . DB_PREFIX . "country` `c` LEFT JOIN `" . DB_PREFIX . "country_description` `cd` ON (`c`.`country_id` = `cd`.`country_id`) WHERE `iso_code_3` = '" . $this->db->escape($iso_code_3) . "' AND `cd`.`language_id` = '" . (int)$this->config->get('config_language_id') . "' AND `c`.`status` = '1'");
			$data = $query->row;
			$this->cache->set($ck, $data);
		}

		return $data;
	}"""

n = 0
for old, new in [(old_getcountry,new_getcountry),(old_iso2,new_iso2),(old_iso3,new_iso3)]:
    if old in s:
        s = s.replace(old, new); n += 1
    else:
        print(f"WARN: pattern not found (#{n+1})")

open(f,"w").write(s)
print(f"patched {n}/3 methods")
