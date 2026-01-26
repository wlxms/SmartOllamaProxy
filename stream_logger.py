"""
Smart Ollama Proxy - 流式日志处理器

专门处理输入流和输出流的日志记录，通过线程池异步处理，避免阻塞主线程。
支持将输入/输出流记录到JSON日志文件中，便于后续分析。
"""

import os
import uuid
import time
import threading
import logging
import queue
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Dict, Any, Optional, Union, Callable, List
from enum import Enum
from datetime import datetime
from pathlib import Path

from utils import json, sanitize_unicode_string


class LogType(Enum):
    """日志类型枚举"""
    INPUT_STREAM = "input_stream"  # 输入流日志
    OUTPUT_STREAM = "output_stream"  # 输出流日志
    STREAM_PROGRESS = "stream_progress"  # 流式进度日志
    STREAM_COMPLETE = "stream_complete"  # 流式完成日志
    DEBUG_PRINT = "debug_print"  # 调试打印日志


class StreamLogger:
    """
    流式日志处理器 - 单例模式
    
    使用线程池异步处理日志记录，避免阻塞流式响应。
    支持输入流和输出流的分离记录，每个流生成唯一ID用于关联。
    """
    
    _instance: Optional['StreamLogger'] = None
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
        verbose_json_logging: bool = False
    ):
        """初始化流式日志处理器
        
        Args:
            log_dir: 日志目录
            max_workers: 线程池最大工作线程数
            max_queue_size: 最大队列大小
            enabled: 是否启用流式日志记录
            verbose_json_logging: 是否启用详细的JSON日志记录
        """
        if getattr(self, '_initialized', False):
            return
            
        self.log_dir = Path(log_dir)
        self.max_workers = max_workers
        self.max_queue_size = max_queue_size
        self.enabled = enabled
        self.verbose_json_logging = verbose_json_logging
        
        # 确保日志目录存在
        self.log_dir.mkdir(exist_ok=True)
        
        # 创建日志文件（带时间戳）
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.input_log_file = self.log_dir / f"stream_input_{timestamp}.jsonl"
        self.output_log_file = self.log_dir / f"stream_output_{timestamp}.jsonl"
        
        # 初始化队列和线程池
        self.log_queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="stream_logger")
        
        # 启动日志处理线程
        self._stop_event = threading.Event()
        self._processing_thread = threading.Thread(
            target=self._process_log_queue,
            name="stream_logger_processor",
            daemon=True
        )
        self._processing_thread.start()
        
        # 日志ID映射表（用于快速查找）
        self._log_id_counter = 0
        self._log_id_lock = threading.Lock()
        
        # 初始化基础日志器
        self.logger = logging.getLogger("smart_ollama_proxy.stream_logger")
        
        self._initialized = True
        self.logger.info(f"流式日志处理器初始化完成，日志目录: {log_dir}")
        self.logger.info(f"输入日志文件: {self.input_log_file}")
        self.logger.info(f"输出日志文件: {self.output_log_file}")
        self.logger.info(f"线程池大小: {max_workers}, 队列大小: {max_queue_size}")
    
    def _generate_log_id(self) -> str:
        """生成唯一的日志ID"""
        with self._log_id_lock:
            self._log_id_counter += 1
            timestamp = int(time.time() * 1000)
            return f"log_{timestamp}_{self._log_id_counter}_{uuid.uuid4().hex[:8]}"
    
    def log_input_stream(
        self,
        data: Dict[str, Any],
        router_name: str,
        model_name: str,
        stream: bool = False,
        request_id: Optional[str] = None
    ) -> str:
        """记录输入流日志
        
        Args:
            data: 输入数据（通常是请求体）
            router_name: 路由器名称
            model_name: 模型名称
            stream: 是否为流式请求
            request_id: 可选的请求ID（如果为None则自动生成）
            
        Returns:
            日志ID
        """
        if not self.enabled:
            return ""
            
        log_id = request_id or self._generate_log_id()
        
        log_entry = {
            "id": log_id,
            "type": LogType.INPUT_STREAM.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "router": router_name,
            "model": model_name,
            "stream": stream,
            "data": data
        }
        
        # 清理数据中的无效Unicode字符
        log_entry = self._sanitize_log_entry(log_entry)
        
        # 将任务放入队列
        try:
            self.log_queue.put_nowait(("input", log_entry))
        except queue.Full:
            self.logger.warning(f"输入日志队列已满，丢弃日志: {log_id}")
        
        return log_id
    
    def log_output_stream(
        self,
        chunk: Union[str, bytes],
        log_id: str,
        router_name: str,
        chunk_index: int,
        total_bytes: int,
        content_length: Optional[int] = None
    ) -> None:
        """记录输出流日志（每个chunk）
        
        Args:
            chunk: 数据块（字符串或字节）
            log_id: 关联的日志ID
            router_name: 路由器名称
            chunk_index: 块索引
            total_bytes: 累计总字节数
            content_length: 内容总长度（如果已知）
        """
        if not self.enabled or not log_id:
            return
            
        # 将字节转换为字符串以便记录
        if isinstance(chunk, bytes):
            try:
                chunk_str = chunk.decode('utf-8', errors='replace')
            except Exception:
                chunk_str = "[binary data]"
        else:
            chunk_str = str(chunk)
        
        log_entry = {
            "id": log_id,
            "type": LogType.OUTPUT_STREAM.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "router": router_name,
            "chunk_index": chunk_index,
            "chunk_size": len(chunk) if hasattr(chunk, '__len__') else len(chunk_str),
            "total_bytes": total_bytes,
            "content_length": content_length,
            "chunk_preview": chunk_str[:500] + "..." if len(chunk_str) > 500 else chunk_str
        }
        
        # 清理数据
        log_entry = self._sanitize_log_entry(log_entry)
        
        try:
            self.log_queue.put_nowait(("output", log_entry))
        except queue.Full:
            # 输出日志队列满时不警告，避免循环
            pass
    
    def log_stream_progress(
        self,
        log_id: str,
        router_name: str,
        chunk_count: int,
        total_bytes: int,
        content_length: Optional[int] = None,
        spinner_idx: int = 0
    ) -> None:
        """记录流式进度日志（替代原有的_print_stream_progress）
        
        Args:
            log_id: 关联的日志ID
            router_name: 路由器名称
            chunk_count: 块数量
            total_bytes: 总字节数
            content_length: 内容总长度（如果已知）
            spinner_idx: 进度指示器索引
        """
        if not self.enabled or not log_id:
            return
            
        # 计算进度百分比（如果知道总长度）
        percent = None
        if content_length and content_length > 0:
            percent = (total_bytes / content_length) * 100
            
        log_entry = {
            "id": log_id,
            "type": LogType.STREAM_PROGRESS.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "router": router_name,
            "chunk_count": chunk_count,
            "total_bytes": total_bytes,
            "content_length": content_length,
            "percent": percent,
            "spinner_idx": spinner_idx
        }
        
        try:
            self.log_queue.put_nowait(("progress", log_entry))
        except queue.Full:
            pass
    
    def log_stream_complete(
        self,
        log_id: str,
        router_name: str,
        chunk_count: int,
        total_bytes: int
    ) -> None:
        """记录流式完成日志（替代原有的_print_stream_complete）
        
        Args:
            log_id: 关联的日志ID
            router_name: 路由器名称
            chunk_count: 总块数
            total_bytes: 总字节数
        """
        if not self.enabled or not log_id:
            return
            
        log_entry = {
            "id": log_id,
            "type": LogType.STREAM_COMPLETE.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "router": router_name,
            "chunk_count": chunk_count,
            "total_bytes": total_bytes,
            "completed": True
        }
        
        try:
            self.log_queue.put_nowait(("complete", log_entry))
        except queue.Full:
            pass
    
    def log_debug_print(
        self,
        message: str,
        router_name: str,
        model_name: Optional[str] = None
    ) -> None:
        """记录调试打印日志（替代原有的print调用）
        
        Args:
            message: 调试消息
            router_name: 路由器名称
            model_name: 模型名称（可选）
        """
        if not self.enabled:
            return
            
        log_entry = {
            "id": self._generate_log_id(),
            "type": LogType.DEBUG_PRINT.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "router": router_name,
            "model": model_name,
            "message": message
        }
        
        try:
            self.log_queue.put_nowait(("debug", log_entry))
        except queue.Full:
            self.logger.warning(f"调试日志队列已满，丢弃消息: {message[:100]}...")
    
    def _sanitize_log_entry(self, log_entry: Dict[str, Any]) -> Dict[str, Any]:
        """清理日志条目中的无效Unicode字符
        
        Args:
            log_entry: 原始日志条目
            
        Returns:
            清理后的日志条目
        """
        def clean_value(value):
            if isinstance(value, str):
                return sanitize_unicode_string(value)
            elif isinstance(value, dict):
                return {k: clean_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [clean_value(item) for item in value]
            else:
                return value
        
        return clean_value(log_entry)
    
    def _write_log_to_file(self, log_type: str, log_entry: Dict[str, Any]) -> None:
        """将日志条目写入对应的文件
        
        Args:
            log_type: 日志类型（"input", "output", "progress", "complete", "debug"）
            log_entry: 日志条目
        """
        try:
            if log_type == "input":
                log_file = self.input_log_file
            elif log_type == "output":
                log_file = self.output_log_file
            else:
                # 进度、完成和调试日志都写入输出日志文件
                log_file = self.output_log_file
            
            # 将日志条目转换为JSON字符串
            json_str = json.dumps(log_entry, ensure_ascii=False)
            
            # 写入文件（追加模式）
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(json_str + '\n')
                
        except Exception as e:
            self.logger.error(f"写入日志文件失败: {e}")
    
    def _process_log_queue(self) -> None:
        """处理日志队列的线程函数"""
        # 在线程中获取logger，避免初始化问题
        process_logger = logging.getLogger("smart_ollama_proxy.stream_logger.processor")
        process_logger.debug("流式日志处理线程启动")
        
        while not self._stop_event.is_set():
            try:
                # 从队列获取日志条目（阻塞，但有超时）
                try:
                    log_type, log_entry = self.log_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                try:
                    # 写入文件
                    self._write_log_to_file(log_type, log_entry)
                    
                    # 如果启用详细JSON日志，同时在控制台输出（通过标准日志系统）
                    if self.verbose_json_logging:
                        log_entry_str = json.dumps(log_entry, ensure_ascii=False, indent=2)
                        if len(log_entry_str) > 1000:
                            log_entry_str = log_entry_str[:1000] + "..."
                        process_logger.debug(f"流式日志记录: {log_entry['type']} - ID: {log_entry.get('id', 'unknown')}")
                
                except Exception as e:
                    process_logger.error(f"处理日志条目失败: {e}")
                
                finally:
                    self.log_queue.task_done()
                    
            except Exception as e:
                if not self._stop_event.is_set():
                    process_logger.error(f"日志处理线程异常: {e}")
        
        process_logger.debug("流式日志处理线程停止")
    
    def shutdown(self) -> None:
        """关闭流式日志处理器"""
        if not self._initialized:
            return
            
        self.logger.info("正在关闭流式日志处理器...")
        self._stop_event.set()
        
        # 等待处理线程结束
        if self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5.0)
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        self.logger.info("流式日志处理器已关闭")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息
        
        Returns:
            包含统计信息的字典
        """
        return {
            "enabled": self.enabled,
            "queue_size": self.log_queue.qsize(),
            "max_queue_size": self.max_queue_size,
            "active_threads": self.executor._max_workers,  # type: ignore
            "input_log_file": str(self.input_log_file),
            "output_log_file": str(self.output_log_file),
            "verbose_json_logging": self.verbose_json_logging
        }


# 全局单例实例
_stream_logger_instance: Optional[StreamLogger] = None


def get_stream_logger() -> StreamLogger:
    """获取流式日志处理器的全局实例
    
    Returns:
        StreamLogger实例
    """
    global _stream_logger_instance
    
    if _stream_logger_instance is None:
        # 使用默认配置初始化
        _stream_logger_instance = StreamLogger()
    
    return _stream_logger_instance


def init_stream_logger(
    log_dir: str = "logs",
    max_workers: int = 4,
    max_queue_size: int = 1000,
    enabled: bool = True,
    verbose_json_logging: bool = False
) -> StreamLogger:
    """初始化流式日志处理器（如果尚未初始化）
    
    Args:
        log_dir: 日志目录
        max_workers: 线程池最大工作线程数
        max_queue_size: 最大队列大小
        enabled: 是否启用流式日志记录
        verbose_json_logging: 是否启用详细的JSON日志记录
        
    Returns:
        初始化的StreamLogger实例
    """
    global _stream_logger_instance
    
    if _stream_logger_instance is None:
        _stream_logger_instance = StreamLogger(
            log_dir=log_dir,
            max_workers=max_workers,
            max_queue_size=max_queue_size,
            enabled=enabled,
            verbose_json_logging=verbose_json_logging
        )
    
    return _stream_logger_instance


def shutdown_stream_logger() -> None:
    """关闭流式日志处理器"""
    global _stream_logger_instance
    
    if _stream_logger_instance is not None:
        _stream_logger_instance.shutdown()
        _stream_logger_instance = None


# 导出公共接口
__all__ = [
    'StreamLogger',
    'LogType',
    'get_stream_logger',
    'init_stream_logger',
    'shutdown_stream_logger'
]