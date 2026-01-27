"""
Smart Ollama Proxy - 全局统一日志记录器

提供统一的日志记录接口，支持：
1. 基础日志打印功能及本地文件持久化写入
2. 流式日志记录机制：实时捕获数据块，流结束后汇总组装为完整JSON对象输出
3. 常规非流式数据记录：自动序列化为JSON格式
4. 日志记录线程与主业务线程分离，确保系统性能与响应效率
"""

import os
import uuid
import time
import threading
import logging
import queue
import json as json_module
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional, Union, List, Callable
from enum import Enum
from datetime import datetime
from pathlib import Path

from utils import json, sanitize_unicode_string


class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogType(Enum):
    """日志类型枚举"""
    # 基础日志类型
    BASE = "base"              # 基础日志（info, debug, error等）
    OBJECT = "object"          # 对象日志（自动序列化为JSON）
    # 流式日志类型
    STREAM_START = "stream_start"      # 流式会话开始
    STREAM_CHUNK = "stream_chunk"      # 流式数据块
    STREAM_END = "stream_end"          # 流式会话结束
    # 兼容类型（保留）
    INPUT_STREAM = "input_stream"      # 输入流日志（兼容）
    OUTPUT_STREAM = "output_stream"    # 输出流日志（兼容）
    STREAM_PROGRESS = "stream_progress"  # 流式进度日志（兼容）
    STREAM_COMPLETE = "stream_complete"  # 流式完成日志（兼容）
    DEBUG_PRINT = "debug_print"        # 调试打印日志（兼容）


class StreamSession:
    """流式会话，用于缓存和管理流式数据块"""
    
    def __init__(self, session_id: str, metadata: Optional[Dict[str, Any]] = None):
        self.session_id = session_id
        self.metadata = metadata or {}
        self.start_time = time.time()
        self.chunks: List[Dict[str, Any]] = []  # 每个块包含 chunk_data, chunk_index, timestamp 等
        self.completed = False
        self.total_bytes = 0
    
    def add_chunk(self, chunk_data: Union[str, bytes, Dict[str, Any]], 
                  chunk_index: int, total_bytes: int, **kwargs):
        """添加数据块到会话"""
        # 将数据转换为可序列化的格式
        if isinstance(chunk_data, bytes):
            try:
                chunk_str = chunk_data.decode('utf-8', errors='replace')
            except Exception:
                chunk_str = "[binary data]"
        elif isinstance(chunk_data, dict):
            chunk_str = json.dumps(chunk_data, ensure_ascii=False)
        else:
            chunk_str = str(chunk_data)
        
        chunk_entry = {
            "chunk_index": chunk_index,
            "chunk_size": len(chunk_data) if hasattr(chunk_data, '__len__') else len(chunk_str),
            "total_bytes": total_bytes,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "chunk_data": chunk_str[:1000] + "..." if len(chunk_str) > 1000 else chunk_str,
            **kwargs
        }
        self.chunks.append(chunk_entry)
        self.total_bytes = total_bytes
    
    def assemble(self) -> Dict[str, Any]:
        """组装所有数据块为完整响应"""
        # 按块索引排序
        sorted_chunks = sorted(self.chunks, key=lambda x: x["chunk_index"])
        
        # 提取数据并拼接
        full_data = ""
        # 尝试构建完整的JSON响应（针对OpenAI格式）
        complete_json = None
        # 收集所有chunk的解析结果
        parsed_chunks = []
        for chunk in sorted_chunks:
            chunk_data = chunk.get("chunk_data", "")
            # 如果chunk_data是JSON字符串，尝试解析
            if isinstance(chunk_data, str) and chunk_data.strip().startswith('{'):
                try:
                    parsed = json.loads(chunk_data)
                    parsed_chunks.append(parsed)
                    # 尝试提取常见字段中的文本内容
                    if "choices" in parsed:
                        for choice in parsed.get("choices", []):
                            if "delta" in choice and "content" in choice["delta"]:
                                full_data += choice["delta"]["content"]
                            elif "message" in choice and "content" in choice["message"]:
                                full_data += choice["message"]["content"]
                    elif "response" in parsed:
                        full_data += parsed["response"]
                    elif "content" in parsed:
                        full_data += parsed["content"]
                    else:
                        # 无法提取，保留原始JSON
                        full_data += chunk_data
                except:
                    full_data += chunk_data
            else:
                full_data += chunk_data
        
        # 尝试合并所有chunk为一个完整的JSON响应
        if parsed_chunks:
            complete_json = self._merge_parsed_chunks(parsed_chunks)
        
        result = {
            "session_id": self.session_id,
            "metadata": self.metadata,
            "start_time": self.start_time,
            "end_time": time.time(),
            "duration": time.time() - self.start_time,
            "total_chunks": len(self.chunks),
            "total_bytes": self.total_bytes,
            "assembled_data": full_data,
            "chunks": sorted_chunks  # 保留原始块信息
        }
        if complete_json is not None:
            result["complete_json"] = complete_json
        
        return result
    
    def _merge_parsed_chunks(self, parsed_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """合并解析后的chunk为一个完整的JSON响应（针对OpenAI格式）"""
        if not parsed_chunks:
            return {}
        
        # 初始化完整响应结构，使用第一个chunk的元数据
        first = parsed_chunks[0]
        complete = {
            "id": first.get("id", ""),
            "object": first.get("object", "chat.completion.chunk"),
            "created": first.get("created", 0),
            "model": first.get("model", ""),
            "choices": [],
            "usage": first.get("usage", {})
        }
        
        # 合并所有choices
        # 假设每个chunk只有一个choice（常见情况）
        # 我们需要合并delta内容
        merged_content = ""
        for chunk in parsed_chunks:
            if "choices" in chunk and chunk["choices"]:
                choice = chunk["choices"][0]
                if "delta" in choice and "content" in choice["delta"]:
                    merged_content += choice["delta"]["content"]
                elif "message" in choice and "content" in choice["message"]:
                    merged_content += choice["message"]["content"]
        
        # 构建最终的choice
        if merged_content:
            complete["choices"] = [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": merged_content
                },
                "finish_reason": "stop"
            }]
        else:
            # 如果没有提取到内容，保留原始chunks
            complete["choices"] = []
        
        return complete


