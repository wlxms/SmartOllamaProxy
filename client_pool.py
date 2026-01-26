"""
HTTP客户端池管理器
用于集中管理和复用httpx.AsyncClient实例，提高连接复用率
"""

import asyncio
import logging
from typing import Dict, Tuple, Optional
import httpx

logger = logging.getLogger("smart_ollama_proxy.client_pool")


class ClientPool:
    """
    HTTP客户端池管理器
    
    为每个唯一的(base_url, api_key)组合创建并复用单个client实例，
    避免相同后端配置的路由器重复创建client，提高连接复用率。
    """
    
    # 健康检查配置
    HEALTH_CHECK_THRESHOLD = 30.0  # 健康检查阈值（秒），空闲超过此时间才进行健康检查
    HEALTH_CHECK_TIMEOUT = 2.0     # 健康检查超时时间（秒）
    
    _instance = None
    _lock = asyncio.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._clients: Dict[Tuple[str, Optional[str], bool], httpx.AsyncClient] = {}
            self._ref_counts: Dict[Tuple[str, Optional[str], bool], int] = {}
            self._last_used: Dict[Tuple[str, Optional[str], bool], float] = {}
            self._initialized = True
            logger.info("ClientPool 初始化完成")
    
    async def get_client(
        self, 
        base_url: str, 
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        limits: Optional[httpx.Limits] = None,
        http2: bool = True,
        compression: bool = True
    ) -> httpx.AsyncClient:
        """
        获取或创建HTTP客户端
        
        Args:
            base_url: 基础URL
            api_key: API密钥（可选）
            compression: 是否启用HTTP压缩解压支持
            timeout: 超时时间（秒）
            limits: 连接限制配置
            http2: 是否启用HTTP/2
            compression: 是否启用HTTP压缩解压支持
            
        Returns:
            httpx.AsyncClient实例
        """
        import time
        
        # 创建客户端标识键
        client_key = (base_url.rstrip('/'), api_key, compression)
        
        async with self._lock:
            # 检查现有客户端
            if client_key in self._clients:
                client = self._clients[client_key]
                current_time = time.time()
                last_used = self._last_used.get(client_key, 0)
                
                # 检查是否需要健康检查（空闲时间超过阈值）
                if current_time - last_used > self.HEALTH_CHECK_THRESHOLD:
                    logger.debug(f"客户端空闲超过阈值，进行健康检查: {base_url}")
                    try:
                        # 执行简单的健康检查（HEAD请求）
                        health_check_url = base_url.rstrip('/') + '/'
                        await client.head(health_check_url, timeout=self.HEALTH_CHECK_TIMEOUT)
                        logger.debug(f"客户端健康检查通过: {base_url}")
                    except Exception as e:
                        logger.warning(f"客户端健康检查失败，创建新客户端: {base_url}, 错误: {e}")
                        # 关闭旧客户端并移除
                        try:
                            await client.aclose()
                        except:
                            pass
                        # 从池中移除
                        del self._clients[client_key]
                        del self._ref_counts[client_key]
                        self._last_used.pop(client_key, None)
                        # 跳出if块，继续创建新客户端
                        # 设置client_key不在_clients中，让代码继续执行创建新客户端
                        pass  # 继续执行后面的创建逻辑
                    else:
                        # 健康检查通过，更新最后使用时间和引用计数
                        self._ref_counts[client_key] += 1
                        self._last_used[client_key] = current_time
                        logger.debug(f"复用现有客户端: {base_url} (引用计数: {self._ref_counts[client_key]})")
                        return client
                else:
                    # 不需要健康检查，直接复用
                    self._ref_counts[client_key] += 1
                    self._last_used[client_key] = current_time
                    logger.debug(f"复用现有客户端: {base_url} (引用计数: {self._ref_counts[client_key]})")
                    return client
            
            # 创建新的客户端（包括健康检查失败的情况）
            logger.info(f"创建新的HTTP客户端: {base_url}")
            
            # 默认连接池配置
            if limits is None:
                limits = httpx.Limits(
                    max_keepalive_connections=100,  # 每个主机保持的连接数（提高复用率）
                    max_connections=200,           # 最大总连接数
                    keepalive_expiry=300.0         # 连接保持时间（秒）- 增加到5分钟
                )
            
            # 创建客户端
            logger.debug(f"创建HTTP客户端，启用压缩: {compression}")
            # 设置Accept-Encoding头以启用HTTP压缩
            headers = {"Accept-Encoding": "gzip, deflate, br"} if compression else {}
            client = httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                http2=http2,
                headers=headers
            )
            
            # 存储客户端
            self._clients[client_key] = client
            self._ref_counts[client_key] = 1
            self._last_used[client_key] = time.time()
            
            return client
    
    async def release_client(self, base_url: str, api_key: Optional[str] = None, compression: bool = True):
        """
        释放客户端引用
        
        Args:
            base_url: 基础URL
            api_key: API密钥（可选）
        """
        client_key = (base_url.rstrip('/'), api_key, compression)
        
        async with self._lock:
            if client_key in self._ref_counts:
                self._ref_counts[client_key] -= 1
                
                if self._ref_counts[client_key] <= 0:
                    # 引用计数为0，关闭并移除客户端
                    logger.info(f"关闭并移除HTTP客户端: {base_url}")
                    client = self._clients.pop(client_key, None)
                    self._ref_counts.pop(client_key, None)
                    self._last_used.pop(client_key, None)
                    
                    if client:
                        try:
                            await client.aclose()
                        except Exception as e:
                            logger.warning(f"关闭客户端失败: {e}")
                else:
                    logger.debug(f"释放客户端引用: {base_url} (剩余引用: {self._ref_counts[client_key]})")
    
    async def close_all(self):
        """关闭所有客户端"""
        async with self._lock:
            logger.info(f"正在关闭所有HTTP客户端 (总数: {len(self._clients)})")
            
            close_tasks = []
            for client_key, client in self._clients.items():
                close_tasks.append(client.aclose())
            
            if close_tasks:
                await asyncio.gather(*close_tasks, return_exceptions=True)
            
            self._clients.clear()
            self._ref_counts.clear()
            self._last_used.clear()
            logger.info("所有HTTP客户端已关闭")
    
    def get_stats(self) -> Dict:
        """获取客户端池统计信息"""
        return {
            "total_clients": len(self._clients),
            "clients": [
                {
                    "base_url": key[0],
                    "has_api_key": key[1] is not None,
                    "compression_enabled": key[2],
                    "ref_count": self._ref_counts.get(key, 0)
                }
                for key in self._clients.keys()
            ]
        }


# 全局客户端池实例
client_pool = ClientPool()