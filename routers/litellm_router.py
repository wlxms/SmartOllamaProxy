"""
LiteLLM后端路由器
专门用于LiteLLM配置，直接使用LiteLLM SDK处理请求
"""
import logging
import time
from typing import Dict, Any
from utils import json, sanitize_message

from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import HTTPException

from config_loader import BackendConfig
from .base_router import BackendRouter

# 导入流式日志处理器
try:
    from stream_logger import get_stream_logger
    STREAM_LOGGER_AVAILABLE = True
except ImportError:
    STREAM_LOGGER_AVAILABLE = False
    get_stream_logger = None

logger = logging.getLogger("smart_ollama_proxy.backend_router")


class LiteLLMRouter(BackendRouter):
    """LiteLLM后端路由器（专门用于LiteLLM配置）"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config, verbose_json_logging,
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        # 不再自己创建client，改为从ClientPool获取
        self._client_key = (self.config.base_url.rstrip('/'), self.config.api_key)
        # JSON转换方法缓存优化
        self._chunk_conversion_cache = {}  # chunk_type -> conversion_method_index
        self._response_conversion_cache = {}  # response_type -> conversion_method_index
        self._conversion_stats = {}  # method_name -> success/failure counts
    
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
                    spinner = ['|', '/', '-', '\\']
                    spinner_idx = 0
                    chunk_count = 0
                    total_bytes = 0

                    # 字节数格式化函数
                    def format_bytes(bytes_count: float) -> str:
                        """格式化字节数为易读格式"""
                        for unit in ['B', 'KB', 'MB', 'GB']:
                            if bytes_count < 1024.0:
                                return f"{bytes_count:.1f}{unit}"
                            bytes_count /= 1024.0
                        return f"{bytes_count:.1f}TB"

                    try:
                        stream_start = time.time()
                        
                        # 生成日志ID（用于关联流式进度和完成日志）
                        log_id = ""
                        if STREAM_LOGGER_AVAILABLE and get_stream_logger is not None:
                            stream_logger = get_stream_logger()
                            log_id = stream_logger._generate_log_id()
                        
                        stream_response = await litellm.acompletion(**params)

                        # 记录流式开始消息（使用流式日志处理器）
                        if STREAM_LOGGER_AVAILABLE and get_stream_logger is not None:
                            stream_logger = get_stream_logger()
                            stream_logger.log_debug_print(
                                message=f"开始流式请求 (模型: {actual_model})",
                                router_name="LiteLLM",
                                model_name=actual_model
                            )
                        else:
                            # 回退到标准日志输出（向后兼容）
                            logger.info(f"[LiteLLM] 开始流式请求 (模型: {actual_model})")

                        first_chunk_time = None

                        async for chunk in stream_response:  # type: ignore
                            # 记录首块响应时间
                            if first_chunk_time is None:
                                first_chunk_time = time.time() - stream_start
                                logger.info(f"[{self.__class__.__name__}] 首块响应时间: {first_chunk_time:.3f}秒")

                            # 更新进度显示
                            spinner_idx = (spinner_idx + 1) % len(spinner)
                            chunk_count += 1

                            # 安全地将chunk转换为字典，处理StreamingChoices等特殊类型
                            chunk_dict = self._safe_chunk_to_dict(chunk)

                            # 计算JSON字符串的字节数
                            chunk_json = json.dumps(chunk_dict)
                            chunk_bytes = len(chunk_json.encode('utf-8'))
                            total_bytes += chunk_bytes

                            # 格式化字节数显示
                            formatted_bytes = format_bytes(total_bytes)

                            # 记录流式进度（使用流式日志处理器）
                            if STREAM_LOGGER_AVAILABLE and get_stream_logger is not None and log_id:
                                stream_logger = get_stream_logger()
                                stream_logger.log_stream_progress(
                                    log_id=log_id,
                                    router_name="LiteLLM",
                                    chunk_count=chunk_count,
                                    total_bytes=total_bytes,
                                    content_length=None,  # LiteLLM不提供内容长度
                                    spinner_idx=spinner_idx
                                )
                            
                            # 保持控制台输出（向后兼容）
                            if not STREAM_LOGGER_AVAILABLE or not log_id:
                                # 使用sys.stdout.write来保持进度条效果
                                import sys
                                sys.stdout.write(f"\r[LiteLLM] 流式进度 {spinner[spinner_idx]} 已接收块: {chunk_count}, 字节: {formatted_bytes}")
                                sys.stdout.flush()

                            # 转换为 SSE 格式
                            yield f"data: {chunk_json}\n\n"

                        # 流式完成
                        first_to_all_time = time.time() - (stream_start + first_chunk_time) if first_chunk_time else 0
                        logger.info(f"[{self.__class__.__name__}] 首块到全部块接收耗时: {first_to_all_time:.3f}秒")
                        formatted_total_bytes = format_bytes(total_bytes)
                        
                        # 记录流式完成（使用流式日志处理器）
                        if STREAM_LOGGER_AVAILABLE and get_stream_logger is not None and log_id:
                            stream_logger = get_stream_logger()
                            stream_logger.log_stream_complete(
                                log_id=log_id,
                                router_name="LiteLLM",
                                chunk_count=chunk_count,
                                total_bytes=total_bytes
                            )
                        
                        # 保持控制台输出（向后兼容）
                        if not STREAM_LOGGER_AVAILABLE or not log_id:
                            # 使用sys.stdout.write来保持进度条效果
                            import sys
                            sys.stdout.write(f"\r[LiteLLM] 流式完成 ✓ 总块数: {chunk_count}, 总字节: {formatted_total_bytes}                          \n")
                            sys.stdout.flush()
                        elif STREAM_LOGGER_AVAILABLE and log_id:
                            # 如果使用流式日志处理器，仍然需要换行来分隔输出
                            import sys
                            sys.stdout.write("\n")
                            sys.stdout.flush()
                        yield "data: [DONE]\n\n"
                    except Exception as e:
                        # 记录错误状态，包含已接收的数据统计
                        if chunk_count > 0:
                            formatted_bytes = format_bytes(total_bytes)
                            error_msg = f"流式失败 ✗ 错误: {type(e).__name__}, 已接收: {chunk_count}块, {formatted_bytes}"
                        else:
                            error_msg = f"流式失败 ✗ 错误: {type(e).__name__}"
                        
                        # 记录错误日志（使用流式日志处理器）
                        if STREAM_LOGGER_AVAILABLE and get_stream_logger is not None:
                            stream_logger = get_stream_logger()
                            stream_logger.log_debug_print(
                                message=error_msg,
                                router_name="LiteLLM",
                                model_name=actual_model
                            )
                        
                        # 保持控制台输出（向后兼容）
                        if not STREAM_LOGGER_AVAILABLE or not get_stream_logger:
                            import sys
                            if chunk_count > 0:
                                sys.stdout.write(f"\r[LiteLLM] {error_msg}                      \n")
                            else:
                                sys.stdout.write(f"\r[LiteLLM] {error_msg}                      \n")
                            sys.stdout.flush()
                        else:
                            import sys
                            sys.stdout.write("\n")
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
    
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """将OpenAI响应转换为Ollama格式"""
        if isinstance(response_data, dict):
            openai_result = response_data
        elif hasattr(response_data, 'body'):
            # JSONResponse对象
            body = response_data.body
            if isinstance(body, bytes):
                openai_result = json.loads(body.decode())
            else:
                openai_result = body
        else:
            raise ValueError(f"无法处理的响应类型: {type(response_data)}")
        
        # 转换为Ollama格式
        ollama_result = {
            "model": virtual_model,
            "response": openai_result["choices"][0]["message"]["content"],
            "done": True,
            "total_duration": openai_result.get("usage", {}).get("total_tokens", 0) * 50_000_000,
        }
        return ollama_result
    
    def _safe_chunk_to_dict(self, chunk: Any) -> Dict[str, Any]:
        """安全地将LiteLLM流式chunk转换为字典，带有方法缓存优化
        
        LiteLLM返回的chunk可能包含不可JSON序列化的对象，如StreamingChoices。
        此方法尝试多种方式转换为可序列化的字典，并缓存每种chunk类型最有效的转换方法。
        """
        try:
            # 如果chunk已经是字典，直接返回（最快路径）
            if isinstance(chunk, dict):
                return chunk
            
            # 获取chunk类型名称用于缓存
            chunk_type = type(chunk).__name__
            
            # 检查是否有缓存的转换方法
            cached_method_idx = self._chunk_conversion_cache.get(chunk_type)
            if cached_method_idx is not None:
                # 尝试使用缓存的转换方法
                conversion_methods = self._get_conversion_methods()
                method_name, method_func = conversion_methods[cached_method_idx]
                try:
                    result = method_func(chunk)
                    # 更新成功统计
                    self._conversion_stats[method_name] = self._conversion_stats.get(method_name, 0) + 1
                    return result
                except (TypeError, ValueError, AttributeError):
                    # 缓存的转换方法失败，从缓存中移除并继续尝试其他方法
                    del self._chunk_conversion_cache[chunk_type]
                    logger.debug(f"缓存的转换方法 {method_name} 失败，重新检测最佳方法")
            
            # 获取转换方法列表（按优先级排序）
            conversion_methods = self._get_conversion_methods()
            
            # 尝试每个转换方法
            for idx, (method_name, method_func) in enumerate(conversion_methods):
                try:
                    # 特殊处理：lambda返回None表示方法不适用（如缺少属性）
                    if method_name == "to_dict":
                        if not hasattr(chunk, 'to_dict'):
                            continue
                    elif method_name == "pydantic_dict":
                        if not hasattr(chunk, 'dict'):
                            continue
                    
                    result = method_func(chunk)
                    # 缓存成功的转换方法
                    self._chunk_conversion_cache[chunk_type] = idx
                    # 更新统计
                    self._conversion_stats[method_name] = self._conversion_stats.get(method_name, 0) + 1
                    logger.debug(f"为 {chunk_type} 缓存转换方法: {method_name}")
                    return result
                except (TypeError, ValueError, AttributeError):
                    # 当前方法失败，继续尝试下一个
                    continue
            
            # 所有方法都失败，使用后备方案
            logger.warning(f"所有转换方法都失败，使用后备方案，chunk类型: {chunk_type}")
            return self._fallback_chunk_conversion(chunk)
                
        except Exception as e:
            logger.error(f"安全转换chunk失败: {e}")
            return {"_error": f"转换失败: {str(e)}"}
    
    def _get_conversion_methods(self):
        """获取转换方法列表（按优先级排序）"""
        return [
            ("to_dict", lambda c: c.to_dict()),
            ("dict", lambda c: dict(c)),
            ("pydantic_dict", lambda c: c.dict()),
            ("vars", lambda c: vars(c)),
            ("json_parse", self._convert_via_json_string),
        ]
    
    def _convert_via_json_string(self, chunk: Any) -> Dict[str, Any]:
        """通过JSON字符串转换chunk（后备方法）"""
        import json as json_module
        # 先转换为字符串，然后解析回字典
        str_repr = str(chunk)
        # 尝试解析为JSON，如果失败则创建简单字典
        try:
            return json_module.loads(str_repr)
        except:
            # 创建包含基本信息的字典
            return {"_type": type(chunk).__name__, "_repr": str_repr}
    
    def _fallback_chunk_conversion(self, chunk: Any) -> Dict[str, Any]:
        """chunk转换的后备方案，当所有方法都失败时使用"""
        logger.warning(f"无法转换chunk为字典: chunk类型: {type(chunk).__name__}")
        # 返回最小化信息字典
        return {"_error": "无法序列化chunk", "_type": type(chunk).__name__}
    
    def _safe_response_to_dict(self, response: Any) -> Dict[str, Any]:
        """安全地将LiteLLM响应转换为字典，带有方法缓存优化"""
        try:
            # 如果响应已经是字典，直接返回（最快路径）
            if isinstance(response, dict):
                return response
            
            # 获取响应类型名称用于缓存
            response_type = type(response).__name__
            
            # 检查是否有缓存的转换方法
            cached_method_idx = self._response_conversion_cache.get(response_type)
            if cached_method_idx is not None:
                # 尝试使用缓存的转换方法
                conversion_methods = self._get_conversion_methods()
                method_name, method_func = conversion_methods[cached_method_idx]
                try:
                    result = method_func(response)
                    # 更新成功统计
                    self._conversion_stats[method_name] = self._conversion_stats.get(method_name, 0) + 1
                    return result
                except (TypeError, ValueError, AttributeError):
                    # 缓存的转换方法失败，从缓存中移除并继续尝试其他方法
                    del self._response_conversion_cache[response_type]
                    logger.debug(f"缓存的响应转换方法 {method_name} 失败，重新检测最佳方法")
            
            # 获取转换方法列表（按优先级排序）
            conversion_methods = self._get_conversion_methods()
            
            # 尝试每个转换方法
            for idx, (method_name, method_func) in enumerate(conversion_methods):
                try:
                    # 特殊处理：lambda返回None表示方法不适用（如缺少属性）
                    if method_name == "to_dict":
                        if not hasattr(response, 'to_dict'):
                            continue
                    elif method_name == "pydantic_dict":
                        if not hasattr(response, 'dict'):
                            continue
                    
                    result = method_func(response)
                    # 缓存成功的转换方法
                    self._response_conversion_cache[response_type] = idx
                    # 更新统计
                    self._conversion_stats[method_name] = self._conversion_stats.get(method_name, 0) + 1
                    logger.debug(f"为响应 {response_type} 缓存转换方法: {method_name}")
                    return result
                except (TypeError, ValueError, AttributeError):
                    # 当前方法失败，继续尝试下一个
                    continue
            
            # 所有方法都失败，使用后备方案
            logger.warning(f"所有响应转换方法都失败，使用字符串表示，响应类型: {response_type}")
            return {"_type": response_type, "_repr": str(response)}
                
        except Exception as e:
            logger.error(f"安全转换响应失败: {e}")
            return {"_error": f"转换失败: {str(e)}"}