"""
Smart Ollama Proxy - 智能统一日志系统

提供统一的日志记录接口，支持：
1. 分类日志：流程日志、性能监控、数据监控、进度显示
2. 可配置的存储和显示行为
3. 高性能异步处理
4. 进度条支持（循环滚动显示）

设计原则：
- 单一入口，消除冗余
- 分类明确，配置灵活
- 性能优化，关键日志同步
- 向后兼容，平滑迁移
"""

import os
import sys
import time
import uuid
import json as json_module
import threading
import queue
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from enum import Enum
from typing import Dict, Any, Optional, Union, List, Callable, Tuple, cast

from utils import json, sanitize_unicode_string


# ============ 枚举定义 ============

class LogLevel(Enum):
    """日志级别枚举"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogType(Enum):
    """日志类型枚举"""
    PROCESS = "process"        # 流程日志：常规操作日志
    PERFORMANCE = "performance"  # 性能监控：耗时统计、性能指标
    DATA = "data"             # 数据监控：请求/响应数据统计
    PROGRESS = "progress"     # 进度显示：循环滚动进度条


# ============ 配置类 ============

class ProgressConfig:
    """进度条配置"""
    
    def __init__(self, config_data: Dict[str, Any]):
        self.enabled = config_data.get("enabled", True)
        self.width = config_data.get("width", 30)  # 减小默认宽度
        self.fill_char = config_data.get("fill_char", "|")  # 使用竖线作为填充
        self.empty_char = config_data.get("empty_char", " ")  # 使用空格作为空白
        self.show_percentage = config_data.get("show_percentage", True)
        self.show_elapsed_time = config_data.get("show_elapsed_time", True)


class LogTypeConfig:
    """日志类型配置"""
    
    def __init__(self, config_data: Dict[str, Any]):
        self.enabled = config_data.get("enabled", True)
        self.save_to_file = config_data.get("save_to_file", True)
        self.show_in_console = config_data.get("show_in_console", True)
        self.async_mode = config_data.get("async_mode", True)  # 默认异步处理


class LogConfig:
    """日志配置管理"""
    
    def __init__(self, config_data: Dict[str, Any]):
        """初始化日志配置
        
        Args:
            config_data: 配置字典，通常来自YAML的logging部分
        """
        self.enabled = config_data.get("enabled", True)
        self.log_dir = Path(config_data.get("log_dir", "logs"))
        self.log_level = LogLevel(config_data.get("log_level", "INFO").upper())
        
        # 类型配置
        log_types_config = config_data.get("log_types", {})
        self.type_configs = {
            LogType.PROCESS: LogTypeConfig(log_types_config.get("process", {})),
            LogType.PERFORMANCE: LogTypeConfig(log_types_config.get("performance", {})),
            LogType.DATA: LogTypeConfig(log_types_config.get("data", {})),
            LogType.PROGRESS: LogTypeConfig(log_types_config.get("progress", {}))
        }
        
        # 性能配置
        perf_config = config_data.get("performance", {})
        self.max_queue_size = perf_config.get("max_queue_size", 1000)
        self.max_workers = perf_config.get("max_workers", 4)
        self.flush_interval = perf_config.get("flush_interval", 1.0)
        
        # 进度条配置
        self.progress_config = ProgressConfig(config_data.get("progress", {}))
        
        # 文件轮转配置
        rotation_config = config_data.get("file_rotation", {})
        self.max_file_size_mb = rotation_config.get("max_size_mb", 100)
        self.backup_count = rotation_config.get("backup_count", 5)
        
        # 确保日志目录存在
        self.log_dir.mkdir(exist_ok=True)
    
    def is_type_enabled(self, log_type: LogType) -> bool:
        """检查日志类型是否启用"""
        return self.enabled and self.type_configs[log_type].enabled
    
    def should_save_to_file(self, log_type: LogType) -> bool:
        """是否保存到文件"""
        return self.is_type_enabled(log_type) and self.type_configs[log_type].save_to_file
    
    def should_show_in_console(self, log_type: LogType) -> bool:
        """是否在控制台显示"""
        return self.is_type_enabled(log_type) and self.type_configs[log_type].show_in_console
    
    def should_process_sync(self, log_type: LogType) -> bool:
        """是否同步处理（false表示异步）"""
        return not self.type_configs[log_type].async_mode
    
    def get_log_file_path(self, log_type: LogType) -> Path:
        """获取日志文件路径"""
        timestamp = datetime.now().strftime('%Y%m%d')
        filename = f"{log_type.value}_{timestamp}.jsonl"
        return self.log_dir / filename


# ============ 处理器 ============

class LogHandler:
    """日志处理器基类"""
    
    def __init__(self, config: LogConfig):
        self.config = config
    
    def handle(self, log_entry: Dict[str, Any]) -> None:
        """处理日志条目"""
        raise NotImplementedError


class FileHandler(LogHandler):
    """文件处理器"""
    
    def __init__(self, config: LogConfig):
        super().__init__(config)
        self._file_handles: Dict[LogType, Any] = {}
        self._locks: Dict[LogType, threading.Lock] = {
            log_type: threading.Lock() for log_type in LogType
        }
    
    def handle(self, log_entry: Dict[str, Any]) -> None:
        """写入日志到文件"""
        log_type = LogType(log_entry.get("type"))
        
        if not self.config.should_save_to_file(log_type):
            return
        
        file_path = self.config.get_log_file_path(log_type)
        
        with self._locks[log_type]:
            try:
                # 检查文件大小，必要时轮转
                self._check_and_rotate(file_path, log_type)
                
                # 写入日志
                with open(file_path, 'a', encoding='utf-8') as f:
                    json_str = json.dumps(log_entry, ensure_ascii=False)
                    f.write(json_str + '\n')
            except Exception as e:
                # 文件写入失败，记录到控制台
                print(f"[FileHandler error] 写入日志文件失败: {e}")
    
    def _check_and_rotate(self, file_path: Path, log_type: LogType) -> None:
        """检查文件大小并执行轮转"""
        if not file_path.exists():
            return
        
        max_size_bytes = self.config.max_file_size_mb * 1024 * 1024
        
        if file_path.stat().st_size > max_size_bytes:
            # 执行轮转
            for i in range(self.config.backup_count - 1, 0, -1):
                old_file = file_path.with_suffix(f".{i}.jsonl")
                new_file = file_path.with_suffix(f".{i+1}.jsonl")
                if old_file.exists():
                    old_file.rename(new_file)
            
            # 重命名当前文件为.1
            backup_file = file_path.with_suffix(".1.jsonl")
            file_path.rename(backup_file)


class ConsoleHandler(LogHandler):
    """控制台处理器"""
    
    def handle(self, log_entry: Dict[str, Any]) -> None:
        """在控制台显示日志"""
        log_type = LogType(log_entry.get("type"))
        
        if not self.config.should_show_in_console(log_type):
            return
        
        # 进度条日志特殊处理
        if log_type == LogType.PROGRESS:
            # 进度条已经在ProgressBar中渲染，这里跳过
            return
        
        # 普通日志格式化
        level = log_entry.get("level", "INFO")
        message = log_entry.get("message", "")
        timestamp = log_entry.get("timestamp_iso", "")
        
        # 格式化输出
        if log_type == LogType.PERFORMANCE:
            # 性能日志特殊格式
            print(f"[PERF {timestamp}] {level}: {message}")
        elif log_type == LogType.DATA:
            # 数据日志简略显示
            data_preview = str(log_entry.get("data", ""))[:100]
            print(f"[DATA {timestamp}] {level}: {data_preview}...")
        else:
            # 流程日志标准格式
            print(f"[{timestamp}] {level}: {message}")


class NullHandler(LogHandler):
    """空处理器，用于禁用的日志类型"""
    
    def handle(self, log_entry: Dict[str, Any]) -> None:
        """什么都不做"""
        pass


# ============ 进度条 ============

class ProgressBar:
    """进度条实现，支持超紧凑ASCII设计和循环滚动显示"""
    
    def __init__(self, total: int, description: str, config: ProgressConfig, bar_id: str):
        self.total = total
        self.current = 0
        self.description = description
        self.config = config
        self.bar_id = bar_id
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self._closed = False
        self.extra_info = ""  # 额外信息，如字节数、chunk数
        self.animation_frame = 0  # 动画帧数，用于循环模式
        
        # 初始显示
        self._render()
    
    def update(self, advance: int = 1, description: Optional[str] = None, extra_info: Optional[str] = None) -> None:
        """更新进度"""
        if self._closed:
            return
        
        self.current = min(self.current + advance, self.total)
        if description:
            self.description = description
        if extra_info is not None:
            self.extra_info = extra_info
        
        # 控制更新频率，避免过度渲染（每100ms最多更新一次）
        current_time = time.time()
        if current_time - self.last_update_time >= 0.1:
            self._render()
            self.last_update_time = current_time
    
    def _render(self) -> None:
        """渲染进度条到控制台"""
        if not self.config.enabled:
            return
        
        # 计算进度百分比
        percentage = (self.current / self.total) * 100 if self.total > 0 else 0
        
        # 构建进度条
        bar = self._build_compact_progress_bar()
        
        # 构建显示文本
        parts = []
        if self.description:
            parts.append(self.description)
        
        parts.append(bar)
        
        if self.config.show_percentage:
            parts.append(f"{percentage:.1f}%")
        
        if self.config.show_elapsed_time:
            elapsed = time.time() - self.start_time
            parts.append(f"{elapsed:.1f}s")
        
        # 添加额外信息
        if self.extra_info:
            parts.append(self.extra_info)
        
        # 使用回车符实现原地更新
        sys.stdout.write("\r" + " ".join(parts))
        sys.stdout.flush()
    
    def _build_compact_progress_bar(self) -> str:
        """构建超紧凑ASCII进度条字符串"""
        # 如果总大小为0或未知，使用紧凑循环模式
        if self.total <= 0:
            return self._build_compact_cyclic_bar()
        
        # 计算填充宽度（使用10个字符的微型进度条）
        compact_width = 10
        filled_width = int(compact_width * self.current / self.total)
        
        # 超紧凑ASCII进度条设计：使用方括号作为边界，#作为填充，.作为空白
        left_boundary = "["
        right_boundary = "]"
        
        # 构建进度条内部
        if filled_width == 0:
            # 空进度条
            inner_bar = "." * compact_width
        elif filled_width == compact_width:
            # 满进度条
            inner_bar = "#" * compact_width
        else:
            # 部分填充
            inner_bar = "#" * filled_width + "." * (compact_width - filled_width)
        
        return f"{left_boundary}{inner_bar}{right_boundary}"
    
    def _build_compact_cyclic_bar(self) -> str:
        """构建超紧凑循环进度条（用于未知总大小的情况）"""
        # 超紧凑循环进度条设计：五个>>>>>字符正向循环
        compact_width = 10
        block_width = 5  # 使用五个>字符作为活动块
        
        # 更新动画帧 - 简单的正向循环
        # 当第一个>超过右边界时，整个块从左边重新开始
        self.animation_frame = (self.animation_frame + 1) % compact_width
        
        # 构建进度条
        left_boundary = "["
        right_boundary = "]"
        
        # 计算活动块位置 - 简单的正向循环
        block_start = self.animation_frame
        
        # 构建内部条：五个>>>>>字符在位置间移动
        inner_chars = []
        for i in range(compact_width):
            # 计算字符在块中的位置（考虑循环）
            pos_in_bar = i
            # 检查当前位置是否在活动块内
            in_block = False
            for j in range(block_width):
                check_pos = (block_start + j) % compact_width
                if pos_in_bar == check_pos:
                    in_block = True
                    break
            
            if in_block:
                inner_chars.append(">")
            else:
                inner_chars.append(".")
        
        inner_bar = "".join(inner_chars)
        return f"{left_boundary}{inner_bar}{right_boundary}"
    
    def close(self) -> None:
        """关闭进度条"""
        if not self._closed:
            self._closed = True
            # 移动到新行
            sys.stdout.write("\n")
            sys.stdout.flush()


class ProgressManager:
    """进度管理器"""
    
    def __init__(self, config: LogConfig):
        self.config = config
        self._active_bars: Dict[str, ProgressBar] = {}
        self._lock = threading.Lock()
    
    def create(self, total: int, description: str = "", bar_id: Optional[str] = None) -> ProgressBar:
        """创建进度条
        
        Args:
            total: 总任务数
            description: 进度条描述
            bar_id: 进度条ID，如果为None则自动生成
            
        Returns:
            ProgressBar实例
        """
        if not self.config.is_type_enabled(LogType.PROGRESS):
            # 如果进度显示禁用，返回一个虚拟进度条
            return self._create_dummy_bar()
        
        bar_id = bar_id or str(uuid.uuid4())
        
        with self._lock:
            bar = ProgressBar(
                total=total,
                description=description,
                config=self.config.progress_config,
                bar_id=bar_id
            )
            self._active_bars[bar_id] = bar
            return bar
    
    def _create_dummy_bar(self) -> ProgressBar:
        """创建虚拟进度条（当进度显示禁用时）"""
        class DummyProgressBar(ProgressBar):
            def __init__(self):
                # 创建一个禁用的配置
                dummy_config = ProgressConfig({"enabled": False})
                super().__init__(total=0, description="", config=dummy_config, bar_id="dummy")
                self._closed = True
            
            def update(self, advance: int = 1, description: Optional[str] = None, extra_info: Optional[str] = None) -> None:
                pass
            
            def close(self) -> None:
                pass

        return DummyProgressBar()
    
    def update(self, bar_id: str, advance: int = 1, description: Optional[str] = None, extra_info: Optional[str] = None) -> None:
        """更新进度条"""
        with self._lock:
            bar = self._active_bars.get(bar_id)
            if bar:
                bar.update(advance, description, extra_info)
    
    def close(self, bar_id: str) -> None:
        """关闭进度条"""
        with self._lock:
            bar = self._active_bars.pop(bar_id, None)
            if bar:
                bar.close()


# ============ 日志分发器 ============

class LogDispatcher:
    """日志分发器，处理同步和异步日志"""
    
    def __init__(self, config: LogConfig):
        self.config = config
        self.async_queue = queue.Queue(maxsize=config.max_queue_size)
        self.executor = ThreadPoolExecutor(
            max_workers=config.max_workers,
            thread_name_prefix="smart_logger"
        )
        self._stop_event = threading.Event()
        
        # 处理器
        self.handlers = {
            "file": FileHandler(config),
            "console": ConsoleHandler(config),
            "null": NullHandler(config)
        }
        
        # 启动异步处理线程
        self._processing_thread = threading.Thread(
            target=self._process_async_queue,
            name="smart_logger_processor",
            daemon=True
        )
        self._processing_thread.start()
        
        # 内部日志器（用于记录日志系统自身的问题）
        self._internal_logger = logging.getLogger("smart_ollama_proxy.smart_logger")
    
    def _create_log_entry(self, log_type: LogType, level: LogLevel, 
                         message: str, **kwargs) -> Dict[str, Any]:
        """创建日志条目"""
        entry = {
            "id": str(uuid.uuid4()),
            "type": log_type.value,
            "level": level.value,
            "timestamp": time.time(),
            "timestamp_iso": datetime.now().isoformat(),
            "message": message,
            **kwargs
        }
        return self._sanitize_entry(entry)
    
    def _sanitize_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """清理日志条目中的无效字符"""
        def clean_value(value):
            if isinstance(value, str):
                return sanitize_unicode_string(value)
            elif isinstance(value, dict):
                return {k: clean_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [clean_value(item) for item in value]
            else:
                return value
        
        return cast(Dict[str, Any], clean_value(entry))
    
    def process_sync(self, log_type: LogType, level: LogLevel, 
                    message: str, **kwargs) -> None:
        """同步处理日志"""
        if not self.config.is_type_enabled(log_type):
            return
        
        log_entry = self._create_log_entry(log_type, level, message, **kwargs)
        self._process_log_entry(log_entry)
    
    def process_async(self, log_type: LogType, level: LogLevel,
                     message: str, **kwargs) -> None:
        """异步处理日志（放入队列）"""
        if not self.config.is_type_enabled(log_type):
            return
        
        log_entry = self._create_log_entry(log_type, level, message, **kwargs)
        
        try:
            self.async_queue.put_nowait(log_entry)
        except queue.Full:
            # 队列满时，同步处理重要日志（WARNING及以上）
            if level in [LogLevel.WARNING, LogLevel.ERROR, LogLevel.CRITICAL]:
                self._process_log_entry(log_entry)
            else:
                self._internal_logger.warning(f"日志队列已满，丢弃日志: {message[:100]}...")
    
    def _process_log_entry(self, log_entry: Dict[str, Any]) -> None:
        """处理单个日志条目"""
        try:
            # 文件处理器
            if self.config.should_save_to_file(LogType(log_entry.get("type"))):
                self.handlers["file"].handle(log_entry)
            
            # 控制台处理器
            if self.config.should_show_in_console(LogType(log_entry.get("type"))):
                self.handlers["console"].handle(log_entry)
                
        except Exception as e:
            self._internal_logger.error(f"处理日志条目失败: {e}")
    
    def _process_async_queue(self) -> None:
        """异步处理队列的线程函数"""
        while not self._stop_event.is_set():
            try:
                # 从队列获取日志条目（阻塞，但有超时）
                try:
                    log_entry = self.async_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                
                # 处理日志条目
                self._process_log_entry(log_entry)
                
                # 标记任务完成
                self.async_queue.task_done()
                
            except Exception as e:
                if not self._stop_event.is_set():
                    self._internal_logger.error(f"日志处理线程异常: {e}")
    
    def shutdown(self) -> None:
        """关闭日志分发器"""
        self._stop_event.set()
        
        # 等待处理线程结束
        if self._processing_thread.is_alive():
            self._processing_thread.join(timeout=5.0)
        
        # 关闭线程池
        self.executor.shutdown(wait=True)
        
        self._internal_logger.info("日志分发器已关闭")


# ============ 日志分类器 ============

class LogCategory:
    """日志分类器，提供类型化的日志接口"""
    
    def __init__(self, logger: 'SmartLogger', log_type: LogType):
        self.logger = logger
        self.log_type = log_type
    
    def debug(self, message: str, **kwargs) -> None:
        """记录DEBUG级别日志"""
        self.logger.log(self.log_type, LogLevel.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        """记录INFO级别日志"""
        self.logger.log(self.log_type, LogLevel.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs) -> None:
        """记录WARNING级别日志"""
        self.logger.log(self.log_type, LogLevel.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        """记录ERROR级别日志"""
        self.logger.log(self.log_type, LogLevel.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        """记录CRITICAL级别日志"""
        self.logger.log(self.log_type, LogLevel.CRITICAL, message, **kwargs)
    
    def record(self, key: str, value: Any, level: LogLevel = LogLevel.INFO) -> None:
        """记录数据（用于DATA和PERFORMANCE类型）"""
        if self.log_type not in [LogType.DATA, LogType.PERFORMANCE]:
            raise ValueError("record方法仅用于DATA和PERFORMANCE类型的日志")
        
        self.logger.log(self.log_type, level, f"记录数据: {key}", data={key: value})
    
    def start_timer(self, timer_name: str) -> None:
        """开始计时器（仅用于PERFORMANCE类型）"""
        if self.log_type != LogType.PERFORMANCE:
            raise ValueError("start_timer方法仅用于PERFORMANCE类型的日志")
        
        self.logger._start_timer(timer_name)
    
    def stop_timer(self, timer_name: str) -> float:
        """停止计时器并返回耗时（仅用于PERFORMANCE类型）"""
        if self.log_type != LogType.PERFORMANCE:
            raise ValueError("stop_timer方法仅用于PERFORMANCE类型的日志")
        
        return self.logger._stop_timer(timer_name)


# ============ 主日志类 ============

class SmartLogger:
    """智能日志记录器（单例模式）"""
    
    _instance: Optional['SmartLogger'] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config: Optional[LogConfig] = None):
        """初始化智能日志记录器
        
        Args:
            config: 日志配置，如果为None则使用默认配置
        """
        if getattr(self, '_initialized', False):
            return
        
        self.config = config or self._create_default_config()
        self.dispatcher = LogDispatcher(self.config)
        self._progress_manager = ProgressManager(self.config)
        
        # 分类日志器
        self.process = LogCategory(self, LogType.PROCESS)
        self.performance = LogCategory(self, LogType.PERFORMANCE)
        self.data = LogCategory(self, LogType.DATA)
        
        # 进度管理器作为progress属性
        self.progress = self._progress_manager
        
        # 计时器缓存（用于性能监控）
        self._timers: Dict[str, float] = {}
        self._timers_lock = threading.Lock()
        
        # 内部日志器
        self._internal_logger = logging.getLogger("smart_ollama_proxy.smart_logger")
        
        self._initialized = True
        self._internal_logger.info("智能日志记录器初始化完成")
    
    def _create_default_config(self) -> LogConfig:
        """创建默认配置"""
        default_config = {
            "enabled": True,
            "log_dir": "logs",
            "log_level": "INFO",
            "log_types": {
                "process": {
                    "enabled": True,
                    "save_to_file": True,
                    "show_in_console": True,
                    "async_mode": True
                },
                "performance": {
                    "enabled": True,
                    "save_to_file": True,
                    "show_in_console": True,
                    "async_mode": False  # 性能日志需要即时性
                },
                "data": {
                    "enabled": True,
                    "save_to_file": True,
                    "show_in_console": False,
                    "async_mode": True
                },
                "progress": {
                    "enabled": True,
                    "save_to_file": False,  # 进度条不保存
                    "show_in_console": True,
                    "async_mode": False  # 进度显示需要即时
                }
            },
            "performance": {
                "max_queue_size": 1000,
                "max_workers": 4,
                "flush_interval": 1.0
            },
            "progress": {
                "width": 30,  # 减小默认宽度
                "fill_char": "|",  # 使用竖线作为填充
                "empty_char": " ",  # 使用空格作为空白
                "show_percentage": True,
                "show_elapsed_time": True
            },
            "file_rotation": {
                "max_size_mb": 100,
                "backup_count": 5
            }
        }
        return LogConfig(default_config)
    
    def log(self, log_type: LogType, level: LogLevel, message: str, **kwargs) -> None:
        """通用日志方法
        
        Args:
            log_type: 日志类型
            level: 日志级别
            message: 日志消息
            **kwargs: 额外字段
        """
        # 检查日志级别是否满足配置要求
        if not self._should_log(level):
            return
        
        # 根据配置决定同步还是异步处理
        if self.config.should_process_sync(log_type):
            self.dispatcher.process_sync(log_type, level, message, **kwargs)
        else:
            self.dispatcher.process_async(log_type, level, message, **kwargs)
    
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
        current_priority = level_priority.get(self.config.log_level, 20)
        msg_priority = level_priority.get(level, 20)
        return msg_priority >= current_priority
    
    def _start_timer(self, timer_name: str) -> None:
        """开始计时器"""
        with self._timers_lock:
            self._timers[timer_name] = time.time()
    
    def _stop_timer(self, timer_name: str) -> float:
        """停止计时器并返回耗时（秒）"""
        with self._timers_lock:
            start_time = self._timers.pop(timer_name, None)
            if start_time is None:
                return 0.0
            return time.time() - start_time
    
    def shutdown(self) -> None:
        """关闭智能日志记录器"""
        if not self._initialized:
            return
        
        self._internal_logger.info("正在关闭智能日志记录器...")
        self.dispatcher.shutdown()
        self._internal_logger.info("智能日志记录器已关闭")
        self._initialized = False


# ============ 全局实例和便利函数 ============

_smart_logger_instance: Optional[SmartLogger] = None


def get_smart_logger() -> SmartLogger:
    """获取智能日志记录器的全局实例
    
    Returns:
        SmartLogger实例
    """
    global _smart_logger_instance
    
    if _smart_logger_instance is None:
        _smart_logger_instance = SmartLogger()
    
    return _smart_logger_instance


def init_smart_logger(config_data: Dict[str, Any]) -> SmartLogger:
    """初始化智能日志记录器（如果尚未初始化）
    
    Args:
        config_data: 配置数据字典
        
    Returns:
        初始化的SmartLogger实例
    """
    global _smart_logger_instance
    
    if _smart_logger_instance is None:
        config = LogConfig(config_data)
        _smart_logger_instance = SmartLogger(config)
    
    return _smart_logger_instance


def shutdown_smart_logger() -> None:
    """关闭智能日志记录器"""
    global _smart_logger_instance
    
    if _smart_logger_instance is not None:
        _smart_logger_instance.shutdown()
        _smart_logger_instance = None


# ============ 标准logging适配器 ============

class StandardLoggingAdapter(logging.Handler):
    """将标准logging适配到SmartLogger"""
    
    def __init__(self, smart_logger: Optional[SmartLogger] = None):
        super().__init__()
        self.smart_logger = smart_logger or get_smart_logger()
        
        # 设置格式化器
        formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
        self.setFormatter(formatter)
    
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
            
            # 推断日志类型
            log_type = self._infer_log_type(record)
            
            # 提取额外字段
            extra_fields = self._extract_extra_fields(record)
            
            # 记录到SmartLogger
            self.smart_logger.log(log_type, level, message, **extra_fields)
            
        except Exception as e:
            # 避免循环错误
            print(f"[StandardLoggingAdapter error] {e}")
    
    def _infer_log_type(self, record: logging.LogRecord) -> LogType:
        """根据日志记录推断日志类型"""
        # 检查是否有显式的log_type属性
        log_type = getattr(record, 'log_type', None)
        if log_type:
            try:
                return LogType(log_type)
            except ValueError:
                pass
        
        # 根据logger名称推断
        logger_name = record.name.lower()
        if 'performance' in logger_name or 'perf' in logger_name:
            return LogType.PERFORMANCE
        elif 'data' in logger_name:
            return LogType.DATA
        else:
            return LogType.PROCESS
    
    def _extract_extra_fields(self, record: logging.LogRecord) -> Dict[str, Any]:
        """从LogRecord提取额外字段"""
        extra_fields = {}
        
        # 常见字段
        fields = ['router', 'model', 'stream', 'request_id', 'session_id', 'endpoint']
        for field in fields:
            value = getattr(record, field, None)
            if value is not None:
                extra_fields[field] = value
        
        return extra_fields


def setup_logging_integration(
    logger_name: str = "smart_ollama_proxy",
    level: Union[int, str] = logging.INFO,
    propagate: bool = False,
    smart_logger: Optional[SmartLogger] = None
) -> None:
    """设置标准logging模块与SmartLogger的集成
    
    Args:
        logger_name: 要配置的logger名称，默认根logger
        level: 日志级别
        propagate: 是否向上传播
        smart_logger: 可选的SmartLogger实例，如果为None则使用全局单例
    """
    # 获取或创建SmartLogger实例
    if smart_logger is None:
        smart_logger = get_smart_logger()
    
    # 创建适配器
    adapter = StandardLoggingAdapter(smart_logger)
    
    # 配置指定logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = propagate
    
    # 移除现有适配器（避免重复）
    for handler in logger.handlers[:]:
        if isinstance(handler, StandardLoggingAdapter):
            logger.removeHandler(handler)
    
    # 添加新的适配器
    logger.addHandler(adapter)
    
    # 记录配置完成
    smart_logger.process.info(f"标准logging模块集成完成，logger: {logger_name}, 级别: {level}")


def configure_root_logging(
    level: Union[int, str] = logging.INFO,
    smart_logger: Optional[SmartLogger] = None
) -> None:
    """配置根logger使用SmartLogger"""
    setup_logging_integration(
        logger_name="",
        level=level,
        propagate=False,
        smart_logger=smart_logger
    )


# ============ 导出 ============

__all__ = [
    # 核心类
    'SmartLogger',
    'LogConfig',
    'LogType',
    'LogLevel',
    
    # 便利函数
    'get_smart_logger',
    'init_smart_logger',
    'shutdown_smart_logger',
    
    # 适配器
    'StandardLoggingAdapter',
    'setup_logging_integration',
    'configure_root_logging',
    
    # 进度管理
    'ProgressManager',
    'ProgressBar',
]