"""
Backend路由器基类
提供统一的接口来处理不同类型的后端请求，提高扩展性
"""
import abc
from utils import json, sanitize_unicode_string, sanitize_message
import logging
import sys
from typing import Dict, Any, Optional, AsyncGenerator, Tuple, List
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config_loader import BackendConfig
from client_pool import client_pool

# 导入流式日志处理器
try:
    from stream_logger import get_stream_logger
    STREAM_LOGGER_AVAILABLE = True
except ImportError:
    STREAM_LOGGER_AVAILABLE = False
    get_stream_logger = None

logger = logging.getLogger("smart_ollama_proxy.backend_router")





class BackendRouter(abc.ABC):
    """后端路由器抽象基类"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        self.config = backend_config
        self.verbose_json_logging = verbose_json_logging
        self.tool_compression_enabled = tool_compression_enabled
        self.prompt_compression_enabled = prompt_compression_enabled
        self._client: Optional[httpx.AsyncClient] = None  # 客户端实例，由子类初始化
        # 增强工具列表缓存：session_id -> (tools_hash, compressed_tools, timestamp)
        self._tools_cache: Dict[str, Tuple[str, List[Dict[str, Any]], float]] = {}
        # 提示词压缩缓存：session_id -> {"benchmark_hash": str, "benchmark_content": str, "timestamp": float}
        self._prompt_cache: Dict[str, Dict[str, Any]] = {}
        # 缓存配置
        self._cache_config = {
            "tools_ttl": 300,  # 工具缓存TTL（秒）
            "prompt_ttl": 300,  # 提示词缓存TTL（秒）
            "max_cache_size": 100,  # 最大缓存条目数
            "cleanup_interval": 30,  # 清理间隔（秒）
        }
        # 清理状态跟踪
        self._last_tools_cleanup: float = 0.0
        self._last_prompt_cleanup: float = 0.0
    
    @abc.abstractmethod
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理请求的抽象方法"""
        pass
    
    @abc.abstractmethod
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """将响应转换为Ollama格式的抽象方法"""
        pass
    
    def _optimize_tools_in_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """优化请求中的工具列表，减少重复的工具定义"""
        import hashlib
        import time
        
        if not self.tool_compression_enabled:
            return request_data
        
        # 检查请求中是否有工具
        if "tools" not in request_data or not request_data["tools"]:
            return request_data
        
        # 获取session_id（如果存在）
        session_id = request_data.get("session_id", "default")
        
        # 计算工具列表的哈希值
        tools = request_data["tools"]
        tools_str = json.dumps(tools, sort_keys=True)
        tools_hash = hashlib.md5(tools_str.encode()).hexdigest()
        
        # 检查缓存
        current_time = time.time()
        if session_id in self._tools_cache:
            cached_hash, compressed_tools, timestamp = self._tools_cache[session_id]
            
            # 检查缓存是否过期
            if current_time - timestamp < self._cache_config["tools_ttl"] and cached_hash == tools_hash:
                logger.debug(f"[{self.__class__.__name__}] 工具列表缓存命中，session_id: {session_id}")
                request_data["tools"] = compressed_tools
                return request_data
        
        # 压缩工具列表（去重）
        compressed_tools = self._compress_tools(tools)
        
        # 更新缓存
        self._tools_cache[session_id] = (tools_hash, compressed_tools, current_time)
        
        # 清理过期缓存
        self._cleanup_tools_cache()
        
        request_data["tools"] = compressed_tools
        return request_data
    
    def _compress_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """压缩工具列表，去除重复的工具定义"""
        seen_tools = {}
        compressed = []
        
        for tool in tools:
            # 提取工具签名（名称+参数）
            tool_name = tool.get("function", {}).get("name", "")
            params = tool.get("function", {}).get("parameters", {})
            
            # 创建工具签名
            signature = json.dumps({"name": tool_name, "parameters": params}, sort_keys=True)
            
            if signature not in seen_tools:
                seen_tools[signature] = True
                compressed.append(tool)
        
        if len(compressed) < len(tools):
            logger.debug(f"[{self.__class__.__name__}] 工具列表压缩: {len(tools)} -> {len(compressed)}")
        
        return compressed
    
    def _cleanup_tools_cache(self, force: bool = False):
        """清理过期的工具缓存，支持条件清理
        
        Args:
            force: 是否强制清理（忽略时间间隔）
        """
        import time
        current_time = time.time()
        
        # 检查是否需要清理：超过最大缓存大小、强制清理、或超过清理间隔
        needs_cleanup = force or len(self._tools_cache) > self._cache_config["max_cache_size"]
        if not needs_cleanup and current_time - self._last_tools_cleanup < self._cache_config["cleanup_interval"]:
            return
        
        # 更新最后清理时间
        self._last_tools_cleanup = current_time
        
        # 清理过期条目
        expired_sessions = []
        for session_id, (_, _, timestamp) in self._tools_cache.items():
            if current_time - timestamp >= self._cache_config["tools_ttl"]:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self._tools_cache[session_id]
        
        # 如果缓存过大，清理最旧的条目
        if len(self._tools_cache) > self._cache_config["max_cache_size"]:
            # 按时间排序
            sorted_sessions = sorted(
                self._tools_cache.items(),
                key=lambda x: x[1][2]  # 按时间戳排序
            )
            # 删除最旧的条目直到达到最大大小
            for session_id, _ in sorted_sessions[:len(self._tools_cache) - self._cache_config["max_cache_size"]]:
                del self._tools_cache[session_id]
    
    def _optimize_prompt(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """优化请求中的提示词，减少重复的基准提示词"""
        import hashlib
        import time
        
        if not self.prompt_compression_enabled:
            return request_data
        
        # 检查请求中是否有消息
        if "messages" not in request_data or not request_data["messages"]:
            return request_data
        
        # 获取session_id（如果存在）
        session_id = request_data.get("session_id", "default")
        
        # 查找基准提示词（通常是第一条system消息）
        messages = request_data["messages"]
        if not messages or messages[0].get("role") != "system":
            return request_data
        
        benchmark_message = messages[0]
        benchmark_content = benchmark_message.get("content", "")
        if not benchmark_content:
            return request_data
        
        # 计算基准提示词的哈希值
        benchmark_hash = hashlib.md5(benchmark_content.encode()).hexdigest()
        
        # 检查缓存
        current_time = time.time()
        if session_id in self._prompt_cache:
            cached_data = self._prompt_cache[session_id]
            if (current_time - cached_data["timestamp"] < self._cache_config["prompt_ttl"] and 
                cached_data["benchmark_hash"] == benchmark_hash):
                logger.debug(f"[{self.__class__.__name__}] 提示词缓存命中，session_id: {session_id}")
                
                # 如果基准提示词相同，可以替换为简化的版本
                # 这里我们保留原内容，但可以在日志中标记
                if self.verbose_json_logging:
                    logger.debug(f"[{self.__class__.__name__}] 重复的基准提示词已检测到，hash: {benchmark_hash}")
                
                return request_data
        
        # 更新缓存
        self._prompt_cache[session_id] = {
            "benchmark_hash": benchmark_hash,
            "benchmark_content": benchmark_content,
            "timestamp": current_time
        }
        
        # 清理过期缓存
        self._cleanup_prompt_cache()
        
        return request_data
    
    def _cleanup_prompt_cache(self, force: bool = False):
        """清理过期的提示词缓存，支持条件清理
        
        Args:
            force: 是否强制清理（忽略时间间隔）
        """
        import time
        current_time = time.time()
        
        # 检查是否需要清理：超过最大缓存大小、强制清理、或超过清理间隔
        needs_cleanup = force or len(self._prompt_cache) > self._cache_config["max_cache_size"]
        if not needs_cleanup and current_time - self._last_prompt_cleanup < self._cache_config["cleanup_interval"]:
            return
        
        # 更新最后清理时间
        self._last_prompt_cleanup = current_time
        
        # 清理过期条目
        expired_sessions = []
        for session_id, cache_data in self._prompt_cache.items():
            if current_time - cache_data["timestamp"] >= self._cache_config["prompt_ttl"]:
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            del self._prompt_cache[session_id]
        
        # 如果缓存过大，清理最旧的条目
        if len(self._prompt_cache) > self._cache_config["max_cache_size"]:
            # 按时间排序
            sorted_sessions = sorted(
                self._prompt_cache.items(),
                key=lambda x: x[1]["timestamp"]  # 按时间戳排序
            )
            # 删除最旧的条目直到达到最大大小
            for session_id, _ in sorted_sessions[:len(self._prompt_cache) - self._cache_config["max_cache_size"]]:
                del self._prompt_cache[session_id]
    
    async def _handle_stream_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        json_data: Dict[str, Any],
        log_id: str = ""
    ) -> StreamingResponse:
        """处理流式请求的通用方法"""
        import time

        stream_start = time.time()
        logger.debug(f"[{self.__class__.__name__}._handle_stream_request] 开始流式请求: {url}")
        
        # 详细的JSON日志记录（如果启用）
        if self.verbose_json_logging:
            logger.debug(f"[{self.__class__.__name__}._handle_stream_request] 请求URL: {url}")
            logger.debug(f"[{self.__class__.__name__}._handle_stream_request] 请求头: {headers}")
            logger.debug(f"[{self.__class__.__name__}._handle_stream_request] 请求数据: {json.dumps(json_data, ensure_ascii=False, indent=2)}")

        async def generate():
            try:
                async with client.stream("POST", url, headers=headers, json=json_data) as response:
                    response.raise_for_status()
                    content_length = response.headers.get('content-length')
                    if content_length:
                        content_length = int(content_length)
                    else:
                        content_length = None
                    chunk_count = 0
                    total_bytes = 0
                    spinner_idx = 0
                    first_chunk_time = None

                    async for chunk in response.aiter_bytes():
                        if chunk:
                            # 记录首块响应时间
                            if first_chunk_time is None:
                                first_chunk_time = time.time() - stream_start
                                logger.info(f"[{self.__class__.__name__}] 首块响应时间: {first_chunk_time:.3f}秒")

                            chunk_count += 1
                            total_bytes += len(chunk)
                            spinner_idx = self._print_stream_progress(
                                chunk_count, total_bytes, content_length, spinner_idx, log_id
                            )
                            
                             # 记录输出流chunk（如果启用了流式日志）
                            if STREAM_LOGGER_AVAILABLE and log_id and get_stream_logger is not None:
                                stream_logger = get_stream_logger()
                                stream_logger.log_output_stream(
                                    chunk=chunk,
                                    log_id=log_id,
                                    router_name=self.__class__.__name__,
                                    chunk_index=chunk_count,
                                    total_bytes=total_bytes,
                                    content_length=content_length
                                )
                            
                            # 不再打印每个chunk的详细JSON日志，使用stream_logger记录完整响应
                            
                            yield chunk

                    # 流式完成
                    first_to_all_time = time.time() - (stream_start + first_chunk_time) if first_chunk_time else 0
                    logger.info(f"[{self.__class__.__name__}] 首块到全部块接收耗时: {first_to_all_time:.3f}秒")
                    self._print_stream_complete(chunk_count, total_bytes, log_id)
                    
                    # 详细的JSON日志记录总结（如果启用）
                    if self.verbose_json_logging:
                        logger.debug(f"[{self.__class__.__name__}._handle_stream_request] 流式请求完成 - 总块数: {chunk_count}, 总字节: {total_bytes}")
                    
                    # 结束流式会话，组装并打印完整JSON
                    if STREAM_LOGGER_AVAILABLE and log_id and get_stream_logger is not None:
                        stream_logger = get_stream_logger()
                        stream_logger.end_stream(log_id)
            except Exception as e:
                logger.error(f"[{self.__class__.__name__}._handle_stream_request] 流式请求失败: {e}")
                error_data = json.dumps({"error": str(e)})
                yield f"data: {error_data}\n\n".encode()

        stream_time = time.time() - stream_start
        logger.info(f"[{self.__class__.__name__}._handle_stream_request] 流式请求初始化完成，耗时: {stream_time:.3f}秒")

        return StreamingResponse(generate(), media_type="text/event-stream")
    
    async def _handle_json_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        json_data: Dict[str, Any]
    ) -> JSONResponse:
        """处理JSON请求的通用方法"""
        import time
        
        json_start = time.time()
        logger.debug(f"[{self.__class__.__name__}._handle_json_request] 开始JSON请求: {url}")
        
        try:
            response = await client.post(url, headers=headers, json=json_data)
            response.raise_for_status()
            response_data = response.json()
            
            json_time = time.time() - json_start
            logger.info(f"[{self.__class__.__name__}._handle_json_request] JSON请求完成，耗时: {json_time:.3f}秒")
            
            # 详细的JSON日志记录（如果启用）
            if self.verbose_json_logging:
                logger.debug(f"[{self.__class__.__name__}._handle_json_request] 请求URL: {url}")
                logger.debug(f"[{self.__class__.__name__}._handle_json_request] 请求头: {headers}")
                logger.debug(f"[{self.__class__.__name__}._handle_json_request] 请求数据: {json.dumps(json_data, ensure_ascii=False, indent=2)}")
                logger.debug(f"[{self.__class__.__name__}._handle_json_request] 响应数据: {json.dumps(response_data, ensure_ascii=False, indent=2)}")
            else:
                logger.debug(f"[{self.__class__.__name__}._handle_json_request] 响应数据已接收，详细JSON日志已禁用")
            
            total_time = time.time() - json_start
            logger.info(f"[{self.__class__.__name__}._handle_json_request] JSON请求总耗时: {total_time:.3f}秒")
            
            return JSONResponse(content=response_data)
        except Exception as e:
            total_time = time.time() - json_start
            logger.error(f"[{self.__class__.__name__}._handle_json_request] JSON请求失败: {e} (耗时: {total_time:.3f}秒)")
            raise HTTPException(status_code=500, detail=str(e))
    
    def _print_stream_progress(self, chunk_count: int, total_bytes: int,
                               content_length: Optional[int] = None,
                               spinner_idx: int = 0, log_id: str = "") -> int:
        """打印流式进度信息"""
        spinner = ['|', '/', '-', '\\']
        spinner_char = spinner[spinner_idx % len(spinner)]

        def format_bytes(bytes_count: int) -> str:
            bytes_float = float(bytes_count)
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_float < 1024.0:
                    return f"{bytes_float:.1f}{unit}"
                bytes_float /= 1024.0
            return f"{bytes_float:.1f}TB"

        formatted_bytes = format_bytes(total_bytes)

        if content_length:
            percent = (total_bytes / content_length) * 100
            progress_msg = f"\r[{self.__class__.__name__}] 进度: {percent:.1f}% ({total_bytes}/{content_length} 字节) 块 #{chunk_count}"
        else:
            progress_msg = f"\r[{self.__class__.__name__}] {spinner_char} 已接收: {formatted_bytes}, 块 #{chunk_count}"

        # 1. 使用流式日志处理器记录（如果可用） - 但log_stream_progress已改为空操作，不记录日志
        if STREAM_LOGGER_AVAILABLE and log_id and get_stream_logger is not None:
            stream_logger = get_stream_logger()
            stream_logger.log_stream_progress(
                log_id=log_id,
                router_name=self.__class__.__name__,
                chunk_count=chunk_count,
                total_bytes=total_bytes,
                content_length=content_length,
                spinner_idx=spinner_idx
            )
        
        # 2. 总是输出控制台进度显示（保留前台进度）
        sys.stdout.write(progress_msg)
        sys.stdout.flush()

        return (spinner_idx + 1) % len(spinner)

    def _print_stream_complete(self, chunk_count: int, total_bytes: int, log_id: str = ""):
        """打印流式完成信息"""
        def format_bytes(bytes_count: int) -> str:
            bytes_float = float(bytes_count)
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_float < 1024.0:
                    return f"{bytes_float:.1f}{unit}"
                bytes_float /= 1024.0
            return f"{bytes_float:.1f}TB"

        formatted_bytes = format_bytes(total_bytes)
        complete_msg = f"\r[{self.__class__.__name__}] 流式完成 ✓ 总块数: {chunk_count}, 总字节: {formatted_bytes}                          \n"
        
        # 1. 使用流式日志处理器记录（如果可用）
        if STREAM_LOGGER_AVAILABLE and log_id and get_stream_logger is not None:
            stream_logger = get_stream_logger()
            stream_logger.log_stream_complete(
                log_id=log_id,
                router_name=self.__class__.__name__,
                chunk_count=chunk_count,
                total_bytes=total_bytes
            )
        
        # 2. 保持原有的控制台输出（向后兼容）
        # 只有在流式日志处理器不可用或未启用时，才输出到控制台
        if not STREAM_LOGGER_AVAILABLE or not log_id:
            sys.stdout.write(complete_msg)
            sys.stdout.flush()