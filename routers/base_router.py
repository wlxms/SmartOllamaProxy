"""
Backend路由器基类
提供统一的接口来处理不同类型的后端请求，提高扩展性
重构版本：使用核心组件减少重复代码，提高性能
"""
import abc
import logging
import sys
import time
import hashlib
from typing import Dict, Any, Optional, AsyncGenerator, Tuple, List
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config_loader import BackendConfig
from client_pool import client_pool
from routers.core.response_converter import ResponseConverter
from routers.core.cache_manager import ToolsCache, PromptCache

# 导入智能日志处理器
from smart_logger import get_smart_logger
smart_logger = get_smart_logger()

logger = logging.getLogger("smart_ollama_proxy.backend_router")


class BackendRouter(abc.ABC):
    """后端路由器抽象基类（重构版）"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        self.config = backend_config
        self.verbose_json_logging = verbose_json_logging
        self.tool_compression_enabled = tool_compression_enabled
        self.prompt_compression_enabled = prompt_compression_enabled
        
        # 核心组件
        self._response_converter = ResponseConverter()
        self._tools_cache = ToolsCache(max_size=100, ttl=300)
        self._prompt_cache = PromptCache(max_size=100, ttl=300)
        
        # HTTP客户端（延迟初始化）
        self._client: Optional[httpx.AsyncClient] = None
        
        # 清理状态跟踪（向后兼容）
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
        if not self.tool_compression_enabled:
            return request_data
        
        # 检查请求中是否有工具
        if "tools" not in request_data or not request_data["tools"]:
            return request_data
        
        # 获取session_id（如果存在）
        session_id = request_data.get("session_id", "default")
        tools = request_data["tools"]
        
        # 使用缓存管理器检查缓存
        cached_tools = self._tools_cache.get_compressed_tools(session_id, tools)
        if cached_tools is not None:
            logger.debug(f"[{self.__class__.__name__}] 工具列表缓存命中，session_id: {session_id}")
            request_data["tools"] = cached_tools
            return request_data
        
        # 压缩工具列表（去重）
        compressed_tools = self._compress_tools(tools)
        
        # 更新缓存
        self._tools_cache.set_compressed_tools(session_id, tools, compressed_tools)
        request_data["tools"] = compressed_tools
        return request_data
    
    def _compress_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """压缩工具列表，去除重复的工具定义"""
        from utils import json
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
    
    def _optimize_prompt(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """优化请求中的提示词，减少重复的基准提示词"""
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
        
        # 检查缓存
        cached_prompt = self._prompt_cache.get_prompt(session_id, benchmark_content)
        if cached_prompt is not None:
            logger.debug(f"[{self.__class__.__name__}] 提示词缓存命中，session_id: {session_id}")
            if self.verbose_json_logging:
                logger.debug(f"[{self.__class__.__name__}] 重复的基准提示词已检测到")
            return request_data
        
        # 更新缓存
        prompt_info = {
            "benchmark_content": benchmark_content,
            "timestamp": time.time()
        }
        self._prompt_cache.set_prompt(session_id, benchmark_content, prompt_info)
        return request_data
    
    async def _handle_stream_request(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        json_data: Dict[str, Any],
        log_id: str = ""
    ) -> StreamingResponse:
        """处理流式请求的通用方法"""
        from utils import json
        
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
                            if log_id:
                                smart_logger.data.record(
                                    key="output_chunk",
                                    value={
                                        "chunk": chunk.decode('utf-8', errors='ignore') if isinstance(chunk, bytes) else chunk,
                                        "summary": f"响应块 - 路由器: {self.__class__.__name__}, 日志ID: {log_id}, 块索引: {chunk_count}",
                                        "router": self.__class__.__name__,
                                        "log_id": log_id,
                                        "chunk_index": chunk_count,
                                        "total_bytes": total_bytes,
                                        "content_length": content_length
                                    }
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
                    if log_id:
                        smart_logger.process.info(
                            f"流式会话结束 - 日志ID: {log_id}",
                            log_id=log_id,
                            event="stream_end"
                        )
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
        from utils import json
        
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
        """打印流式进度信息（使用ProgressBar）"""
        # 格式化字节数
        def format_bytes(bytes_count: int) -> str:
            bytes_float = float(bytes_count)
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_float < 1024.0:
                    return f"{bytes_float:.1f}{unit}"
                bytes_float /= 1024.0
            return f"{bytes_float:.1f}TB"

        formatted_bytes = format_bytes(total_bytes)
        
        # 构建额外信息字符串
        extra_info = f"({formatted_bytes}, 块: {chunk_count})"
        
        # 使用智能日志处理器的进度条功能
        if log_id and hasattr(smart_logger, 'progress'):
            try:
                # 如果content_length已知，使用百分比进度条
                if content_length and content_length > 0:
                    # 创建或获取进度条
                    if not hasattr(self, '_progress_bars'):
                        self._progress_bars = {}
                    
                    if log_id not in self._progress_bars:
                        # 创建新的进度条
                        progress_bar = smart_logger.progress.create(
                            total=content_length,
                            description=f"[{self.__class__.__name__}] 接收中",
                            bar_id=log_id
                        )
                        self._progress_bars[log_id] = progress_bar
                    
                    # 更新进度条
                    progress_bar = self._progress_bars[log_id]
                    if total_bytes > progress_bar.current:
                        progress_bar.update(
                            advance=total_bytes - progress_bar.current,
                            extra_info=extra_info
                        )
                else:
                    # 未知总大小，使用循环进度条
                    if not hasattr(self, '_progress_bars'):
                        self._progress_bars = {}
                    
                    if log_id not in self._progress_bars:
                        # 创建total=0的进度条，触发循环模式
                        progress_bar = smart_logger.progress.create(
                            total=0,  # total=0触发循环模式
                            description=f"[{self.__class__.__name__}] 接收中",
                            bar_id=log_id
                        )
                        self._progress_bars[log_id] = progress_bar
                    
                    # 更新进度条（只更新额外信息，进度条会自动循环）
                    progress_bar = self._progress_bars[log_id]
                    progress_bar.update(advance=0, extra_info=extra_info)
            except Exception as e:
                # 如果进度条功能失败，回退到简单方法
                logger.debug(f"进度条更新失败，回退到简单方法: {e}")
                # 使用简单的单行更新
                spinner = ['|', '/', '-', '\\']
                spinner_char = spinner[spinner_idx % len(spinner)]
                progress_msg = f"\r[{self.__class__.__name__}] {spinner_char} 已接收: {formatted_bytes}, 块: {chunk_count}"
                sys.stdout.write(progress_msg)
                sys.stdout.flush()
                return (spinner_idx + 1) % 4
        
        # 如果没有log_id或进度条功能不可用，使用简单的单行更新
        else:
            if content_length:
                percent = (total_bytes / content_length) * 100
                progress_msg = f"\r[{self.__class__.__name__}] 进度: {percent:.1f}% {extra_info}"
            else:
                # 使用spinner显示进度
                spinner = ['|', '/', '-', '\\']
                spinner_char = spinner[spinner_idx % len(spinner)]
                progress_msg = f"\r[{self.__class__.__name__}] {spinner_char} 已接收: {formatted_bytes}, 块: {chunk_count}"
            
            sys.stdout.write(progress_msg)
            sys.stdout.flush()
        
        return (spinner_idx + 1) % 4 if not content_length else 0

    def _print_stream_complete(self, chunk_count: int, total_bytes: int, log_id: str = ""):
        """打印流式完成信息（使用ProgressBar）"""
        # 关闭进度条（如果存在）
        if log_id and hasattr(self, '_progress_bars') and log_id in self._progress_bars:
            try:
                progress_bar = self._progress_bars.pop(log_id)
                progress_bar.close()
            except Exception as e:
                logger.debug(f"关闭进度条失败: {e}")
        
        def format_bytes(bytes_count: int) -> str:
            bytes_float = float(bytes_count)
            for unit in ['B', 'KB', 'MB', 'GB']:
                if bytes_float < 1024.0:
                    return f"{bytes_float:.1f}{unit}"
                bytes_float /= 1024.0
            return f"{bytes_float:.1f}TB"

        formatted_bytes = format_bytes(total_bytes)
        complete_msg = f"\r[{self.__class__.__name__}] 流式完成 ✓ 总块数: {chunk_count}, 总字节: {formatted_bytes}                          \n"
        
        # 1. 使用智能日志处理器记录（如果可用）
        if log_id:
            smart_logger.performance.record(
                key="stream_complete",
                value={
                    "metric": "stream_complete",
                    "value": total_bytes,
                    "unit": "bytes",
                    "router": self.__class__.__name__,
                    "log_id": log_id,
                    "chunk_count": chunk_count,
                    "total_bytes": total_bytes
                }
            )
        
        # 2. 保持原有的控制台输出（向后兼容）
        if not log_id:
            sys.stdout.write(complete_msg)
            sys.stdout.flush()
    
    # ==================== 新增辅助方法 ====================
    
    def _get_http_client(self) -> httpx.AsyncClient:
        """获取HTTP客户端（从client_pool获取）"""
        if self._client is None:
            # 延迟初始化，由子类实现
            raise NotImplementedError("子类需要实现HTTP客户端获取逻辑")
        return self._client
    
    def _convert_to_ollama_format_default(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """默认的Ollama格式转换实现（使用ResponseConverter）"""
        return self._response_converter.convert_to_ollama_format(response_data, virtual_model)
    
    def _cleanup_caches(self):
        """清理所有缓存（向后兼容）"""
        self._tools_cache.cleanup()
        self._prompt_cache.cleanup()
        self._last_tools_cleanup = time.time()
        self._last_prompt_cleanup = time.time()
    
    # ==================== 向后兼容的方法 ====================
    
    # 注意：_cleanup_tools_cache 和 _cleanup_prompt_cache 已移除，
    # 请使用 _cleanup_caches 方法或直接访问 self._tools_cache.cleanup()