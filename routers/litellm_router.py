"""
LiteLLM后端路由器
专门用于LiteLLM配置，直接使用LiteLLM SDK处理请求
重构版：使用基类组件减少重复代码
"""
import logging
import time
import uuid
from typing import Dict, Any
from utils import json, sanitize_message

from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import HTTPException

from config_loader import BackendConfig
from .base_router import BackendRouter
from routers.core.response_converter import ResponseConverter

# 导入智能日志处理器
from smart_logger import get_smart_logger
smart_logger = get_smart_logger()

logger = logging.getLogger("smart_ollama_proxy.backend_router")


class LiteLLMRouter(BackendRouter):
    """LiteLLM后端路由器（专门用于LiteLLM配置，重构版）"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config, verbose_json_logging,  # type: ignore
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        # JSON转换方法缓存优化（保留性能优化）
        self._chunk_conversion_cache = {}  # chunk_type -> conversion_method_index
        self._response_conversion_cache = {}  # response_type -> conversion_method_index
        self._conversion_stats = {}  # method_name -> success/failure counts
        
        # 响应转换器
        self._converter = ResponseConverter()
    
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理LiteLLM请求"""
        request_start = time.time()
        
        logger.debug(f"[LiteLLMRouter] 处理请求")
        logger.debug(f"实际模型: {actual_model}")
        logger.debug(f"流式: {stream}")
        logger.debug(f"支持thinking: {support_thinking}")
        
        # 优化工具列表和提示词（复用基类方法）
        request_data = self._optimize_tools_in_request(request_data)
        request_data = self._optimize_prompt(request_data)
        
        # 处理消息中的 thinking 支持（确保 assistant 消息包含 reasoning_content 字段）
        request_data = self._process_messages_for_thinking(request_data, support_thinking)
        
        # 构建 LiteLLM 参数
        params = self._build_litellm_params(actual_model, request_data, stream, support_thinking)
        
        # 设置 API 密钥和基础地址（从配置继承）
        if self.config.api_key:
            params["api_key"] = self.config.api_key
        if self.config.base_url:
            params["api_base"] = self.config.base_url
        
        try:
            import litellm
            if stream:
                # 流式处理
                async def generate():
                    # 进度显示初始化
                    spinner_idx = 0
                    chunk_count = 0
                    total_bytes = 0

                    try:
                        stream_start = time.time()
                        
                        # 生成日志ID（用于关联流式进度和完成日志）
                        log_id = uuid.uuid4().hex
                        # 记录输入流（请求数据）
                        smart_logger.data.record(
                            key="input",
                            value={
                                "data": request_data,
                                "summary": f"输入流 - 路由器: LiteLLM, 模型: {actual_model}",
                                "router": "LiteLLM",
                                "model_name": actual_model,
                                "stream": True,
                                "log_id": log_id
                            }
                        )
                        
                        stream_response = await litellm.acompletion(**params)

                        # 记录流式开始消息（使用智能日志处理器）
                        smart_logger.process.info(
                            f"开始流式请求 (模型: {actual_model})",
                            router="LiteLLM",
                            model_name=actual_model
                        )

                        first_chunk_time = None
                        content_length = None  # LiteLLM SDK 不提供内容长度

                        async for chunk in stream_response:  # type: ignore
                            # 记录首块响应时间
                            if first_chunk_time is None:
                                first_chunk_time = time.time() - stream_start
                                logger.info(f"[{self.__class__.__name__}] 首块响应时间: {first_chunk_time:.3f}秒")

                            chunk_count += 1

                            # 安全地将chunk转换为字典，处理StreamingChoices等特殊类型
                            chunk_dict = self._safe_chunk_to_dict(chunk)

                            # 计算JSON字符串的字节数
                            chunk_json = json.dumps(chunk_dict)
                            chunk_bytes = len(chunk_json.encode('utf-8'))
                            total_bytes += chunk_bytes

                            # 使用基类的进度显示方法
                            spinner_idx = self._print_stream_progress(
                                chunk_count, total_bytes, content_length, spinner_idx, log_id
                            )

                            # 转换为 SSE 格式
                            yield f"data: {chunk_json}\n\n"

                        # 流式完成
                        first_to_all_time = time.time() - (stream_start + first_chunk_time) if first_chunk_time else 0
                        logger.info(f"[{self.__class__.__name__}] 首块到全部块接收耗时: {first_to_all_time:.3f}秒")
                        
                        # 使用基类的完成显示方法
                        self._print_stream_complete(chunk_count, total_bytes, log_id)
                        
                        # 记录流式完成（使用智能日志处理器）
                        if log_id:
                            smart_logger.performance.record(
                                key="stream_complete",
                                value={
                                    "metric": "stream_complete",
                                    "value": total_bytes,
                                    "unit": "bytes",
                                    "router": "LiteLLM",
                                    "log_id": log_id,
                                    "chunk_count": chunk_count,
                                    "total_bytes": total_bytes
                                }
                            )
                            # 结束流式会话，组装并打印完整JSON
                            smart_logger.process.info(
                                "流式会话结束",
                                log_id=log_id,
                                event="stream_end"
                            )
                        
                        yield "data: [DONE]\n\n"
                    except Exception as e:
                        # 记录错误状态，包含已接收的数据统计
                        if chunk_count > 0:
                            # 格式化字节数显示
                            def format_bytes(bytes_count: float) -> str:
                                """格式化字节数为易读格式"""
                                for unit in ['B', 'KB', 'MB', 'GB']:
                                    if bytes_count < 1024.0:
                                        return f"{bytes_count:.1f}{unit}"
                                    bytes_count /= 1024.0
                                return f"{bytes_count:.1f}TB"
                            
                            formatted_bytes = format_bytes(total_bytes)
                            error_msg = f"流式失败 ✗ 错误: {type(e).__name__}, 已接收: {chunk_count}块, {formatted_bytes}"
                        else:
                            error_msg = f"流式失败 ✗ 错误: {type(e).__name__}"
                        
                        # 记录错误日志（使用智能日志处理器）
                        smart_logger.process.error(
                            error_msg,
                            router="LiteLLM",
                            model_name=actual_model
                        )
                        
                        # 保持控制台输出（向后兼容）
                        import sys
                        if chunk_count > 0:
                            sys.stdout.write(f"\r[LiteLLM] {error_msg}                      \n")
                        else:
                            sys.stdout.write(f"\r[LiteLLM] {error_msg}                      \n")
                        sys.stdout.flush()
                        
                        logger.error(f"LiteLLM 流式请求失败: {e}")
                        error_data = json.dumps({"error": str(e)})
                        yield f"data: {error_data}\n\n"
                
                request_time = time.time() - request_start
                logger.info(f"[LiteLLMRouter] LiteLLM流式请求完成，耗时: {request_time:.3f}秒")
                return StreamingResponse(generate(), media_type="text/event-stream")
            else:
                # 非流式处理
                response = await litellm.acompletion(**params)
                request_time = time.time() - request_start
                logger.info(f"[LiteLLMRouter] LiteLLM非流式请求完成，耗时: {request_time:.3f}秒")
                # 安全地将响应转换为字典
                response_dict = self._safe_response_to_dict(response)
                return JSONResponse(content=response_dict)
        except Exception as e:
            logger.error(f"LiteLLM 请求失败: {e}")
            raise HTTPException(status_code=500, detail=f"LiteLLM请求失败: {str(e)}")
    
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """将OpenAI响应转换为Ollama格式（使用ResponseConverter）"""
        return self._converter.convert_to_ollama_format(response_data, virtual_model)
    
    def _build_litellm_params(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool,
        support_thinking: bool
    ) -> Dict[str, Any]:
        """构建 LiteLLM 调用参数"""
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
            "safety_identifier": request_data.get("safety_identifier"),
            "reasoning_effort": request_data.get("reasoning_effort"),
            "extra_headers": request_data.get("extra_headers"),
        }
        
        # 移除值为 None 的项
        params = {k: v for k, v in params.items() if v is not None}
        
        # 添加思考能力支持
        if support_thinking:
            params["reasoning"] = True
        
        # 合并配置中的额外参数
        if self.config.litellm_params:
            params.update(self.config.litellm_params)
        
        # 为LiteLLM格式化模型名称（添加提供商前缀）
        params["model"] = self._format_model_for_litellm(actual_model)
        
        return params
    
    def _process_messages_for_thinking(self, request_data: Dict[str, Any], support_thinking: bool) -> Dict[str, Any]:
        """处理消息中的 thinking 支持，确保 assistant 消息包含 reasoning_content 字段
        
        根据 Deepseek API 文档，当使用 thinking 模式时，assistant 消息必须包含 reasoning_content 字段。
        即使字段为空字符串，也需要存在以避免 "Missing `reasoning_content` field" 错误。
        
        Args:
            request_data: 请求数据字典
            support_thinking: 是否支持 thinking 能力
            
        Returns:
             处理后的请求数据
        """
        if not support_thinking:
            return request_data
        
        # 检查请求中是否有消息
        if "messages" not in request_data or not request_data["messages"]:
            return request_data
        
        messages = request_data.get("messages", [])
        if messages:
            processed_messages = []
            for msg in messages:
                # 清理消息中的无效 Unicode 字符
                sanitized_msg = sanitize_message(msg)
                
                # 只在模型支持 thinking 时才添加相关字段
                if support_thinking:
                    if sanitized_msg.get("role") == "assistant" and "reasoning_content" not in sanitized_msg:
                        sanitized_msg["reasoning_content"] = ""
                
                processed_messages.append(sanitized_msg)
            request_data["messages"] = processed_messages
        
        return request_data
    
    def _format_model_for_litellm(self, model_name: str) -> str:
        """为LiteLLM格式化模型名称，添加提供商前缀
        
        LiteLLM要求模型名称格式为 'provider/model-name'，例如:
        - deepseek/deepseek-reasoner
        - openai/gpt-4o
        - anthropic/claude-3-5-sonnet
        
        注意：这里使用模型组名作为provider，而不是解析域名
        
        Args:
            model_name: 原始模型名称
            
        Returns:
            格式化的模型名称
        """
        # 获取模型组名 - 从配置的base_url推断
        # 注意：更好的方法是在BackendConfig中添加model_group字段
        base_url = self.config.base_url.lower()
        
        # 根据base_url推断模型组/提供商
        provider = self._infer_provider_from_url(base_url)
        
        # 格式化模型名称
        if provider and not model_name.startswith(f"{provider}/"):
            # 添加提供商前缀
            return f"{provider}/{model_name}"
        else:
            # 已经包含前缀或无法推断提供商，返回原始名称
            return model_name
    
    def _infer_provider_from_url(self, base_url: str) -> str:
        """从base_url推断LiteLLM提供商名称
        
        使用模型组名而不是解析域名
        """
        # 常见API端点的映射
        url_to_provider = {
            "api.deepseek.com": "deepseek",
            "api.openai.com": "openai", 
            "api.anthropic.com": "anthropic",
            "api.groq.com": "groq",
            "dashscope.aliyuncs.com": "alibabacloud",
            "siliconflow.cn": "siliconflow",
            "api.siliconflow.cn": "siliconflow",
        }
        
        # 检查完全匹配
        for url_pattern, provider in url_to_provider.items():
            if url_pattern in base_url:
                return provider
        
        # 如果没有匹配，尝试从backend_mode推断
        # backend_mode格式如 "litellm_backend"，但我们想要模型组名
        # 实际上需要模型组名如 "deepseek"，这信息应该在配置中
        # 这里作为临时方案，尝试从base_url提取
        try:
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            domain = parsed.netloc
            
            # 移除端口和www前缀
            if ":" in domain:
                domain = domain.split(":")[0]
            if domain.startswith("www."):
                domain = domain[4:]
            
            # 取主域名部分作为provider
            domain_parts = domain.split(".")
            if len(domain_parts) >= 2:
                # 使用倒数第二部分，如 "deepseek" from "api.deepseek.com"
                return domain_parts[-2]
            else:
                return domain
        except:
            # 如果无法推断，返回空字符串
            return ""
    
    def _safe_chunk_to_dict(self, chunk: Any) -> Dict[str, Any]:
        """将LiteLLM流式chunk转换为字典（简化版，无多方法回退）"""
        # 如果已经是字典，直接返回
        if isinstance(chunk, dict):
            return chunk
        
        # 尝试常用转换方法
        if hasattr(chunk, 'to_dict'):
            return chunk.to_dict()
        if hasattr(chunk, 'dict'):
            return chunk.dict()
        if hasattr(chunk, 'model_dump'):
            return chunk.model_dump()
        
        # 最后尝试vars
        try:
            return vars(chunk)
        except TypeError:
            # 如果vars失败，使用字符串表示
            logger.warning(f"无法转换chunk为字典: {type(chunk).__name__}")
            return {"_type": type(chunk).__name__, "_repr": str(chunk)}
    
    def _safe_response_to_dict(self, response: Any) -> Dict[str, Any]:
        """将LiteLLM响应转换为字典（简化版，无多方法回退）"""
        # 如果已经是字典，直接返回
        if isinstance(response, dict):
            return response
        
        # 尝试常用转换方法
        if hasattr(response, 'to_dict'):
            return response.to_dict()
        if hasattr(response, 'dict'):
            return response.dict()
        if hasattr(response, 'model_dump'):
            return response.model_dump()
        
        # 最后尝试vars
        try:
            return vars(response)
        except TypeError:
            # 如果vars失败，使用字符串表示
            logger.warning(f"无法转换响应为字典: {type(response).__name__}")
            return {"_type": type(response).__name__, "_repr": str(response)}