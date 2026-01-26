"""
后端路由器工厂和管理器
提供路由器创建和管理的统一接口
"""
import logging
from typing import Dict, Any, Optional

from config_loader import BackendConfig
from .base_router import BackendRouter
from .openai_router import OpenAIBackendRouter
from .litellm_router import LiteLLMRouter
from .ollama_router import OllamaBackendRouter
from .mock_router import MockBackendRouter

logger = logging.getLogger("smart_ollama_proxy.backend_router")


class BackendRouterFactory:
    """后端路由器工厂"""
    
    @staticmethod
    def create_router(backend_config: BackendConfig, backend_type: Optional[str] = None,
                      verbose_json_logging: bool = False,
                      tool_compression_enabled: bool = True,
                      prompt_compression_enabled: bool = True) -> BackendRouter:
        """
        创建后端路由器
        
        Args:
            backend_config: 后端配置
            backend_type: 后端类型，如果为None则根据配置自动判断
            verbose_json_logging: 是否启用详细的JSON日志记录
            tool_compression_enabled: 是否启用工具压缩优化
            prompt_compression_enabled: 是否启用重复提示词压缩优化
            
        Returns:
            后端路由器实例
        """
        if backend_type is None:
            # 优先使用配置中的backend_type
            if backend_config.backend_type:
                backend_type = backend_config.backend_type
                logger.debug(f"使用配置指定的后端类型: {backend_type}")
            elif backend_config.backend_mode:
                # 根据backend_mode推断backend_type
                if backend_config.backend_mode == "litellm_backend":
                    backend_type = "litellm"
                    logger.debug(f"根据backend_mode推断后端类型为: {backend_type}")
                elif backend_config.backend_mode == "openai_backend":
                    backend_type = "openai"
                    logger.debug(f"根据backend_mode推断后端类型为: {backend_type}")
                else:
                    # 其他backend_mode，尝试从名称推断
                    if "litellm" in backend_config.backend_mode:
                        backend_type = "litellm"
                    elif "openai" in backend_config.backend_mode:
                        backend_type = "openai"
                    else:
                        # 默认为openai
                        backend_type = "openai"
                    logger.debug(f"根据backend_mode名称推断后端类型为: {backend_type}")
            else:
                # 根据base_url自动判断类型
                base_url = backend_config.base_url.lower()
                if "openai.com" in base_url or "api.deepseek.com" in base_url or "api.anthropic.com" in base_url:
                    backend_type = "openai"
                elif "localhost" in base_url or "127.0.0.1" in base_url:
                    backend_type = "ollama"
                else:
                    # 默认为OpenAI兼容
                    backend_type = "openai"
                logger.debug(f"自动判断后端类型为: {backend_type} (base_url: {base_url})")
        
        # 映射兼容的后端类型
        backend_type_map = {
            "http": "openai",     # HTTP映射到openai（OpenAI SDK + HTTP回退）
            "openai_compat": "openai",  # OpenAI兼容
        }
        if backend_type in backend_type_map:
            mapped_type = backend_type_map[backend_type]
            logger.debug(f"映射后端类型 {backend_type} -> {mapped_type}")
            backend_type = mapped_type
        
        logger.info(f"创建后端路由器: 类型={backend_type}, backend_mode={backend_config.backend_mode}, base_url={backend_config.base_url}")
        
        if backend_type == "openai" or backend_type == "openai_sdk":
            return OpenAIBackendRouter(backend_config, verbose_json_logging,
                                       tool_compression_enabled=tool_compression_enabled,
                                       prompt_compression_enabled=prompt_compression_enabled)
        elif backend_type == "litellm":
            return LiteLLMRouter(backend_config, verbose_json_logging,
                                 tool_compression_enabled=tool_compression_enabled,
                                 prompt_compression_enabled=prompt_compression_enabled)
        elif backend_type == "ollama":
            return OllamaBackendRouter(backend_config,
                                       tool_compression_enabled=tool_compression_enabled,
                                       prompt_compression_enabled=prompt_compression_enabled)
        elif backend_type == "mock":
            return MockBackendRouter(backend_config,
                                     tool_compression_enabled=tool_compression_enabled,
                                     prompt_compression_enabled=prompt_compression_enabled)
        else:
            raise ValueError(f"不支持的后端类型: {backend_type}")
    
    @staticmethod
    def create_router_from_config(
        backend_config: BackendConfig, 
        config_data: Dict[str, Any]
    ) -> BackendRouter:
        """
        从配置数据创建路由器
        
        Args:
            backend_config: 后端配置
            config_data: 完整的配置数据
            
        Returns:
            后端路由器实例
        """
        # 从配置数据中提取路由器参数
        verbose_json_logging = config_data.get("proxy", {}).get("verbose_json_logging", False)
        tool_compression_enabled = config_data.get("proxy", {}).get("tool_compression_enabled", True)
        prompt_compression_enabled = config_data.get("proxy", {}).get("prompt_compression_enabled", True)
        
        return BackendRouterFactory.create_router(
            backend_config=backend_config,
            backend_type=backend_config.backend_type,
            verbose_json_logging=verbose_json_logging,
            tool_compression_enabled=tool_compression_enabled,
            prompt_compression_enabled=prompt_compression_enabled
        )


class BackendManager:
    """后端管理器，统一管理所有后端路由器"""
    
    def __init__(self):
        self.routers: Dict[str, BackendRouter] = {}
    
    def register_router(self, name: str, router: BackendRouter):
        """注册后端路由器"""
        self.routers[name] = router
        logger.info(f"注册后端路由器: {name}")
    
    def get_router(self, name: str) -> Optional[BackendRouter]:
        """获取后端路由器"""
        return self.routers.get(name)
    
    async def handle_request(
        self,
        router_name: str,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        convert_to_ollama: bool = False,
        virtual_model: Optional[str] = None,
        support_thinking: bool = False
    ) -> Any:
        """
        通过指定的路由器处理请求
        
        Args:
            router_name: 路由器名称
            actual_model: 实际模型名称
            request_data: 请求数据
            stream: 是否流式
            convert_to_ollama: 是否转换为Ollama格式
            virtual_model: 虚拟模型名称（用于转换）
            support_thinking: 是否支持thinking能力
            
        Returns:
            响应数据
        """
        router = self.get_router(router_name)
        if not router:
            raise ValueError(f"未找到后端路由器: {router_name}")
        
        # 处理请求
        response = await router.handle_request(actual_model, request_data, stream, support_thinking)
        
        # 如果需要转换为Ollama格式且不是流式响应
        if convert_to_ollama and not stream and virtual_model:
            from fastapi.responses import JSONResponse
            if isinstance(response, JSONResponse):
                ollama_result = router.convert_to_ollama_format(response, virtual_model)
                return JSONResponse(content=ollama_result)
        
        return response