<?php
/**
 * @package        OpenCart
 *
 * @author         Daniel Kerr
 * @copyright      Copyright (c) 2005 - 2022, OpenCart, Ltd. (https://www.opencart.com/)
 * @license        https://opensource.org/licenses/GPL-3.0
 *
 * @see           https://www.opencart.com
 */
namespace Opencart\System\Library;
/**
 * Class DB Adaptor
 *
 * @package Opencart\System\Library
 */
class DB {
	/**
	 * @var object
	 */
	private object $adaptor;

	/**
	 * @var object|null reader 只读连接(读写分离用)
	 */
	private $reader = null;

	/**
	 * @var bool 是否在事务中(事务内所有查询必须走 writer 保证一致性)
	 */
	private bool $inTransaction = false;

	/**
	 * Constructor
	 *
	 * @param string $adaptor
	 * @param string $hostname
	 * @param string $username
	 * @param string $password
	 * @param string $database
	 * @param string $port
	 * @param string $ssl_key
	 * @param string $ssl_cert
	 * @param string $ssl_ca
	 */
	public function __construct(string $adaptor, string $hostname, string $username, string $password, string $database, string $port = '', string $ssl_key = '', string $ssl_cert = '', string $ssl_ca = '') {
		$class = 'Opencart\System\Library\DB\\' . $adaptor;

		if (class_exists($class)) {
			$this->adaptor = new $class($hostname, $username, $password, $database, $port, $ssl_key, $ssl_cert, $ssl_ca);
		} else {
			throw new \Exception('Error: Could not load database adaptor ' . $adaptor . '!');
		}

		// [READ-SPLIT] 读写分离：若定义了 DB_READER_HOSTNAME，建立只读连接(连 Aurora reader endpoint)
		if (defined('DB_READER_HOSTNAME') && DB_READER_HOSTNAME && DB_READER_HOSTNAME !== $hostname) {
			try {
				$this->reader = new $class(DB_READER_HOSTNAME, $username, $password, $database, $port, $ssl_key, $ssl_cert, $ssl_ca);
			} catch (\Throwable $e) {
				$this->reader = null;   // reader 连不上，安全降级：所有查询走 writer
			}
		}
	}

	/**
	 * Query
	 *
	 * @param string $sql SQL statement to be executed
	 *
	 * @return mixed
	 */
	public function query(string $sql) {
		// [READ-SPLIT] SELECT 且不在事务中 → 走 reader；其余(INSERT/UPDATE/DELETE/事务)走 writer
		if ($this->reader !== null && !$this->inTransaction) {
			$s = ltrim($sql);
			// 仅纯 SELECT 分流；SELECT ... FOR UPDATE / GET_LOCK 等需强一致的仍走 writer
			if (stripos($s, 'SELECT') === 0 && stripos($s, 'FOR UPDATE') === false && stripos($s, 'GET_LOCK') === false && stripos($s, 'LAST_INSERT_ID') === false) {
				try {
					return $this->reader->query($sql);
				} catch (\Throwable $e) {
					return $this->adaptor->query($sql);   // reader 出错降级 writer
				}
			}
			// 进入事务：标记，后续查询都走 writer
			if (stripos($s, 'START TRANSACTION') === 0 || stripos($s, 'BEGIN') === 0) {
				$this->inTransaction = true;
			}
		} else if ($this->inTransaction) {
			$s = ltrim($sql);
			if (stripos($s, 'COMMIT') === 0 || stripos($s, 'ROLLBACK') === 0) {
				$this->inTransaction = false;
			}
		}
		return $this->adaptor->query($sql);
	}

	/**
	 * Escape
	 *
	 * @param string $value Value to be protected against SQL injections
	 *
	 * @return string Returns escaped value
	 */
	public function escape(string $value): string {
		return $this->adaptor->escape($value);
	}

	/**
	 * Count Affected
	 *
	 * Gets the total number of affected rows from the last query
	 *
	 * @return int returns the total number of affected rows
	 */
	public function countAffected(): int {
		return $this->adaptor->countAffected();
	}

	/**
	 * Get Last Id
	 *
	 * Get the last ID gets the primary key that was returned after creating a row in a table.
	 *
	 * @return int Returns last ID
	 */
	public function getLastId(): int {
		return $this->adaptor->getLastId();
	}

	/**
	 * Is Connected
	 *
	 * Checks if a DB connection is active.
	 *
	 * @return bool
	 */
	public function isConnected(): bool {
		return $this->adaptor->isConnected();
	}
}
