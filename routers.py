"""
Backend路由模式类
提供统一的接口来处理不同类型的后端请求，提高扩展性
"""
import abc
from utils import json
import logging
import sys
from typing import Dict, Any, Optional, AsyncGenerator, Tuple, List
import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config_loader import BackendConfig
from client_pool import client_pool

logger = logging.getLogger("smart_ollama_proxy.backend_router")


def sanitize_unicode_string(text: str) -> str:
    """
    清理字符串中的无效 Unicode 代理对，避免 JSON 序列化错误
    
    Args:
        text: 需要清理的字符串
        
    Returns:
        清理后的字符串
    """
    if not isinstance(text, str):
        return text
    
    try:
        # 尝试编码为 UTF-8，如果失败则替换无效字符
        text.encode('utf-8', errors='strict')
        return text
    except UnicodeEncodeError:
        # 如果包含无效字符，使用 replace 策略替换
        return text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')


def sanitize_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    """
    清理消息中的 Unicode 字符，确保可以正确序列化为 JSON
    
    Args:
        msg: 消息字典
        
    Returns:
        清理后的消息字典
    """
    sanitized_msg = msg.copy()
    
    # 清理 content 字段
    if "content" in sanitized_msg and isinstance(sanitized_msg["content"], str):
        sanitized_msg["content"] = sanitize_unicode_string(sanitized_msg["content"])
    
    # 清理 reasoning_content 字段（如果存在）
    if "reasoning_content" in sanitized_msg and isinstance(sanitized_msg["reasoning_content"], str):
        sanitized_msg["reasoning_content"] = sanitize_unicode_string(sanitized_msg["reasoning_content"])
    
    return sanitized_msg


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
        self._max_cache_size = 200  # 增加缓存大小
        self._cache_cleanup_interval = 300  # 5分钟
        self._last_cache_cleanup = 0
        self._cache_hits: int = 0
        self._cache_misses: int = 0
    
    def _extract_session_id(self, request_data: Dict[str, Any]) -> str:
        """从请求数据中提取或生成会话ID"""
        import hashlib
        import time
        import random
        
        # 尝试从消息中提取会话标识
        messages = request_data.get("messages", [])
        if messages:
            # 使用第一条消息的内容生成会话ID
            first_message = messages[0] if messages else {}
            content = first_message.get("content", "")
            if content:
                # 使用消息内容的前100个字符生成哈希
                content_hash = hashlib.md5(content[:100].encode()).hexdigest()[:8]
                return f"session_{content_hash}"
        
        # 如果没有消息，使用时间戳和随机数
        timestamp = int(time.time() * 1000)
        random_suffix = random.randint(1000, 9999)
        return f"temp_{timestamp}_{random_suffix}"

    def _optimize_prompt(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        优化请求中的重复提示词（从内容头开始比对与基准内容，将重复部分替换为标记）
        
        算法：
        1. 每个会话维护一个基准提示词（benchmark）
        2. 将当前提示词与基准提示词比较，计算公共前缀
        3. 如果公共前缀长度大于阈值（50字符），则压缩重复部分
        4. 如果公共前缀长度小于阈值，则将当前提示词设为新的基准（不压缩）
        5. 更新缓存
        
        Args:
            request_data: 原始请求数据
            
        Returns:
            优化后的请求数据
        """
        import hashlib
        import time
        
        if not self.prompt_compression_enabled:
            return request_data
        
        # 提取或生成会话ID
        session_id = self._extract_session_id(request_data)
        
        # 获取消息列表
        messages = request_data.get("messages", [])
        if not messages:
            return request_data
        
        # 只处理最后一条用户消息（假设重复内容在连续请求中）
        last_message = messages[-1]
        if last_message.get("role") != "user":
            return request_data
        
        content = last_message.get("content", "")
        if not content:
            return request_data
        
        # 检查缓存中是否有该会话的基准提示词
        cached_entry = self._prompt_cache.get(session_id)
        current_time = time.time()
        content_hash = hashlib.md5(content.encode()).hexdigest()[:12]
        
        if not cached_entry:
            # 首次请求，将当前提示词设为基准
            self._prompt_cache[session_id] = {
                "benchmark_hash": content_hash,
                "benchmark_content": content,
                "timestamp": current_time
            }
            logger.info(f"提示词压缩: 会话 {session_id[:8]} 初始化基准，长度 {len(content)}")
            return request_data
        
        # 获取基准提示词
        benchmark_hash = cached_entry["benchmark_hash"]
        benchmark_content = cached_entry["benchmark_content"]
        timestamp = cached_entry["timestamp"]
        
        # 如果当前内容与基准完全相同，无需压缩
        if content_hash == benchmark_hash:
            # 缓存命中，内容完全相同，跳过压缩
            logger.info(f"提示词压缩: 会话 {session_id[:8]} 内容完全相同，跳过压缩 (长度 {len(content)})")
            # 更新时间戳
            self._prompt_cache[session_id]["timestamp"] = current_time
            return request_data
        
        # 计算与基准的公共前缀
        common_prefix = self._find_common_prefix(benchmark_content, content)
        common_prefix_len = len(common_prefix)
        
        # 设置阈值（可配置，暂定50字符）
        threshold = 50
        
        if common_prefix_len >= threshold:
            # 重复部分足够长，进行压缩
            # 替换重复部分为标记
            compressed_content = f"<开头{common_prefix[:30]}....末尾{common_prefix[-30:]}>" + content[common_prefix_len:]
            # 更新消息内容
            last_message["content"] = compressed_content
            # 计算压缩率
            original_len = len(content)
            compressed_len = len(compressed_content)
            compression_ratio = common_prefix_len / original_len if original_len > 0 else 0
            logger.info(f"提示词压缩: 会话 {session_id[:8]} 重复前缀长度 {common_prefix_len} 已替换为标记 (基准长度 {len(benchmark_content)}), 原始长度 {original_len}, 压缩后长度 {compressed_len}, 压缩率 {compression_ratio:.2%}")
            # 保持基准不变
            self._prompt_cache[session_id]["timestamp"] = current_time
        else:
            # 重复部分太少，将当前提示词设为新的基准
            self._prompt_cache[session_id] = {
                "benchmark_hash": content_hash,
                "benchmark_content": content,
                "timestamp": current_time
            }
            logger.info(f"提示词压缩: 会话 {session_id[:8]} 更新基准，重复前缀长度 {common_prefix_len} 小于阈值 {threshold}")
        
        # 清理过期缓存
        self._cleanup_prompt_cache()
        
        return request_data
    
    def _find_common_prefix(self, str1: str, str2: str) -> str:
        """查找两个字符串的公共前缀"""
        min_len = min(len(str1), len(str2))
        for i in range(min_len):
            if str1[i] != str2[i]:
                return str1[:i]
        return str1[:min_len]
    
    def _cleanup_prompt_cache(self):
        """清理提示词缓存，避免内存泄漏"""
        import time
        current_time = time.time()
        
        # 定期清理（每5分钟）
        if current_time - self._last_cache_cleanup > self._cache_cleanup_interval:
            ttl = 3600  # 1小时
            keys_to_remove = []
            for key, entry in self._prompt_cache.items():
                timestamp = entry.get("timestamp", 0)
                if current_time - timestamp > ttl:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._prompt_cache[key]
            
            if keys_to_remove:
                logger.debug(f"清理了 {len(keys_to_remove)} 个过期提示词缓存条目")
            
            # 如果缓存仍然超过最大大小，清理最旧的条目
            if len(self._prompt_cache) > self._max_cache_size:
                sorted_keys = sorted(
                    self._prompt_cache.items(),
                    key=lambda x: x[1].get("timestamp", 0)  # 按timestamp排序
                )
                keys_to_remove = [k for k, _ in sorted_keys[:self._max_cache_size // 2]]
                for key in keys_to_remove:
                    del self._prompt_cache[key]
                logger.debug(f"清理了 {len(keys_to_remove)} 个最旧提示词缓存条目")
            
            self._last_cache_cleanup = current_time



    def _optimize_tools_in_request(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        优化请求中的工具列表（检测重复并压缩）
        
        Args:
            request_data: 原始请求数据
            
        Returns:
            优化后的请求数据
        """
        if not self.tool_compression_enabled:
            return request_data
        import hashlib
        
        if "tools" in request_data and isinstance(request_data["tools"], list):
            tools = request_data["tools"]
            if tools:
                # 提取或生成会话ID
                session_id = self._extract_session_id(request_data)
                
                # 计算工具列表的哈希值
                tools_json = json.dumps(tools, sort_keys=True, ensure_ascii=False)
                tools_hash = hashlib.md5(tools_json.encode()).hexdigest()[:12]
                
                # 检查缓存中是否有该会话的相同工具列表
                cached_entry = self._tools_cache.get(session_id)
                if cached_entry and cached_entry[0] == tools_hash:
                    # 使用缓存的压缩工具列表
                    cached_hash, compressed_tools, timestamp = cached_entry
                    self._cache_hits += 1
                    logger.info(f"检测到会话 {session_id[:8]} 的重复工具列表（哈希: {tools_hash}），使用缓存压缩版本 (命中: {self._cache_hits})")
                    request_data["tools"] = compressed_tools
                else:
                    # 创建压缩版本并缓存
                    compressed_tools = self._compress_tools(tools)
                    import time
                    self._tools_cache[session_id] = (tools_hash, compressed_tools, time.time())
                    self._cache_misses += 1
                    
                    # 清理过期缓存
                    self._cleanup_tools_cache()
                    
                    logger.info(f"会话 {session_id[:8]} 的新工具列表（哈希: {tools_hash}），已缓存压缩版本 (未命中: {self._cache_misses})")
                    request_data["tools"] = compressed_tools
        
        return request_data
    
    def _compress_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """压缩工具列表，减少Token消耗但保持结构有效性"""
        compressed_tools = []
        for tool in tools:
            if isinstance(tool, dict):
                compressed_tool = {
                    "type": tool.get("type", ""),
                    "name": tool.get("name", "")[:50]  # 限制名称长度
                }
                # 如果是function类型，保留必要信息但简化
                if tool.get("type") == "function" and "function" in tool:
                    func = tool["function"]
                    compressed_function = {
                        "name": func.get("name", "")[:50],
                        "description": func.get("description", "")[:100] if func.get("description") else ""
                    }
                    
                    # 处理parameters字段 - 保持结构但简化内容
                    if "parameters" in func:
                        params = func["parameters"]
                        if isinstance(params, dict):
                            # 保持基本结构，但简化properties
                            compressed_params = {
                                "type": params.get("type", "object"),
                                "properties": {}  # 空对象，但保持类型正确
                            }
                            # 如果需要，可以添加required字段
                            if "required" in params and isinstance(params["required"], list):
                                compressed_params["required"] = params["required"][:5]  # 只保留前5个
                            
                            compressed_function["parameters"] = compressed_params
                        else:
                            compressed_function["parameters"] = params
                    
                    compressed_tool["function"] = compressed_function
                
                compressed_tools.append(compressed_tool)
            else:
                compressed_tools.append(tool)
        
        return compressed_tools
    
    def _cleanup_tools_cache(self):
        """清理工具列表缓存，避免内存泄漏"""
        import time
        current_time = time.time()
        
        # 定期清理（每5分钟）
        if current_time - self._last_cache_cleanup > self._cache_cleanup_interval:
            # 清理过期条目（超过1小时）
            ttl = 3600  # 1小时
            keys_to_remove = []
            for key, (_, _, timestamp) in self._tools_cache.items():
                if current_time - timestamp > ttl:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                del self._tools_cache[key]
            
            if keys_to_remove:
                logger.debug(f"清理了 {len(keys_to_remove)} 个过期工具列表缓存条目")
            
            # 如果缓存仍然超过最大大小，清理最旧的条目
            if len(self._tools_cache) > self._max_cache_size:
                # 按时间戳排序，清理最旧的
                sorted_keys = sorted(
                    self._tools_cache.items(),
                    key=lambda x: x[1][2]  # 按timestamp排序
                )
                keys_to_remove = [k for k, _ in sorted_keys[:self._max_cache_size // 2]]
                for key in keys_to_remove:
                    del self._tools_cache[key]
                logger.debug(f"清理了 {len(keys_to_remove)} 个最旧工具列表缓存条目")
            
            # 记录缓存统计
            cache_size = len(self._tools_cache)
            hit_rate = self._cache_hits / (self._cache_hits + self._cache_misses) if (self._cache_hits + self._cache_misses) > 0 else 0
            logger.debug(f"工具缓存统计: 大小={cache_size}, 命中率={hit_rate:.2%}, 命中={self._cache_hits}, 未命中={self._cache_misses}")
            
            self._last_cache_cleanup = current_time

    @abc.abstractmethod
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """
        处理请求
        
        Args:
            actual_model: 实际模型名称
            request_data: 请求数据
            stream: 是否流式
            
        Returns:
            响应数据
        """
        pass
    
    @abc.abstractmethod
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """
        将后端响应转换为Ollama格式
        
        Args:
            response_data: 后端响应数据
            virtual_model: 虚拟模型名称
            
        Returns:
            Ollama格式的响应
        """
        pass
    
    async def _handle_stream_generic(
        self,
        url: str,
        data: Dict[str, Any],
        headers: Dict[str, str],
        media_type: str = "text/event-stream",
        is_sse_format: bool = True,
        chunk_end_marker: bytes = b'\n\n'
    ) -> StreamingResponse:
        """
        通用的流式请求处理方法（优化版）
        
        Args:
            url: 请求URL
            data: 请求数据
            headers: 请求头
            media_type: 媒体类型
            is_sse_format: 是否为SSE格式（data:前缀）
            chunk_end_marker: 块结束标记
            
        Returns:
            StreamingResponse对象
        """
        import time
        
        stream_start = time.time()
        chunk_count = 0
        
        async def generic_stream():
            nonlocal chunk_count
            try:
                logger.debug(f"[{self.__class__.__name__}] 开始通用流式请求（优化版）")
                connect_start = time.time()
                
                # 优化JSON序列化 - 使用更高效的参数
                try:
                    json_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
                except (UnicodeEncodeError, ValueError) as e:
                    logger.warning(f"流式请求 JSON 序列化失败，尝试清理数据: {e}")
                    # 如果序列化失败，尝试清理数据后重试
                    cleaned_data = self._clean_request_data(data)
                    json_data = json.dumps(cleaned_data, ensure_ascii=False, separators=(',', ':'))
                
                # 确保客户端已初始化
                if not hasattr(self, '_client') or self._client is None:
                    logger.error(f"[{self.__class__.__name__}] HTTP客户端未初始化")
                    error_data = json.dumps({"error": "HTTP客户端未初始化"})
                    if is_sse_format:
                        yield f"data: {error_data}\n\n".encode('utf-8')
                    else:
                        yield error_data.encode('utf-8')
                    return
                
                # 使用客户端发送请求
                async with self._client.stream(
                    "POST",
                    url,
                    content=json_data.encode('utf-8'),
                    headers=headers
                ) as response:
                    connect_time = time.time() - connect_start
                    logger.info(f"[{self.__class__.__name__}] 连接建立耗时: {connect_time:.3f}秒")
                    logger.debug(f"[{self.__class__.__name__}] 响应状态码: {response.status_code}")
                    
                    if response.status_code != 200:
                        error_text = await response.aread()
                        logger.error(f"[{self.__class__.__name__}] 错误响应: {error_text.decode()}")
                        error_data = json.dumps({'error': error_text.decode()})
                        if is_sse_format:
                            yield f"data: {error_data}\n\n".encode('utf-8')
                        else:
                            yield error_data.encode('utf-8')
                        return
                    
                    first_chunk_time = None
                    chunk_count = 0
                    max_buffer_size = self.config.stream_buffer_size  # 保留用于日志记录，但不再用于缓冲
                    log_frequency = self.config.stream_log_frequency
                    
                    # 进度显示变量
                    total_bytes_received = 0
                    content_length = response.headers.get('content-length')
                    if content_length:
                        content_length = int(content_length)
                    else:
                        content_length = None
                    spin_chars = ['-', '\\', '|', '/']
                    spin_index = 0
                    
                    # 使用 aiter_bytes() 以提高性能
                    async for chunk in response.aiter_bytes():
                        if first_chunk_time is None:
                            first_chunk_time = time.time() - stream_start
                            logger.info(f"[{self.__class__.__name__}] 首块响应时间: {first_chunk_time:.3f}秒")
                        
                        # 直接转发数据块，不进行缓冲
                        chunk_count += 1
                        total_bytes_received += len(chunk)
                        spin_char = spin_chars[spin_index % len(spin_chars)]
                        spin_index += 1
                        
                        # 进度显示（不写入日志，仅控制台输出）
                        if content_length:
                            percent = (total_bytes_received / content_length) * 100
                            progress_msg = f"\r[{self.__class__.__name__}] 进度: {percent:.1f}% ({total_bytes_received}/{content_length} 字节) 块 #{chunk_count}"
                        else:
                            progress_msg = f"\r[{self.__class__.__name__}] {spin_char} 已接收: {total_bytes_received} 字节, 块 #{chunk_count}"
                        sys.stdout.write(progress_msg)
                        sys.stdout.flush()
                        
                        if chunk_count <= 3 or chunk_count % log_frequency == 0:
                            logger.debug(f"[{self.__class__.__name__}] 转发数据块 #{chunk_count}, 大小: {len(chunk)}字节")
                        
                        yield chunk
                    
                    # 流式传输完成，清除进度行
                    sys.stdout.write('\n')
                    sys.stdout.flush()
                    
                    # 注意：循环结束后没有需要发送的剩余缓冲区
                    
                    total_time = time.time() - stream_start
                    logger.info(f"[{self.__class__.__name__}] 流式响应完成，总块数: {chunk_count}, 总耗时: {total_time:.3f}秒")
            except Exception as e:
                total_time = time.time() - stream_start
                logger.error(f"[{self.__class__.__name__}] 流式请求失败: {e} (耗时: {total_time:.3f}秒)")
                error_data = json.dumps({"error": str(e)})
                if is_sse_format:
                    yield f"data: {error_data}\n\n".encode('utf-8')
                else:
                    yield error_data.encode('utf-8')
        
        return StreamingResponse(generic_stream(), media_type=media_type)
    
    
    def _clean_request_data(self, data: Any) -> Any:
        '''
        清理请求数据中的无效Unicode字符，确保可以正确序列化为JSON
        
        Args:
            data: 需要清理的数据（可以是dict、list、str等）
            
        Returns:
            清理后的数据
        '''
        if isinstance(data, dict):
            # 深度清理字典
            cleaned_dict = {}
            for key, value in data.items():
                cleaned_key = self._clean_request_data(key)
                cleaned_value = self._clean_request_data(value)
                cleaned_dict[cleaned_key] = cleaned_value
            return cleaned_dict
        elif isinstance(data, list):
            # 深度清理列表
            return [self._clean_request_data(item) for item in data]
        elif isinstance(data, str):
            # 清理字符串
            return sanitize_unicode_string(data)
        else:
            # 其他类型直接返回
            return data
    
    async def _handle_json_request(self, url: str, data: Dict[str, Any]) -> JSONResponse:
        """处理JSON请求"""
        import time
        json_start = time.time()
        
        try:
            logger.debug(f"[{self.__class__.__name__}._handle_json_request] 开始HTTP JSON请求")
            
            # 确保客户端已初始化
            if self._client is None:
                logger.error(f"[{self.__class__.__name__}._handle_json_request] HTTP客户端未初始化")
                raise HTTPException(status_code=500, detail="HTTP客户端未初始化")
            
            # 优化JSON序列化 - 使用更高效的参数
            try:
                json_data = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            except (UnicodeEncodeError, ValueError) as e:
                logger.warning(f"JSON 序列化失败，尝试清理数据: {e}")
                # 如果序列化失败，尝试清理数据后重试
                cleaned_data = self._clean_request_data(data)
                json_data = json.dumps(cleaned_data, ensure_ascii=False, separators=(',', ':'))
            
            # 使用从ClientPool获取的客户端（性能优化），使用 content 而不是 json 参数
            response = await self._client.post(
                url,
                content=json_data.encode('utf-8'),
                headers={**self.config.headers, "Content-Type": "application/json"}
            )
            request_time = time.time() - json_start
            
            logger.info(f"[{self.__class__.__name__}._handle_json_request] HTTP请求完成，耗时: {request_time:.3f}秒")
            logger.debug(f"[{self.__class__.__name__}._handle_json_request] 响应状态码: {response.status_code}")
            logger.debug(f"[{self.__class__.__name__}._handle_json_request] 响应头: {dict(response.headers)}")
            
            if response.status_code != 200:
                error_text = response.text
                logger.error(f"[{self.__class__.__name__}._handle_json_request] 错误响应: {error_text}")
                raise HTTPException(status_code=response.status_code, detail=error_text)
            
            response_data = response.json()
            
            # 记录响应数据（截断长内容）
            if self.verbose_json_logging:
                response_preview = json.dumps(response_data, ensure_ascii=False, indent=2)
                if len(response_preview) > 2000:
                    response_preview = response_preview[:2000] + "\n... (响应内容过长，已截断)"
                logger.debug(f"[{self.__class__.__name__}._handle_json_request] 响应数据:")
                logger.debug(response_preview)
            else:
                logger.debug(f"[{self.__class__.__name__}._handle_json_request] 响应数据已接收，详细JSON日志已禁用")
            
            total_time = time.time() - json_start
            logger.info(f"[{self.__class__.__name__}._handle_json_request] JSON请求总耗时: {total_time:.3f}秒")
            
            return JSONResponse(content=response_data)
        except Exception as e:
            total_time = time.time() - json_start
            logger.error(f"[{self.__class__.__name__}._handle_json_request] JSON请求失败: {e} (耗时: {total_time:.3f}秒)")
            raise HTTPException(status_code=500, detail=str(e))

class OpenAIBackendRouter(BackendRouter):
    """OpenAI兼容后端路由器"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config, verbose_json_logging,
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        # 不再自己创建client，改为从ClientPool获取
        self._client_key = (self.config.base_url.rstrip('/'), self.config.api_key)
    
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
        
        # 尝试使用 OpenAI SDK
        try:
            response = await self._handle_with_openai_sdk(
                actual_model, request_data, stream, support_thinking
            )
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter] OpenAI SDK请求完成，耗时: {request_time:.3f}秒")
            return response
        except ImportError:
            logger.warning("OpenAI SDK包未安装，回退到HTTP")
            # 继续执行HTTP回退逻辑
        except Exception as e:
            logger.warning(f"OpenAI SDK调用失败，回退到HTTP: {type(e).__name__}: {e}")
            # 继续执行HTTP回退逻辑
        
        # 回退到原始 HTTP 请求
        response = await self._handle_with_http(
            actual_model, request_data, stream, support_thinking
        )
        request_time = time.time() - request_start
        logger.info(f"[OpenAIBackendRouter] HTTP回退请求完成，总耗时: {request_time:.3f}秒")
        return response
    
    # _handle_stream_request 方法已移除，使用基类的 _handle_stream_generic 方法替代
    
    # _handle_json_request 方法使用基类的实现
    

    
    # 工具压缩相关方法已移至基类，这里不再重复定义
    




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
            # OpenAI SDK目前通过extra_headers传递reasoning参数
            # 这里使用DeepSeek等兼容参数
            params["reasoning"] = True
        
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
            try:
                assert self._openai_client is not None, "OpenAI客户端未初始化"
                stream = await self._openai_client.chat.completions.create(**params)  # type: ignore
                async for chunk in stream:
                    # 转换为SSE格式
                    yield f"data: {chunk.model_dump_json()}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"OpenAI SDK流式请求失败: {e}")
                error_data = json.dumps({"error": str(e)})
                yield f"data: {error_data}\n\n"
        
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
        import time
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
        import time
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
                timeout=self.config.timeout
            )
            if self._client is None:
                logger.error(f"[OpenAIBackendRouter._handle_with_http] 无法获取HTTP客户端，client_pool返回None")
                raise HTTPException(status_code=500, detail="无法初始化HTTP客户端")
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 客户端获取成功: {id(self._client)}")
        else:
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 复用现有客户端: {id(self._client)}")
        
        # 处理流式响应
        if stream:
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 开始流式请求")
            # 准备请求头
            headers = {**self.config.headers, "Content-Type": "application/json"}
            # 使用基类的通用流式处理方法
            response = await self._handle_stream_generic(
                url=url,
                data=forward_data,
                headers=headers,
                media_type="text/event-stream",
                is_sse_format=True,
                chunk_end_marker=b'\n\n'
            )
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter._handle_with_http] 流式请求完成，耗时: {request_time:.3f}秒")
            return response
        else:
            logger.debug(f"[OpenAIBackendRouter._handle_with_http] 开始JSON请求")
            response = await self._handle_json_request(url, forward_data)
            request_time = time.time() - request_start
            logger.info(f"[OpenAIBackendRouter._handle_with_http] JSON请求完成，耗时: {request_time:.3f}秒")
            return response
    

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


class LiteLLMRouter(BackendRouter):
    """LiteLLM后端路由器（专门用于LiteLLM配置）"""
    
    def __init__(self, backend_config: BackendConfig, verbose_json_logging: bool = False,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config, verbose_json_logging,
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        # 不再自己创建client，改为从ClientPool获取
        self._client_key = (self.config.base_url.rstrip('/'), self.config.api_key)
        # OpenAI客户端将在第一次请求时初始化
        self._openai_client = None
    
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理LiteLLM请求"""
        import time
        import litellm
        
        request_start = time.time()
        
        logger.debug(f"[LiteLLMRouter] 处理请求")
        logger.debug(f"实际模型: {actual_model}")
        logger.debug(f"流式: {stream}")
        logger.debug(f"支持thinking: {support_thinking}")
        
        # 优化工具列表和提示词（复用基类方法）
        request_data = self._optimize_tools_in_request(request_data)
        request_data = self._optimize_prompt(request_data)
        
        # 构建 LiteLLM 参数
        params = self._build_litellm_params(actual_model, request_data, stream, support_thinking)
        
        # 设置 API 密钥和基础地址（从配置继承）
        if self.config.api_key:
            params["api_key"] = self.config.api_key
        if self.config.base_url:
            params["api_base"] = self.config.base_url
        
        try:
            if stream:
                # 流式处理
                async def generate():
                    try:
                        stream_response = await litellm.acompletion(**params)
                        async for chunk in stream_response:  # type: ignore
                            # 转换为 SSE 格式
                            yield f"data: {json.dumps(dict(chunk))}\n\n"
                        yield "data: [DONE]\n\n"
                    except Exception as e:
                        logger.error(f"LiteLLM 流式请求失败: {e}")
                        error_data = json.dumps({"error": str(e)})
                        yield f"data: {error_data}\n\n"
                
                from fastapi.responses import StreamingResponse
                request_time = time.time() - request_start
                logger.info(f"[LiteLLMRouter] LiteLLM流式请求完成，耗时: {request_time:.3f}秒")
                return StreamingResponse(generate(), media_type="text/event-stream")
            else:
                # 非流式处理
                response = await litellm.acompletion(**params)
                from fastapi.responses import JSONResponse
                request_time = time.time() - request_start
                logger.info(f"[LiteLLMRouter] LiteLLM非流式请求完成，耗时: {request_time:.3f}秒")
                return JSONResponse(content=dict(response))  # type: ignore
        except Exception as e:
            logger.error(f"LiteLLM 请求失败: {e}")
            raise
    
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
        
        return params

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


class OllamaBackendRouter(BackendRouter):
    """Ollama后端路由器（用于本地Ollama）"""
    
    def __init__(self, backend_config: BackendConfig, base_url: str = "http://localhost:11434",
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config,
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        self.base_url = base_url
        # 不再自己创建client，改为从ClientPool获取
        self._client = None
        self._client_key = (self.base_url.rstrip('/'), None)
    
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理Ollama请求"""
        # 确定端点
        if "messages" in request_data:
            # OpenAI格式请求
            endpoint = "v1/chat/completions"
        else:
            # Ollama格式请求
            endpoint = "api/generate"
            # 确保有model字段
            if "model" not in request_data:
                request_data["model"] = actual_model
        
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        # 从ClientPool获取客户端
        if self._client is None:
            self._client = await client_pool.get_client(
                base_url=self.base_url,
                api_key=None,
                timeout=self.config.timeout
            )
        
        # 确保客户端已初始化
        if self._client is None:
            logger.error(f"[OllamaBackendRouter] 无法获取HTTP客户端")
            raise HTTPException(status_code=500, detail="无法初始化HTTP客户端")
        
        # 处理流式响应
        if stream:
            # 准备请求头
            headers = {"Content-Type": "application/json"}
            # 根据端点确定媒体类型和格式
            if endpoint == "api/generate":
                media_type = "application/x-ndjson"
                is_sse_format = False
                chunk_end_marker = b'\n'
            else:
                media_type = "text/event-stream"
                is_sse_format = True
                chunk_end_marker = b'\n\n'
            
            # 使用基类的通用流式处理方法
            return await self._handle_stream_generic(
                url=url,
                data=request_data,
                headers=headers,
                media_type=media_type,
                is_sse_format=is_sse_format,
                chunk_end_marker=chunk_end_marker
            )
        
        # 处理非流式响应
        else:
            try:
                # 确保客户端已初始化
                if self._client is None:
                    logger.error(f"[OllamaBackendRouter] HTTP客户端未初始化")
                    raise HTTPException(status_code=500, detail="HTTP客户端未初始化")
                
                # 使用从ClientPool获取的客户端（性能优化）
                response = await self._client.post(url, json=request_data)
                
                if response.status_code != 200:
                    raise HTTPException(status_code=response.status_code, detail=response.text)
                
                return JSONResponse(content=response.json())
            except Exception as e:
                logger.error(f"Ollama请求失败: {e}")
                raise HTTPException(status_code=500, detail=str(e))
    
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """Ollama响应已经是Ollama格式，直接返回或转换"""
        if isinstance(response_data, dict):
            return response_data
        elif hasattr(response_data, 'body'):
            # JSONResponse对象
            body = response_data.body
            if isinstance(body, bytes):
                return json.loads(body.decode())
            else:
                return body
        else:
            raise ValueError(f"无法处理的响应类型: {type(response_data)}")


class MockBackendRouter(BackendRouter):
    """模拟后端路由器，用于在没有真实后端时提供模拟响应"""
    
    def __init__(self, backend_config: BackendConfig,
                 tool_compression_enabled: bool = True, prompt_compression_enabled: bool = True):
        super().__init__(backend_config,
                         tool_compression_enabled=tool_compression_enabled,
                         prompt_compression_enabled=prompt_compression_enabled)
        self.mock_responses = {
            "generate": {
                "model": "mock-model",
                "response": "这是一个模拟响应。由于没有安装Ollama，我无法提供真实的AI回复。请安装Ollama或配置其他后端服务。",
                "done": True,
                "total_duration": 1000000000,
            },
            "chat": {
                "id": "chatcmpl-mock",
                "object": "chat.completion",
                "created": 1700000000,
                "model": "mock-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "这是一个模拟响应。由于没有安装Ollama，我无法提供真实的AI回复。请安装Ollama或配置其他后端服务。"
                        },
                        "finish_reason": "stop"
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30
                }
            }
        }
    
    async def handle_request(
        self,
        actual_model: str,
        request_data: Dict[str, Any],
        stream: bool = False,
        support_thinking: bool = False
    ) -> Any:
        """处理模拟请求"""
        logger.info(f"模拟后端处理请求，模型: {actual_model}, 流式: {stream}")
        
        # 判断请求类型
        if "messages" in request_data:
            # OpenAI格式请求
            response_type = "chat"
        else:
            # Ollama格式请求
            response_type = "generate"
        
        # 如果是流式请求，返回流式响应
        if stream:
            async def mock_stream():
                import time
                import asyncio
                if response_type == "chat":
                    # OpenAI流式格式
                    mock_data = self.mock_responses["chat"]
                    content = mock_data["choices"][0]["message"]["content"]
                    words = content.split()
                    for i, word in enumerate(words):
                        chunk = {
                            "id": "chatcmpl-mock",
                            "object": "chat.completion.chunk",
                            "created": 1700000000,
                            "model": actual_model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": word + " "},
                                    "finish_reason": None if i < len(words) - 1 else "stop"
                                }
                            ]
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
                        await asyncio.sleep(0.05)
                    yield "data: [DONE]\n\n"
                else:
                    # Ollama流式格式
                    mock_data = self.mock_responses["generate"]
                    content = mock_data["response"]
                    words = content.split()
                    for i, word in enumerate(words):
                        chunk = {
                            "model": actual_model,
                            "response": word + " ",
                            "done": i == len(words) - 1
                        }
                        yield json.dumps(chunk) + "\n"
                        await asyncio.sleep(0.05)
            
            if response_type == "chat":
                return StreamingResponse(mock_stream(), media_type="text/event-stream")
            else:
                return StreamingResponse(mock_stream(), media_type="application/x-ndjson")
        
        # 非流式请求
        else:
            if response_type == "chat":
                mock_data = self.mock_responses["chat"].copy()
                mock_data["model"] = actual_model
                return JSONResponse(content=mock_data)
            else:
                mock_data = self.mock_responses["generate"].copy()
                mock_data["model"] = actual_model
                return JSONResponse(content=mock_data)
    
    def convert_to_ollama_format(self, response_data: Any, virtual_model: str) -> Dict[str, Any]:
        """将模拟响应转换为Ollama格式"""
        if isinstance(response_data, dict):
            return response_data
        elif hasattr(response_data, 'body'):
            # JSONResponse对象
            body = response_data.body
            if isinstance(body, bytes):
                return json.loads(body.decode())
            else:
                return body
        else:
            raise ValueError(f"无法处理的响应类型: {type(response_data)}")


