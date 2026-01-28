"""
Client manager for unified handling of HTTP and SDK clients.
统一管理HTTP客户端和SDK客户端的管理器。
"""
import logging
import asyncio
from typing import Dict, Any, Optional, Tuple
import httpx

from client_pool import client_pool

logger = logging.getLogger("smart_ollama_proxy.client_manager")


class ClientManager:
    """客户端管理器，统一管理HTTP和SDK客户端"""
    
    def __init__(self):
        self._http_clients: Dict[Tuple[str, Optional[str], bool], httpx.AsyncClient] = {}
        self._sdk_clients: Dict[Tuple[str, Optional[str], Optional[str]], Any] = {}
        self._lock = asyncio.Lock()
    
    async def get_http_client(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        timeout: float = 30.0,
        compression: bool = True
    ) -> httpx.AsyncClient:
        """获取HTTP客户端（委托给全局client_pool）"""
        return await client_pool.get_client(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            compression=compression
        )
    
    async def release_http_client(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        compression: bool = True
    ):
        """释放HTTP客户端引用"""
        await client_pool.release_client(
            base_url=base_url,
            api_key=api_key,
            compression=compression
        )
    
    async def get_sdk_client(
        self,
        sdk_type: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ) -> Any:
        """获取SDK客户端（如OpenAI、LiteLLM）"""
        client_key = (sdk_type, api_key, base_url)
        
        async with self._lock:
            if client_key in self._sdk_clients:
                return self._sdk_clients[client_key]
            
            # 创建新的SDK客户端
            client = self._create_sdk_client(sdk_type, api_key, base_url, **kwargs)
            self._sdk_clients[client_key] = client
            return client
    
    def _create_sdk_client(
        self,
        sdk_type: str,
        api_key: Optional[str],
        base_url: Optional[str],
        **kwargs
    ) -> Any:
        """创建SDK客户端实例"""
        if sdk_type == "openai":
            try:
                import openai
                client = openai.AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url.rstrip('/') if base_url else None,
                    **kwargs
                )
                logger.debug(f"创建OpenAI SDK客户端: base_url={base_url}")
                return client
            except ImportError:
                raise ImportError("OpenAI SDK未安装，请运行: pip install openai")
        elif sdk_type == "litellm":
            try:
                import litellm
                # LiteLLM 使用全局配置，不需要客户端实例
                # 返回一个虚拟客户端对象，实际调用时使用 litellm.acompletion
                class LiteLLMClient:
                    def __init__(self):
                        self.sdk_type = "litellm"
                
                logger.debug(f"创建LiteLLM SDK客户端")
                return LiteLLMClient()
            except ImportError:
                raise ImportError("LiteLLM SDK未安装，请运行: pip install litellm")
        else:
            raise ValueError(f"不支持的SDK类型: {sdk_type}")
    
    async def close_all(self):
        """关闭所有客户端"""
        # HTTP客户端由client_pool统一管理，这里只关闭SDK客户端
        # SDK客户端通常不需要显式关闭
        self._sdk_clients.clear()


# 全局客户端管理器实例
client_manager = ClientManager()