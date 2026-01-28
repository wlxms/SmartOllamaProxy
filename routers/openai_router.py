"""
OpenAI兼容后端路由器
优先使用OpenAI Python SDK，失败时回退到HTTP请求
重构版：使用基类组件减少重复代码，保留HTTP回退
"""
import logging
import time
import uuid
from typing import Dict, Any, Optional
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config_loader import BackendConfig
from client_pool import client_pool
from .base_router import BackendRouter
from routers.core.response_converter import ResponseConverter
from utils import sanitize_message, json

# 导入智能日志处理器
from smart_logger import get_smart_logger
smart_logger = get_smart_logger()

logger = logging.getLogger("smart_ollama_proxy.backend_router")


class OpenAIBackendRouter(BackendRouter):
    """OpenAI兼容后端路由器（优先SDK，失败回退HTTP）"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config, verbose_json_logging,  # type: ignore
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        # OpenAI客户端将在第一次请求时初始化
        self._openai_client: Optional[Any] = None
        
        # SDK状态跟踪（性能优化：避免重复尝试失败的SDK）
        self._sdk_status = "unknown"  # "unknown", "available", "unavailable"
        self._last_sdk_check = 0  # 上次检查时间戳
        self._sdk_check_interval = 300  # 检查间隔（秒），5分钟
        
        # 响应转换器（复用基类的实例）
        self._converter = ResponseConverter()
    
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理OpenAI兼容请求（优先使用OpenAI SDK，失败回退HTTP）"""
        import time
        request_start = time.time()
        
        logger.debug(f"[OpenAIBackendRouter] 处理请求")
        logger.debug(f"实际模型: {actual_model}")
        logger.debug(f"流式: {stream}")
        logger.debug(f"支持thinking: {support_thinking}")
        
        # 优化工具列表和提示词（复用基类方法）
        request_data = self._optimize_tools_in_request(request_data)
        request_data = self._optimize_prompt(request_data)
        
        # 智能判断：如果SDK已知不可用且在检查间隔内，直接使用HTTP
        current_time = time.time()
        if (self._sdk_status == "unavailable" and 
            current_time - self._last_sdk_check < self._sdk_check_interval):
            logger.debug(f"[OpenAIBackendRouter] SDK标记为不可用，直接使用HTTP（上次检查: {self._last_sdk_check:.0f}）")
            response = await self._handle_with_http(
                actual_model, request_data, stream, support_thinking
            )
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter] HTTP请求完成，耗时: {request_time:.3f}秒")
            return response
        
        # 尝试使用 OpenAI SDK
        try:
            response = await self._handle_with_openai_sdk(
                actual_model, request_data, stream, support_thinking
            )
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter] OpenAI SDK请求完成，耗时: {request_time:.3f}秒")
            
            # SDK请求成功，标记为可用
            if self._sdk_status != "available":
                self._sdk_status = "available"
                logger.debug(f"[OpenAIBackendRouter] SDK状态更新为: available")
            
            return response
        except ImportError:
            logger.warning("OpenAI SDK包未安装，回退到HTTP")
            # SDK未安装，标记为不可用
            self._sdk_status = "unavailable"
            self._last_sdk_check = current_time
            logger.info(f"[OpenAIBackendRouter] SDK标记为不可用（ImportError）")
        except Exception as e:
            logger.warning(f"OpenAI SDK调用失败，回退到HTTP: {type(e).__name__}: {e}")
            # 其他异常（如网络错误）可能是暂时的，不标记为不可用
            # 但如果是配置错误等持久性问题，可能需要特殊处理
            if "invalid_api_key" in str(e) or "authentication" in str(e).lower():
                # 认证错误可能是持久的，标记为不可用
                self._sdk_status = "unavailable"
                self._last_sdk_check = current_time
                logger.info(f"[OpenAIBackendRouter] SDK标记为不可用（认证错误）")
        
        # 回退到原始 HTTP 请求
        response = await self._handle_with_http(
            actual_model, request_data, stream, support_thinking
        )
        request_time = time.time() - request_start
        logger.info(f"[OpenAIBackendRouter] HTTP回退请求完成，总耗时: {request_time:.3f}秒")
        return response
    
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """将OpenAI响应转换为Ollama格式（使用ResponseConverter）"""
        return self._converter.convert_to_ollama_format(response_data, virtual_model)
    
    async def _ensure_openai_client(self) -> None:
        """确保OpenAI客户端已初始化"""
        if self._openai_client is None:
            try:
                import openai
                # 配置OpenAI客户端
                self._openai_client = openai.AsyncOpenAI(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url.rstrip('/') if self.config.base_url else None,
                    timeout=self.config.timeout,
                    max_retries=getattr(self.config, 'max_retries', 0)
                )
                logger.debug(f"[OpenAIBackendRouter] OpenAI客户端初始化完成，base_url: {self.config.base_url}")
            except ImportError:
                raise ImportError("OpenAI SDK未安装，请运行: pip install openai")
            except Exception as e:
                logger.error(f"[OpenAIBackendRouter] OpenAI客户端初始化失败: {e}")
                raise
    
    def _build_openai_params(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool,
        support_thinking: bool
    ) -> Dict[str, Any]:
        """构建OpenAI SDK调用参数"""
        params = {
            "model": actual_model,
            "messages": request_data.get("messages", []),
            "stream": stream,
            "temperature": request_data.get("temperature"),
            "max_tokens": request_data.get("max_tokens"),
            "max_completion_tokens": request_data.get("max_completion_tokens"),
            "top_p": request_data.get("top_p"),
            "frequency_penalty": request_data.get("frequency_penalty"),
            "presence_penalty": request_data.get("presence_penalty"),
            "stop": request_data.get("stop"),
            "tools": request_data.get("tools"),
            "tool_choice": request_data.get("tool_choice"),
            "parallel_tool_calls": request_data.get("parallel_tool_calls"),
            "functions": request_data.get("functions"),
            "function_call": request_data.get("function_call"),
            "response_format": request_data.get("response_format"),
            "seed": request_data.get("seed"),
            "logprobs": request_data.get("logprobs"),
            "top_logprobs": request_data.get("top_logprobs"),
            "user": request_data.get("user"),
            "logit_bias": request_data.get("logit_bias"),
            "n": request_data.get("n"),
            "stream_options": request_data.get("stream_options"),
            "extra_headers": request_data.get("extra_headers"),
        }
        
        # 移除值为None的项
        params = {k: v for k, v in params.items() if v is not None}
        
        # 添加思考能力支持（如果模型支持）
        if support_thinking:
            # OpenAI SDK可能不支持reasoning参数，通过extra_headers传递
            # 或者让HTTP回退处理
            # 这里我们尝试通过extra_headers传递
            extra_headers = params.get("extra_headers")
            if extra_headers is None:
                params["extra_headers"] = {"reasoning": True}
            elif isinstance(extra_headers, dict):
                params["extra_headers"] = {**extra_headers, "reasoning": True}
            else:
                # 如果不是字典，转换为字典
                params["extra_headers"] = {"reasoning": True}
            # 注意：不添加顶层的reasoning参数，因为OpenAI SDK可能不接受
        
        # 合并配置中的额外参数
        if self.config.litellm_params:
            # 将litellm_params中的参数合并到OpenAI SDK调用
            unsupported_keys = {'max_retries', 'cache', 'timeout'}
            for key, value in self.config.litellm_params.items():
                if key in unsupported_keys:
                    continue
                if key not in params or params[key] is None:
                    params[key] = value
        
        # 移除OpenAI SDK不支持的参数
        unsupported_params = {'max_retries', 'cache', 'timeout'}
        for key in unsupported_params:
            params.pop(key, None)
        
        return params
    
    async def _handle_openai_stream(self, params: Dict[str, Any]) -> StreamingResponse:
        """处理OpenAI SDK流式请求"""
        # 确保客户端已初始化
        await self._ensure_openai_client()

        async def generate():
            assert self._openai_client is not None, "OpenAI客户端未初始化"
            stream_start = time.time()
            
            # 生成日志ID（用于关联流式进度和完成日志）
            log_id = uuid.uuid4().hex
            # 记录输入流（请求数据） - 需要从params中提取原始请求数据
            # 注意：params中可能不包含完整的原始请求数据，这里我们记录params中的关键信息
            # 实际请求数据在调用_handle_openai_stream时已经处理过，但这里我们至少记录模型和消息
            request_data_for_log = {
                "model": params.get('model'),
                "messages": params.get('messages', []),
                "stream": True
            }
            smart_logger.data.record(
                key="input",
                value={
                    "data": request_data_for_log,
                    "summary": f"输入流 - 路由器: OpenAIBackendRouter, 模型: {params.get('model', 'unknown')}",
                    "router": "OpenAIBackendRouter",
                    "model_name": params.get('model', 'unknown'),
                    "stream": True,
                    "log_id": log_id
                }
            )
            
            stream = await self._openai_client.chat.completions.create(**params)  # type: ignore
            # 记录流式开始消息（使用流式日志处理器）
            model_name = params.get('model', 'unknown')
            # 使用智能日志处理器
            smart_logger.process.info(
                f"开始流式请求 (模型: {model_name})",
                router="OpenAIBackendRouter",
                model_name=model_name
            )
            chunk_count = 0
            total_bytes = 0
            spinner_idx = 0
            content_length = None  # OpenAI SDK 不提供内容长度
            first_chunk_time = None
            first_to_all_time = None

            async for chunk in stream:
                # 记录首块响应时间
                if first_chunk_time is None:
                    first_chunk_time = time.time() - stream_start
                    logger.info(f"[{self.__class__.__name__}] 首块响应时间: {first_chunk_time:.3f}秒")

                # 转换为SSE格式
                chunk_json = chunk.model_dump_json()
                chunk_bytes = len(chunk_json.encode('utf-8'))
                chunk_count += 1
                total_bytes += chunk_bytes
                spinner_idx = self._print_stream_progress(
                    chunk_count, total_bytes, content_length, spinner_idx, log_id
                )
                yield f"data: {chunk_json}\n\n"

            # 流式完成
            first_to_all_time = time.time() - (stream_start + first_chunk_time) if first_chunk_time else 0
            logger.info(f"[{self.__class__.__name__}] 首块到全部块接收耗时: {first_to_all_time:.3f}秒")
            self._print_stream_complete(chunk_count, total_bytes, log_id)
            
            # 结束流式会话，组装并打印完整JSON
            if log_id:
                smart_logger.process.info(
                    "流式会话结束",
                    log_id=log_id,
                    event="stream_end"
                )
                
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    
    async def _handle_openai_non_stream(self, params: Dict[str, Any]) -> JSONResponse:
        """处理OpenAI SDK非流式请求"""
        from fastapi.responses import JSONResponse
        # 确保客户端已初始化
        await self._ensure_openai_client()
        
        try:
            response = await self._openai_client.chat.completions.create(**params)  # type: ignore
            return JSONResponse(content=response.model_dump())
        except Exception as e:
            logger.error(f"OpenAI SDK非流式请求失败: {e}")
            raise
    
    async def _handle_with_openai_sdk(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool,
        support_thinking: bool
    ) -> Any:
        """使用OpenAI SDK处理请求"""
        request_start = time.time()
        
        logger.debug(f"[OpenAIBackendRouter._handle_with_openai_sdk] 处理SDK请求")
        logger.debug(f"实际模型: {actual_model}")
        logger.debug(f"流式: {stream}")
        logger.debug(f"支持thinking: {support_thinking}")
        
        # 确保OpenAI客户端已初始化
        await self._ensure_openai_client()
        
        # 构建OpenAI SDK调用参数
        params = self._build_openai_params(actual_model, request_data, stream, support_thinking)
        
        try:
            if stream:
                response = await self._handle_openai_stream(params)
            else:
                response = await self._handle_openai_non_stream(params)
            
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter._handle_with_openai_sdk] SDK请求完成，耗时: {request_time:.3f}秒")
            return response
        except Exception as e:
            request_time = time.time() - request_start
            logger.error(f"[OpenAIBackendRouter._handle_with_openai_sdk] SDK请求失败: {type(e).__name__}: {e} (耗时: {request_time:.3f}秒)")
            # 将OpenAI SDK异常向上抛出，由handle_request方法处理回退
            raise
    
    async def _handle_with_http(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool,
        support_thinking: bool
    ) -> Any:
        """回退到原始 HTTP 请求处理"""
        request_start = time.time()
        
        # 准备请求URL
        endpoint = "chat/completions"
        url = f"{self.config.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        logger.debug(f"[OpenAIBackendRouter._handle_with_http] 开始HTTP回退请求")
        logger.debug(f"URL: {url}")
        
        # 准备转发数据
        forward_data = request_data.copy()
        forward_data["model"] = actual_model
        forward_data["stream"] = stream
        
        # 清理消息中的无效 Unicode 字符
        messages = forward_data.get("messages", [])
        if messages:
            processed_messages = []
            for msg in messages:
                sanitized_msg = sanitize_message(msg)
                
                # 只在模型支持 thinking 时才添加相关字段
                if support_thinking:
                    if sanitized_msg.get("role") == "assistant" and "reasoning_content" not in sanitized_msg:
                        sanitized_msg["reasoning_content"] = ""
                
                processed_messages.append(sanitized_msg)
            forward_data["messages"] = processed_messages
        
        # 只在模型支持 thinking 时才添加 reasoning 字段
        if support_thinking:
            forward_data["reasoning"] = True
        
        # 从ClientPool获取客户端（确保客户端不为None）
        if self._client is None:
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 客户端为None，从ClientPool获取: {self.config.base_url}")
            self._client = await client_pool.get_client(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                timeout=self.config.timeout,
                compression=self.config.compression_enabled
            )
            if self._client is None:
                logger.error(f"[OpenAIBackendRouter._handle_with_http] 无法获取HTTP客户端，client_pool返回None")
                raise HTTPException(status_code=500, detail="无法初始化HTTP客户端")
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 客户端获取成功: {id(self._client)}")
        else:
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 复用现有客户端: {id(self._client)}")
        
        # 准备请求头（流式和非流式共用）
        headers = {**self.config.headers, "Content-Type": "application/json"}
        
        # 处理流式响应
        if stream:
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 开始流式请求")
            
            # 生成日志ID（用于关联流式进度和完成日志）
            log_id = uuid.uuid4().hex
            # 记录输入流（请求数据）
            smart_logger.data.record(
                key="input",
                value={
                    "data": forward_data,
                    "summary": f"输入流 - 路由器: OpenAIBackendRouter, 模型: {actual_model}",
                    "router": "OpenAIBackendRouter",
                    "model_name": actual_model,
                    "stream": True,
                    "log_id": log_id
                }
            )
            
            # 使用基类的通用流式处理方法
            response = await self._handle_stream_request(
                client=self._client,
                url=url,
                headers=headers,
                json_data=forward_data,
                log_id=log_id
            )
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter._handle_with_http] 流式请求完成，耗时: {request_time:.3f}秒")
            return response
        else:
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 开始JSON请求")
            response = await self._handle_json_request(self._client, url, headers, forward_data)
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter._handle_with_http] JSON请求完成，耗时: {request_time:.3f}秒")
            return response