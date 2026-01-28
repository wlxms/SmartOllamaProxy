"""
Cache manager with TTL and LRU eviction for tools and prompts.
提供工具和提示词缓存管理，支持TTL和LRU淘汰。
"""
import logging
import time
from typing import Dict, Any, Optional, Tuple, List
import hashlib
from utils import json

logger = logging.getLogger("smart_ollama_proxy.cache_manager")


class CacheEntry:
    """缓存条目"""
    
    __slots__ = ('value', 'timestamp', 'access_count')
    
    def __init__(self, value: Any, timestamp: float):
        self.value = value
        self.timestamp = timestamp
        self.access_count = 0
    
    def touch(self):
        """更新访问计数"""
        self.access_count += 1


class CacheManager:
    """通用缓存管理器，支持TTL和LRU淘汰"""
    
    def __init__(self, max_size: int = 100, default_ttl: float = 300.0):
        """
        初始化缓存管理器
        
        Args:
            max_size: 最大缓存条目数
            default_ttl: 默认TTL（秒）
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = None  # 可选的异步锁
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值，如果过期返回None"""
        if key not in self._cache:
            return None
        
        entry = self._cache[key]
        current_time = time.time()
        
        # 检查是否过期
        if current_time - entry.timestamp > self.default_ttl:
            del self._cache[key]
            return None
        
        entry.touch()
        return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        """设置缓存值"""
        current_time = time.time()
        
        # 如果缓存已满，淘汰最久未使用的条目
        if len(self._cache) >= self.max_size and key not in self._cache:
            self._evict()
        
        entry = CacheEntry(value, current_time)
        self._cache[key] = entry
    
    def delete(self, key: str):
        """删除缓存条目"""
        self._cache.pop(key, None)
    
    def clear(self):
        """清空缓存"""
        self._cache.clear()
    
    def _evict(self):
        """淘汰最久未使用的条目（LRU策略）"""
        if not self._cache:
            return
        
        # 找到访问次数最少的条目
        lru_key = min(self._cache.items(), key=lambda x: x[1].access_count)[0]
        del self._cache[lru_key]
    
    def cleanup(self):
        """清理过期条目"""
        current_time = time.time()
        expired_keys = []
        
        for key, entry in self._cache.items():
            if current_time - entry.timestamp > self.default_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            logger.debug(f"清理了 {len(expired_keys)} 个过期缓存条目")
    
    def stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        current_time = time.time()
        valid_count = 0
        expired_count = 0
        
        for entry in self._cache.values():
            if current_time - entry.timestamp > self.default_ttl:
                expired_count += 1
            else:
                valid_count += 1
        
        return {
            "total_entries": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": expired_count,
            "max_size": self.max_size,
            "default_ttl": self.default_ttl,
        }


class ToolsCache(CacheManager):
    """工具列表专用缓存"""
    
    def __init__(self, max_size: int = 100, ttl: float = 300.0):
        super().__init__(max_size=max_size, default_ttl=ttl)
    
    def compute_key(self, session_id: str, tools: List[Dict[str, Any]]) -> str:
        """计算工具列表的缓存键"""
        tools_str = json.dumps(tools, sort_keys=True)
        tools_hash = hashlib.md5(tools_str.encode()).hexdigest()
        return f"tools:{session_id}:{tools_hash}"
    
    def get_compressed_tools(self, session_id: str, tools: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """获取压缩后的工具列表"""
        key = self.compute_key(session_id, tools)
        return self.get(key)
    
    def set_compressed_tools(self, session_id: str, tools: List[Dict[str, Any]], compressed_tools: List[Dict[str, Any]]):
        """设置压缩后的工具列表"""
        key = self.compute_key(session_id, tools)
        self.set(key, compressed_tools)


class PromptCache(CacheManager):
    """提示词专用缓存"""
    
    def __init__(self, max_size: int = 100, ttl: float = 300.0):
        super().__init__(max_size=max_size, default_ttl=ttl)
    
    def compute_key(self, session_id: str, prompt_content: str) -> str:
        """计算提示词的缓存键"""
        prompt_hash = hashlib.md5(prompt_content.encode()).hexdigest()
        return f"prompt:{session_id}:{prompt_hash}"
    
    def get_prompt(self, session_id: str, prompt_content: str) -> Optional[Dict[str, Any]]:
        """获取缓存的提示词信息"""
        key = self.compute_key(session_id, prompt_content)
        return self.get(key)
    
    def set_prompt(self, session_id: str, prompt_content: str, prompt_info: Dict[str, Any]):
        """设置提示词缓存"""
        key = self.compute_key(session_id, prompt_content)
        self.set(key, prompt_info)