class GlobalLogger:
    """
    全局统一日志记录器 - 单例模式
    
    使用线程池异步处理日志记录，避免阻塞主线程。
    支持基础日志、对象日志、流式日志记录。
    """
    
    _instance: Optional['GlobalLogger'] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        log_dir: str = "logs",
        max_workers: int = 4,
        max_queue_size: int = 1000,
        enabled: bool = True,
        verbose_json_logging: bool = False,
        log_level: Union[str, LogLevel] = LogLevel.INFO,
        enable_file_logging: bool = True,
        enable_console_logging: bool = True
    ):
        """初始化全局日志记录器
        
        Args:
            log_dir: 日志目录
            max_workers: 线程池最大工作线程数
            max_queue_size: 最大队列大小
            enabled: 是否启用日志记录
            verbose_json_logging: 是否启用详细的JSON日志记录
            log_level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
            enable_file_logging: 是否启用文件日志
            enable_console_logging: 是否启用控制台日志
        """
        if getattr(self, '_initialized', False):
            return
            
        self.log_dir = Path(log_dir)
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self.enabled = enabled
        self.verbose_json_logging = verbose_json_logging
        
        # 日志级别处理
        if isinstance(log_level, str):
            log_level = LogLevel(log_level.upper())
        self.log_level = log_level
        
        self.enable_file_logging = enable_file_logging
        self.enable_console_logging = enable_console_logging
        
        # 确保日志目录存在
        self.log_dir.mkdir(exist_ok=True)
        
        # 创建日志文件（带时间戳）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.base_log_file = self.log_dir / f"unified_{timestamp}.jsonl"
        self.stream_log_file = self.log_dir / f"stream_{timestamp}.jsonl"
        
        # 初始化队列和线程池
        self.log_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="global_logger")
        
        # 流式会话缓存
        self._stream_sessions: Dict[str, StreamSession] = {}
        self._stream_sessions_lock = threading.Lock()
        
        # 启动日志处理线程
        self._stop_event = threading.Event()
        self._processing_thread = threading.Thread(
            target=self._process_log_queue,
            name="global_logger_processor",
            daemon=True
        )
        self._processing_thread.start()
        
        # 初始化基础日志器（用于内部日志）
        self._internal_logger = logging.getLogger("smart_ollama_proxy.global_logger")
        
        self._initialized = True
        self._internal_logger.info(f"全局日志记录器初始化完成，日志目录: {log_dir}")
        self._internal_logger.info(f"基础日志文件: {self.base_log_file}")
        self._internal_logger.info(f"流式日志文件: {self.stream_log_file}")
        self._internal_logger.info(f"线程池大小: {max_workers}, 队列大小: {max_queue_size}")
        self._internal_logger.info(f"日志级别: {log_level.value}")
    
    def _should_log(self, level: LogLevel) -> bool:
        """检查是否应该记录给定级别的日志"""
        # 日志级别优先级：DEBUG < INFO < WARNING < ERROR < CRITICAL
        level_priority = {
            LogLevel.DEBUG: 10,
            LogLevel.INFO: 20,
            LogLevel.WARNING: 30,
            LogLevel.ERROR: 40,
            LogLevel.CRITICAL: 50
        }
        current_priority = level_priority.get(self.log_level, 20)
        msg_priority = level_priority.get(level, 20)
        return msg_priority >= current_priority
    
    def _create_base_entry(self, level: LogLevel, message: str, **kwargs) -> Dict[str, Any]:
        """创建基础日志条目"""
        entry = {
            "id": str(uuid.uuid4()),
            "type": LogType.BASE.value,
            "level": level.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "message": message,
            **kwargs
        }
        return self._sanitize_entry(entry)
    
    def log(self, level: Union[str, LogLevel], message: str, **kwargs):
        """记录基础日志
        
        Args:
            level: 日志级别（DEBUG, INFO, WARNING, ERROR, CRITICAL）
            message: 日志消息
            **kwargs: 额外字段
        """
        if not self.enabled:
            return
        
        if isinstance(level, str):
            level = LogLevel(level.upper())
        
        if not self._should_log(level):
            return
        
        entry = self._create_base_entry(level, message, **kwargs)
        
        # 将任务放入队列
        try:
            self.log_queue.put_nowait(("base", entry))
        except queue.Full:
            self._internal_logger.warning(f"日志队列已满，丢弃日志: {message[:100]}...")
    
    def info(self, message: str, **kwargs):
        """记录INFO级别日志"""
        self.log(LogLevel.INFO, message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """记录DEBUG级别日志"""
        self.log(LogLevel.DEBUG, message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        """记录WARNING级别日志"""
        self.log(LogLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """记录ERROR级别日志"""
        self.log(LogLevel.ERROR, message, **kwargs)
    
    def log_object(self, obj: Any, level: LogLevel = LogLevel.INFO, **kwargs):
        """记录任意对象，自动序列化为JSON
        
        Args:
            obj: 要记录的对象（将尝试序列化为JSON）
            level: 日志级别
            **kwargs: 额外字段
        """
        if not self.enabled:
            return
        
        if not self._should_log(level):
            return
        
        # 尝试序列化对象
        try:
            if isinstance(obj, (dict, list, str, int, float, bool, type(None))):
                data = obj
            else:
                # 尝试使用对象的__dict__属性
                data = vars(obj) if hasattr(obj, '__dict__') else str(obj)
            
            # 确保数据可序列化
            data = self._ensure_serializable(data)
            
            entry = {
                "id": str(uuid.uuid4()),
                "type": LogType.OBJECT.value,
                "level": level.value,
                "timestamp": time.time(),
                "timestamp_iso": datetime.now().isoformat(),
                "data": data,
                **kwargs
            }
            entry = self._sanitize_entry(entry)
            
            try:
                self.log_queue.put_nowait(("object", entry))
            except queue.Full:
                self._internal_logger.warning(f"日志队列已满，丢弃对象日志")
        except Exception as e:
            self._internal_logger.error(f"记录对象日志失败: {e}")
    
    def start_stream(self, session_id: Optional[str] = None, **metadata) -> str:
        """开始一个流式会话
        
        Args:
            session_id: 可选的会话ID，如果为None则自动生成
            **metadata: 会话元数据
            
        Returns:
            会话ID
        """
        if not self.enabled:
            return ""
        
        session_id = session_id or f"stream_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        
        with self._stream_sessions_lock:
            self._stream_sessions[session_id] = StreamSession(session_id, metadata)
        
        # 记录流式开始事件
        entry = {
            "id": session_id,
            "type": LogType.STREAM_START.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "metadata": metadata
        }
        entry = self._sanitize_entry(entry)
        
        try:
            self.log_queue.put_nowait(("stream_start", entry))
        except queue.Full:
            self._internal_logger.warning(f"日志队列已满，丢弃流式开始日志")
        
        return session_id
    
    def log_stream_chunk(self, session_id: str, chunk_data: Union[str, bytes, Dict[str, Any]],
                         chunk_index: int, total_bytes: int, **kwargs):
        """记录流式数据块
        
        Args:
            session_id: 会话ID
            chunk_data: 数据块（字符串、字节或字典）
            chunk_index: 块索引
            total_bytes: 累计总字节数
            **kwargs: 额外字段
        """
        if not self.enabled or not session_id:
            return
        
        # 更新会话缓存
        with self._stream_sessions_lock:
            session = self._stream_sessions.get(session_id)
            if session:
                session.add_chunk(chunk_data, chunk_index, total_bytes, **kwargs)
        
        # 记录流式块事件（可选，避免日志过多）
        # 仅在verbose_json_logging为True时记录chunk事件，减少日志量
        if self.verbose_json_logging:
            entry = {
                "id": session_id,
                "type": LogType.STREAM_CHUNK.value,
                "timestamp": time.time(),
                "timestamp_iso": datetime.now().isoformat(),
                "chunk_index": chunk_index,
                "total_bytes": total_bytes,
                **kwargs
            }
            entry = self._sanitize_entry(entry)
            
            try:
                self.log_queue.put_nowait(("stream_chunk", entry))
            except queue.Full:
                pass
    
    def end_stream(self, session_id: str, **kwargs):
        """结束流式会话，组装数据并记录完整响应
        
        Args:
            session_id: 会话ID
            **kwargs: 额外字段
        """
        if not self.enabled or not session_id:
            return
        
        # 从缓存中获取会话并移除
        with self._stream_sessions_lock:
            session = self._stream_sessions.pop(session_id, None)
        
        if not session:
            self._internal_logger.warning(f"尝试结束不存在的流式会话: {session_id}")
            return
        
        # 组装完整数据
        assembled_data = session.assemble()
        
        # 在控制台打印完整的组装JSON（如果启用控制台日志）
        if self.enable_console_logging:
            try:
                # 优先使用complete_json（如果存在）
                complete_json = assembled_data.get("complete_json")
                if complete_json is not None:
                    formatted = json.dumps(complete_json, ensure_ascii=False, indent=2)
                    print(f"[StreamLogger] 流式会话 {session_id} 完整响应JSON:\n{formatted}")
                else:
                    # 回退到assembled_data
                    assembled_json = assembled_data.get("assembled_data", "")
                    # 如果assembled_json是字符串，尝试解析为JSON对象
                    if isinstance(assembled_json, str) and assembled_json.strip():
                        try:
                            parsed = json.loads(assembled_json)
                            formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
                            print(f"[StreamLogger] 流式会话 {session_id} 完整响应JSON:\n{formatted}")
                        except:
                            # 如果不是有效的JSON，直接打印字符串（可能已经是文本内容）
                            print(f"[StreamLogger] 流式会话 {session_id} 完整响应内容:\n{assembled_json[:1000]}{'...' if len(assembled_json) > 1000 else ''}")
                    else:
                        # 如果assembled_json是字典或其他类型，直接格式化
                        formatted = json.dumps(assembled_json, ensure_ascii=False, indent=2)
                        print(f"[StreamLogger] 流式会话 {session_id} 完整响应JSON:\n{formatted}")
            except Exception as e:
                self._internal_logger.error(f"打印完整响应JSON失败: {e}")
        
        # 记录流式结束事件（包含完整数据）
        entry = {
            "id": session_id,
            "type": LogType.STREAM_END.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "metadata": session.metadata,
            "assembled_data": assembled_data,
            **kwargs
        }
        entry = self._sanitize_entry(entry)
        
        try:
            self.log_queue.put_nowait(("stream_end", entry))
        except queue.Full:
            self._internal_logger.warning(f"日志队列已满，丢弃流式结束日志")
    
    # 兼容旧StreamLogger接口的方法
    def log_input_stream(self, data: Dict[str, Any], router_name: str, model_name: str,
                         stream: bool = False, request_id: Optional[str] = None) -> str:
        """记录输入流日志（兼容旧接口）"""
        log_id = request_id or self.start_stream(metadata={
            "router": router_name,
            "model": model_name,
            "stream": stream,
            "data_type": "input"
        })
        
        # 在控制台打印请求输入JSON（如果启用控制台日志）
        if self.enable_console_logging:
            try:
                formatted = json.dumps(data, ensure_ascii=False, indent=2)
                print(f"[StreamLogger] 请求输入 (会话 {log_id}) - 路由器: {router_name}, 模型: {model_name}, 流式: {stream}")
                print(f"[StreamLogger] 请求数据JSON:\n{formatted}")
            except Exception as e:
                self._internal_logger.error(f"打印请求输入JSON失败: {e}")
        
        # 记录对象日志（到基础日志文件）
        self.log_object(data, level=LogLevel.INFO,
                        router=router_name, model=model_name, stream=stream)
        
        # 同时记录INPUT_STREAM事件到流式日志文件，确保请求JSON出现在流式日志中
        if self.enabled and log_id:
            entry = {
                "id": log_id,
                "type": LogType.INPUT_STREAM.value,
                "timestamp": time.time(),
                "timestamp_iso": datetime.now().isoformat(),
                "router": router_name,
                "model": model_name,
                "stream": stream,
                "request_data": data
            }
            entry = self._sanitize_entry(entry)
            
            try:
                self.log_queue.put_nowait(("stream_start", entry))  # 使用stream_start类型，因为INPUT_STREAM会被写入流式日志文件
            except queue.Full:
                self._internal_logger.warning(f"日志队列已满，丢弃输入流日志")
        
        return log_id
    
    def log_output_stream(self, chunk: Union[str, bytes], log_id: str, router_name: str,
                          chunk_index: int, total_bytes: int, content_length: Optional[int] = None):
        """记录输出流日志（兼容旧接口）"""
        self.log_stream_chunk(log_id, chunk, chunk_index, total_bytes,
                              router=router_name, content_length=content_length)
    
    def log_stream_progress(self, log_id: str, router_name: str, chunk_count: int,
                            total_bytes: int, content_length: Optional[int] = None,
                            spinner_idx: int = 0):
        """记录流式进度日志（兼容旧接口）"""
        # 根据用户要求，移除每个chunk块的打印，只保留流式完成时的打印
        # 因此此方法不再记录任何日志条目
        return
    
    def log_stream_complete(self, log_id: str, router_name: str, chunk_count: int, total_bytes: int):
        """记录流式完成日志（兼容旧接口）"""
        if not self.enabled or not log_id:
            return
        
        entry = {
            "id": log_id,
            "type": LogType.STREAM_COMPLETE.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "router": router_name,
            "chunk_count": chunk_count,
            "total_bytes": total_bytes,
            "completed": True
        }
        entry = self._sanitize_entry(entry)
        
        try:
            self.log_queue.put_nowait(("stream_complete", entry))
        except queue.Full:
            pass
    
    def log_debug_print(self, message: str, router_name: str, model_name: Optional[str] = None):
        """记录调试打印日志（兼容旧接口）"""
        self.debug(message, router=router_name, model=model_name)
    
    def _sanitize_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """清理日志条目中的无效Unicode字符"""
        def clean_value(value):
            if isinstance(value, str):
                return sanitize_unicode_string(value)
            elif isinstance(value, dict):
                return {k: clean_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [clean_value(item) for item in value]
            else:
                return value
        
        # entry 保证是字典，clean_value 会保持字典结构
        cleaned = clean_value(entry)
        # 类型断言，确保返回的是字典
        from typing import cast
        return cast(Dict[str, Any], cleaned)
    
    def _generate_log_id(self) -> str:
        """生成唯一的日志ID（兼容旧接口）"""
        import uuid
        import time
        return f"stream_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    
    def _ensure_serializable(self, data: Any) -> Any:
        """确保数据可序列化为JSON"""
        if isinstance(data, (str, int, float, bool, type(None))):
            return data
        elif isinstance(data, dict):
            return {k: self._ensure_serializable(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._ensure_serializable(item) for item in data]
        elif isinstance(data, bytes):
            try:
                return data.decode('utf-8', errors='replace')
            except:
                return "[binary data]"
        else:
            # 尝试转换为字符串
            try:
                return str(data)
            except:
                return "[unserializable object]"
    
    def _write_log_to_file(self, log_type: str, log_entry: Dict[str, Any]) -> None:
        """将日志条目写入对应的文件"""
        try:
            if log_type in ("base", "object"):
                log_file = self.base_log_file
            else:
                # 流式相关日志写入流式日志文件
                log_file = self.stream_log_file
            
            # 将日志条目转换为JSON字符串
            json_str = json.dumps(log_entry, ensure_ascii=False)
            
            # 写入文件（追加模式）
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json_str + '\n')
                
            # 如果启用控制台日志，也输出到控制台（仅基础日志）
            if self.enable_console_logging and log_type in ("base", "object"):
                level = log_entry.get("level", "INFO")
                message = log_entry.get("message", "") or str(log_entry.get("data", ""))[:200]
                print(f"[{level}] {message}")
                
        except Exception as e:
            self._internal_logger.error(f"写入日志文件失败: {e}")
    
    def _process_log_queue(self) -> None:
        """处理日志队列的线程函数"""
        # 在线程中获取logger，避免初始化问题
        process_logger = logging.getLogger("smart_ollama_proxy.global_logger.processor")
        process_logger.debug("全局日志处理线程启动")
        
        while not self._stop_event.is_set():
            try:
                # 从队列获取日志条目（阻塞，但有超时）
                try:
                    log_type, log_entry = self.log_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                try:
                    # 写入文件
                    if self.enable_file_logging:
                        self._write_log_to_file(log_type, log_entry)
                    
                    # 如果启用详细JSON日志，同时在控制台输出（通过内部日志系统）
                    if self.verbose_json_logging:
                        log_entry_str = json.dumps(log_entry, ensure_ascii=False, indent=2)
                        if len(log_entry_str) > 1000:
                            log_entry_str = log_entry_str[:1000] + "..."
                        process_logger.debug(f"日志记录: {log_entry.get('type', 'unknown')} - ID: {log_entry.get('id', 'unknown')}")
                
                except Exception as e:
                    process_logger.error(f"处理日志条目失败: {e}")
                
                finally:
                    self.log_queue.task_done()
                    
            except Exception as e:
                if not self._stop_event.is_set():
                    process_logger.error(f"日志处理线程异常: {e}")
        
        process_logger.debug("全局日志处理线程停止")
    
    def shutdown(self) -> None:
        """关闭全局日志记录器"""
        if not self._initialized:
            return
            
        self._internal_logger.info("正在关闭全局日志记录器...")
        self._stop_event.set()
        
        # 等待处理线程结束
        if self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5.0)
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        # 清理流式会话缓存
        with self._stream_sessions_lock:
            self._stream_sessions.clear()
        
        self._internal_logger.info("全局日志记录器已关闭")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "enabled": self.enabled,
            "queue_size": self.log_queue.qsize(),
            "max_queue_size": self.max_queue_size,
            "active_threads": self.executor._max_workers,
            "stream_sessions": len(self._stream_sessions),
            "base_log_file": str(self.base_log_file),
            "stream_log_file": str(self.stream_log_file),
            "verbose_json_logging": self.verbose_json_logging,
            "log_level": self.log_level.value
        }


# 全局单例实例
_global_logger_instance: Optional[GlobalLogger] = None


def get_global_logger() -> GlobalLogger:
    """获取全局日志记录器的全局实例
    
    Returns:
        GlobalLogger实例
    """
    global _global_logger_instance
    
    if _global_logger_instance is None:
        # 使用默认配置初始化
        _global_logger_instance = GlobalLogger()
    
    return _global_logger_instance


def init_global_logger(
    log_dir: str = "logs",
    max_workers: int = 4,
    max_queue_size: int = 1000,
    enabled: bool = True,
    verbose_json_logging: bool = False,
    log_level: Union[str, LogLevel] = LogLevel.INFO,
    enable_file_logging: bool = True,
    enable_console_logging: bool = False
) -> GlobalLogger:
    """初始化全局日志记录器（如果尚未初始化）
    
    Args:
        log_dir: 日志目录
        max_workers: 线程池最大工作线程数
        max_queue_size: 最大队列大小
        enabled: 是否启用日志记录
        verbose_json_logging: 是否启用详细的JSON日志记录
        log_level: 日志级别
        enable_file_logging: 是否启用文件日志
        enable_console_logging: 是否启用控制台日志
        
    Returns:
        初始化的GlobalLogger实例
    """
    global _global_logger_instance
    
    if _global_logger_instance is None:
        _global_logger_instance = GlobalLogger(
            log_dir=log_dir,
            max_workers=max_workers,
            max_queue_size=max_queue_size,
            enabled=enabled,
            verbose_json_logging=verbose_json_logging,
            log_level=log_level,
            enable_file_logging=enable_file_logging,
            enable_console_logging=enable_console_logging
        )
    
    return _global_logger_instance


def shutdown_global_logger() -> None:
    """关闭全局日志记录器"""
    global _global_logger_instance
    
    if _global_logger_instance is not None:
        _global_logger_instance.shutdown()
        _global_logger_instance = None


# 兼容性接口（保持旧代码能运行）
def get_stream_logger() -> GlobalLogger:
    """获取流式日志处理器的全局实例（兼容性接口）
    
    Returns:
        GlobalLogger实例
    """
    return get_global_logger()


def init_stream_logger(
    log_dir: str = "logs",
    max_workers: int = 4,
    max_queue_size: int = 1000,
    enabled: bool = True,
    verbose_json_logging: bool = False
) -> GlobalLogger:
    """初始化流式日志处理器（兼容性接口）
    
    Args:
        log_dir: 日志目录
        max_workers: 线程池最大工作线程数
        max_queue_size: 最大队列大小
        enabled: 是否启用流式日志记录
        verbose_json_logging: 是否启用详细的JSON日志记录
        
    Returns:
        初始化的GlobalLogger实例
    """
    return init_global_logger(
        log_dir=log_dir,
        max_workers=max_workers,
        max_queue_size=max_queue_size,
        enabled=enabled,
        verbose_json_logging=verbose_json_logging,
        log_level=LogLevel.INFO,
        enable_file_logging=True,
        enable_console_logging=False
    )


def shutdown_stream_logger() -> None:
    """关闭流式日志处理器（兼容性接口）"""
    shutdown_global_logger()


class GlobalLoggingHandler(logging.Handler):
    """将标准logging模块的日志转发到GlobalLogger"""
    
    def __init__(self, global_logger: Optional[GlobalLogger] = None):
        super().__init__()
        self.global_logger = global_logger or get_global_logger()
        
    def emit(self, record: logging.LogRecord) -> None:
        """处理日志记录"""
        try:
            # 将LogRecord转换为日志消息
            message = self.format(record)
            
            # 根据日志级别映射
            level_map = {
                logging.DEBUG: LogLevel.DEBUG,
                logging.INFO: LogLevel.INFO,
                logging.WARNING: LogLevel.WARNING,
                logging.ERROR: LogLevel.ERROR,
                logging.CRITICAL: LogLevel.CRITICAL
            }
            
            level = level_map.get(record.levelno, LogLevel.INFO)
            
            # 提取额外字段（使用getattr避免类型错误）
            extra_fields = {}
            router = getattr(record, 'router', None)
            if router is not None:
                extra_fields['router'] = router
            model = getattr(record, 'model', None)
            if model is not None:
                extra_fields['model'] = model
            stream = getattr(record, 'stream', None)
            if stream is not None:
                extra_fields['stream'] = stream
            request_id = getattr(record, 'request_id', None)
            if request_id is not None:
                extra_fields['request_id'] = request_id
            
            # 记录到GlobalLogger
            self.global_logger.log(level, message, **extra_fields)
            
        except Exception as e:
            # 避免循环错误
            print(f"[GlobalLoggingHandler error] {e}")


def setup_logging_integration(
    logger_name: str = "smart_ollama_proxy",
    level: Union[int, str] = logging.INFO,
    propagate: bool = False,
    global_logger: Optional[GlobalLogger] = None
) -> None:
    """设置标准logging模块与GlobalLogger的集成
    
    Args:
        logger_name: 要配置的logger名称，默认根logger
        level: 日志级别
        propagate: 是否向上传播
        global_logger: 可选的GlobalLogger实例，如果为None则使用全局单例
    """
    # 获取或创建GlobalLogger实例
    if global_logger is None:
        global_logger = get_global_logger()
    
    # 创建handler
    handler = GlobalLoggingHandler(global_logger)
    
    # 设置格式化器（可选，使用简单格式）
    formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    
    # 配置指定logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = propagate
    
    # 移除现有handler（避免重复）
    for hdlr in logger.handlers[:]:
        if isinstance(hdlr, GlobalLoggingHandler):
            logger.removeHandler(hdlr)
    
    # 添加新的handler
    logger.addHandler(handler)
    
    # 记录配置完成
    global_logger.info(f"标准logging模块集成完成，logger: {logger_name}, 级别: {level}")


def configure_root_logging(
    level: Union[int, str] = logging.INFO,
    global_logger: Optional[GlobalLogger] = None
) -> None:
    """配置根logger使用GlobalLogger"""
    setup_logging_integration(
        logger_name="",
        level=level,
        propagate=False,
        global_logger=global_logger
    )


# 导出公共接口
__all__ = [
    'GlobalLogger',
    'LogLevel',
    'LogType',
    'StreamSession',
    'GlobalLoggingHandler',
    'get_global_logger',
    'init_global_logger',
    'shutdown_global_logger',
    'setup_logging_integration',
    'configure_root_logging',
    # 兼容性导出
    'get_stream_logger',
    'init_stream_logger',
    'shutdown_stream_logger'
]
