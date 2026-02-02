"""
配置加载和模型路由模块
"""
import os
import yaml
import logging
from typing import Dict, Any, Optional, List, Tuple
import httpx
import asyncio

# Unified logger imports (migrated to smart_logger)
from smart_logger import LogConfig, LogType, LogLevel

logger = logging.getLogger("smart_ollama_proxy.config")


def deep_merge(default: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并两个字典，用户配置覆盖默认配置"""
    if not isinstance(default, dict) or not isinstance(user, dict):
        return user if user is not None else default
    
    merged = default.copy()
    for key, value in user.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_env_file(env_path: str = ".env") -> None:
    """加载.env文件到环境变量（简易实现）"""
    if not os.path.exists(env_path):
        logger.debug(f"未找到.env文件: {env_path}")
        return
    
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释
                if not line or line.startswith('#'):
                    continue
                # 解析键值对
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # 移除值两端的引号
                    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    # 设置环境变量（如果尚未设置）
                    if key and key not in os.environ:
                        os.environ[key] = value
                        logger.debug(f"从.env文件设置环境变量: {key}")
    except Exception as e:
        logger.warning(f"加载.env文件失败: {e}")


# 自动加载.env文件（如果存在）
load_env_file()


class BackendConfig:
    """后端配置"""
    
    def __init__(self, config_data: Dict[str, Any], backend_mode: Optional[str] = None, proxy_config: Optional[Dict[str, Any]] = None, model_group: Optional[str] = None):
        self.base_url = config_data.get("base_url", "")
        self.api_key = config_data.get("api_key", "")
        self.timeout = config_data.get("timeout", 30)
        self.model_group = model_group
        
        # 环境变量覆盖：优先从环境变量读取API密钥
        if self.model_group:
            # 构建环境变量名：{模型组大写}_API_KEY
            env_var_name = f"{self.model_group.upper().replace('-', '_')}_API_KEY"
            env_api_key = os.environ.get(env_var_name)
            if env_api_key and env_api_key.strip():
                self.api_key = env_api_key.strip()
                logger.debug(f"从环境变量 {env_var_name} 读取API密钥")
            # 如果配置中的api_key是占位符，且环境变量不存在，可以记录警告
            elif self.api_key and ("your-" in self.api_key or "***" in self.api_key):
                logger.warning(f"API密钥是占位符，请设置环境变量 {env_var_name} 或直接修改配置")
        self.headers = config_data.get("headers", {})
        self.model_mapping = config_data.get("model_mapping", {})
        
        # LiteLLM 配置
        self.use_litellm = config_data.get("use_litellm", True)  # 默认启用LiteLLM（如果已安装）
        self.litellm_params = config_data.get("litellm_params", {})  # LiteLLM专用参数
        
        # 后端类型配置（可选）
        self.backend_type = config_data.get("backend_type")  # openai, openai_sdk, litellm, http, ollama, mock
        
        # 后端模式（openai_backend, litellm_backend等）
        self.backend_mode = backend_mode
        
        # 流式缓冲区配置
        self.stream_buffer_size = config_data.get("stream_buffer_size", 16384)  # 默认16KB
        self.stream_log_frequency = config_data.get("stream_log_frequency", 1000)  # 日志记录频率，提高以减少日志量
        self.log_full_stream_data = config_data.get("log_full_stream_data", False)  # 是否记录完整流式数据
        
        # HTTP压缩配置
        self.proxy_config = proxy_config or {}
        # 优先使用后端配置的compression_enabled，其次使用代理全局配置http_compression_enabled，默认True
        if "compression_enabled" in config_data:
            self.compression_enabled = config_data.get("compression_enabled", True)
        else:
            self.compression_enabled = self.proxy_config.get("http_compression_enabled", True)
        
        # 确保有基本的Content-Type头
        if "content-type" not in self.headers and "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "application/json"
        
        # 添加Authorization头
        if self.api_key:
            # 检查是否是Claude API（需要x-api-key）
            if "anthropic.com" in self.base_url:
                self.headers["x-api-key"] = self.api_key
            else:
                self.headers["Authorization"] = f"Bearer {self.api_key}"


class ModelConfig:
    """模型配置"""
    
    def __init__(self, model_group: str, config_data: Dict[str, Any], proxy_config: Optional[Dict[str, Any]] = None):
        self.model_group = model_group
        self.description = config_data.get("description", "")
        self.proxy_config = proxy_config or {}
        # available_models 现在是一个字典，键为模型名，值为配置
        available_models_dict = config_data.get("available_models", {})
        self.available_models = list(available_models_dict.keys())  # 保持列表兼容性
        self.model_details: Dict[str, Dict[str, Any]] = {}
        
        # 解析每个模型的详细配置
        for model_name, model_config in available_models_dict.items():
            self.model_details[model_name] = {
                "context_length": model_config.get("context_length", 4096),
                "embedding_length": model_config.get("embedding_length", 0),
                "capabilities": model_config.get("capabilities", ["completion"]),
                "actual_model": model_config.get("actual_model", model_name)
            }
        
        self.backends: Dict[str, BackendConfig] = {}
        self.backend_order: List[str] = []  # 保持后端配置的顺序
        
        # 加载所有后端配置
        for key, value in config_data.items():
            if key.endswith("_backend"):
                backend_name = key
                backend_config = BackendConfig(value, backend_mode=backend_name, proxy_config=self.proxy_config, model_group=self.model_group)
                self.backends[backend_name] = backend_config
                self.backend_order.append(backend_name)
    
    def get_backend(self, backend_mode: str = "openai_backend") -> Optional[BackendConfig]:
        """获取指定后端模式的配置"""
        return self.backends.get(backend_mode)
    
    def get_ordered_backends(self) -> List[BackendConfig]:
        """获取按配置顺序排列的后端配置列表"""
        return [self.backends[name] for name in self.backend_order if name in self.backends]
    
    def get_actual_model(self, virtual_model: str, backend_mode: str = "openai_backend") -> Optional[str]:
        """获取实际模型名称"""
        backend = self.get_backend(backend_mode)
        if not backend:
            return None
        
        # 从模型详情中获取实际模型名
        if virtual_model in self.model_details:
            return self.model_details[virtual_model]["actual_model"]
        
        # 如果没有详情，使用虚拟模型名
        return virtual_model
    
    def get_model_context_length(self, model_name: str) -> int:
        """获取模型的上下文长度"""
        if model_name in self.model_details:
            return self.model_details[model_name]["context_length"]
        return 4096  # 默认值
    
    def get_model_embedding_length(self, model_name: str) -> int:
        """获取模型的嵌入长度"""
        if model_name in self.model_details:
            return self.model_details[model_name]["embedding_length"]
        return 0
    
    def get_model_capabilities(self, model_name: str) -> List[str]:
        """获取模型的能力列表"""
        if model_name in self.model_details:
            return self.model_details[model_name]["capabilities"]
        return ["completion"]


class ConfigLoader:
    """配置加载器"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config_data: Dict[str, Any] = {}
        self.models: Dict[str, ModelConfig] = {}
        self.routing_config: Dict[str, Any] = {}
        self.proxy_config: Dict[str, Any] = {}
        self.local_ollama_config: Dict[str, Any] = {}
        # 模型配置缓存（性能优化：避免重复查找）
        self._model_config_cache: Dict[str, Optional[Tuple[ModelConfig, str]]] = {}
        # 模型名到模型组的映射（性能优化：快速查找）
        self._model_to_group_map: Dict[str, str] = {}
        
    def load(self) -> bool:
        """加载配置文件"""
        try:
            if not os.path.exists(self.config_path):
                logger.warning(f"配置文件不存在: {self.config_path}")
                return False
            
            # 加载主配置文件
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config_data = yaml.safe_load(f)
            
            # 尝试加载本地配置文件（如果存在）
            local_config_path = self._get_local_config_path()
            if local_config_path and os.path.exists(local_config_path):
                logger.info(f"检测到本地配置文件: {local_config_path}")
                try:
                    with open(local_config_path, 'r', encoding='utf-8') as f:
                        local_config = yaml.safe_load(f)
                    
                    if local_config:
                        # 深度合并：本地配置覆盖主配置
                        self.config_data = deep_merge(self.config_data, local_config)
                        logger.info("本地配置文件已合并到主配置")
                except Exception as e:
                    logger.warning(f"加载本地配置文件失败，跳过: {e}")
            
            # 加载各配置部分
            self.proxy_config = self.config_data.get("proxy", {})
            self.local_ollama_config = self.config_data.get("local_ollama", {})
            self.routing_config = self.config_data.get("routing", {})
            
            # 加载模型配置
            models_data = self.config_data.get("models", {})
            for model_group, model_data in models_data.items():
                model_config = ModelConfig(model_group, model_data, proxy_config=self.proxy_config)
                self.models[model_group] = model_config
                
                # 构建模型名到模型组的映射（性能优化）
                for model_name in model_config.available_models:
                    self._model_to_group_map[model_name] = model_group
                    # 同时添加带组名的映射，支持"组名/模型名"格式
                    full_model_name = f"{model_group}/{model_name}"
                    self._model_to_group_map[full_model_name] = model_group
            
            # 清空配置缓存（配置重新加载后需要重建）
            self._model_config_cache.clear()
            
            logger.info(f"配置加载成功: {self.config_path}")
            logger.info(f"加载了 {len(self.models)} 个模型组")
            return True
            
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            return False
    
    def get_model_config(self, model_name: str) -> Optional[Tuple[ModelConfig, str]]:
        """
        根据模型名称获取模型配置（带缓存优化）
        支持两种格式：
        1. 纯模型名：deepseek-chat
        2. 带组名的模型名：deepseek/deepseek-chat
        
        Returns:
            (ModelConfig, actual_model_name) 或 None
        """
        # 检查缓存（性能优化）
        if model_name in self._model_config_cache:
            cached_result = self._model_config_cache[model_name]
            logger.debug(f"从缓存获取模型配置: {model_name}")
            return cached_result
        
        logger.debug(f"查找模型配置: {model_name}")
        result = None
        actual_model_name = model_name
        
        # 首先检查是否是带组名的模型名（格式：组名/模型名）
        if '/' in model_name:
            parts = model_name.split('/', 1)
            if len(parts) == 2:
                group_name, inner_model_name = parts
                model_config = self.models.get(group_name)
                if model_config:
                    # 检查该组是否包含这个模型
                    if inner_model_name in model_config.available_models:
                        logger.debug(f"找到带组名的模型 {model_name} (组: {group_name}, 模型: {inner_model_name})")
                        result = (model_config, inner_model_name)
                    else:
                        logger.debug(f"组 {group_name} 中不存在模型 {inner_model_name}")
                else:
                    logger.debug(f"组 {group_name} 不存在")
        
        # 如果不是带组名的格式，或者带组名的查找失败，使用原来的查找逻辑
        if result is None:
            # 使用映射表快速查找（性能优化：O(1)查找替代O(n)遍历）
            if model_name in self._model_to_group_map:
                model_group = self._model_to_group_map[model_name]
                model_config = self.models.get(model_group)
                if model_config:
                    logger.debug(f"找到模型 {model_name} 在组 {model_group} 中")
                    result = (model_config, model_name)
            else:
                logger.debug(f"模型 {model_name} 不在任何组的 available_models 中")
                
                # 检查是否是本地模型（local组）
                if "local" in self.models:
                    # 本地模型的available_models为空，表示所有模型都可能是本地的
                    logger.debug(f"模型 {model_name} 作为本地模型处理")
                    result = (self.models["local"], model_name)
        
        if result is None:
            logger.debug(f"未找到模型 {model_name} 的配置")
        
        # 缓存结果（性能优化）
        self._model_config_cache[model_name] = result
        return result
    
    def get_backend_for_model(self, model_name: str, backend_mode: Optional[str] = None) -> Optional[Tuple[BackendConfig, str]]:
        """
        获取模型的后端配置和实际模型名称
        
        Returns:
            (BackendConfig, actual_model_name) 或 None
        """
        if backend_mode is None:
            backend_mode = self.routing_config.get("default_backend_mode", "openai_backend")
        
        # 确保backend_mode是字符串
        backend_mode_str = str(backend_mode)
        
        model_info = self.get_model_config(model_name)
        if not model_info:
            return None
        
        model_config, virtual_model = model_info
        
        # 如果是本地模型，返回None（表示使用本地Ollama）
        if model_config.model_group == "local":
            return None
        
        backend = model_config.get_backend(backend_mode_str)
        if not backend:
            logger.warning(f"模型 {model_name} 不支持后端模式 {backend_mode_str}")
            return None
        
        actual_model = model_config.get_actual_model(virtual_model, backend_mode_str)
        if actual_model is None:
            return None
        
        return backend, actual_model
    
    def get_backends_for_model(self, model_name: str) -> Optional[List[Tuple[BackendConfig, str]]]:
        """
        获取模型的所有后端配置和实际模型名称（按配置顺序）
        
        Returns:
            [(BackendConfig, actual_model_name), ...] 或 None（表示使用本地Ollama）
        """
        model_info = self.get_model_config(model_name)
        if not model_info:
            return None
        
        model_config, virtual_model = model_info
        
        # 如果是本地模型，返回None（表示使用本地Ollama）
        if model_config.model_group == "local":
            return None
        
        # 获取所有按顺序排列的后端配置
        backends = model_config.get_ordered_backends()
        if not backends:
            logger.warning(f"模型 {model_name} 没有配置任何后端")
            return None
        
        result = []
        for backend in backends:
            if backend.backend_mode is None:
                continue
            actual_model = model_config.get_actual_model(virtual_model, backend.backend_mode)  # type: ignore
            if actual_model is not None:
                result.append((backend, actual_model))
        
        if not result:
            logger.warning(f"模型 {model_name} 无法获取任何有效的实际模型名称")
            return None
        
        return result
    
    def get_proxy_config(self) -> Dict[str, Any]:
        """获取代理配置"""
        return self.proxy_config
    
    def get_verbose_json_logging(self) -> bool:
        """获取是否启用详细的JSON日志记录"""
        return self.proxy_config.get("verbose_json_logging", False)
    
    def get_tool_compression_enabled(self) -> bool:
        """获取是否启用工具压缩优化"""
        return self.proxy_config.get("tool_compression_enabled", True)
    
    def get_prompt_compression_enabled(self) -> bool:
        """获取是否启用重复提示词压缩优化"""
        return self.proxy_config.get("prompt_compression_enabled", True)
    
    def get_http_compression_enabled(self) -> bool:
        """获取是否启用HTTP传输压缩（gzip/deflate）"""
        return self.proxy_config.get("http_compression_enabled", True)
    
    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置
        
        Returns:
            日志配置字典，包含智能日志系统的所有配置
        """
        # 从proxy配置中获取日志配置
        logging_config = self.proxy_config.get("logging", {})
        
        # 设置默认值
        default_config = {
            "enabled": True,
            "log_dir": "logs",
            "log_level": self.proxy_config.get("log_level", "INFO"),
            "verbose_json_logging": self.proxy_config.get("verbose_json_logging", False),
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
                "width": 50,
                "fill_char": "█",
                "empty_char": "░",
                "show_percentage": True,
                "show_elapsed_time": True
            },
            "file_rotation": {
                "max_size_mb": 100,
                "backup_count": 5
            }
        }
        
        # 深度合并配置：用户配置覆盖默认配置
        return deep_merge(default_config, logging_config)
    
    def get_unified_logger_config(self) -> LogConfig:
        """获取统一日志记录器的配置（已迁移到smart_logger）
        
        Returns:
            LogConfig 配置对象
        """
        # 获取现有的日志配置
        logging_config = self.get_logging_config()
        
        # 创建并返回LogConfig对象
        return LogConfig(logging_config)
    
    def get_local_ollama_config(self) -> Dict[str, Any]:
        """获取本地Ollama配置"""
        return self.local_ollama_config
    
    def get_all_virtual_models(self) -> List[str]:
        """获取所有虚拟模型名称"""
        models = []
        for model_config in self.models.values():
            models.extend(model_config.available_models)
        
        return list(set(models))  # 去重
    
    def get_all_backend_configs(self) -> Dict[str, BackendConfig]:
        """获取所有后端配置"""
        backend_configs = {}
        
        for model_group, model_config in self.models.items():
            for backend_name, backend_config in model_config.backends.items():
                # 使用组合键: model_group.backend_name
                key = f"{model_group}.{backend_name}"
                backend_configs[key] = backend_config
        
        return backend_configs
    
    def get_backend_config_by_url(self, base_url: str, api_key: str = "") -> Optional[BackendConfig]:
        """根据URL和API密钥查找后端配置"""
        for model_group, model_config in self.models.items():
            for backend_name, backend_config in model_config.backends.items():
                if (backend_config.base_url == base_url and
                    backend_config.api_key == api_key):
                    return backend_config
        
        return None
    
    def _get_local_config_path(self) -> Optional[str]:
        """
        获取本地配置文件路径
        
        检查以下文件（按优先级顺序）：
        1. config.local.yaml
        2. config.personal.yaml
        3. 当前目录下的任何 *.local.yaml 文件
        
        Returns:
            本地配置文件路径，如果不存在则返回 None
        """
        import glob
        
        # 检查的路径列表（按优先级顺序）
        candidate_paths = [
            "config.local.yaml",
            "config.personal.yaml",
        ]
        
        # 检查当前目录下的所有 *.local.yaml 文件
        local_yaml_files = glob.glob("*.local.yaml")
        # 按文件名排序以确保一致性（排除已在候选列表中的文件）
        for file_path in sorted(local_yaml_files):
            if file_path not in candidate_paths:
                candidate_paths.append(file_path)
        
        # 遍历候选路径，返回第一个存在的文件
        for path in candidate_paths:
            if os.path.exists(path):
                return path
        
        return None


class ModelRouter:
    """模型路由器"""
    
    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self.local_models_cache: List[Dict[str, Any]] = []
        self.last_cache_update = 0
        
    async def fetch_local_models(self) -> List[Dict[str, Any]]:
        """从本地Ollama获取模型列表，如果失败则返回空列表（表示没有本地模型）"""
        local_config = self.config_loader.get_local_ollama_config()
        base_url = local_config.get("base_url", "http://localhost:11434")
        timeout = local_config.get("timeout", 60)
        
        logger.info(f"尝试连接本地Ollama: {base_url}/api/tags, 超时: {timeout}秒")
        
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{base_url}/api/tags")
                logger.info(f"本地Ollama响应状态码: {resp.status_code}")
                
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("models", [])
                    logger.info(f"从本地Ollama成功获取了 {len(models)} 个模型")
                    
                    # 记录前几个模型的名称用于调试
                    if models:
                        model_names = [m.get("name", "unknown") for m in models[:3]]
                        logger.info(f"本地模型示例: {model_names}{'...' if len(models) > 3 else ''}")
                    
                    return models
                else:
                    error_text = await resp.aread() if resp.content else "无响应内容"
                    logger.warning(f"无法从本地Ollama获取模型列表，状态码: {resp.status_code}, 错误: {error_text[:100]}")
                    return []
        except httpx.ConnectError as e:
            logger.warning(f"连接本地Ollama失败（连接错误）: {e}")
            logger.info("这可能是因为Ollama服务没有运行，或者地址配置错误")
            return []
        except httpx.TimeoutException as e:
            logger.warning(f"连接本地Ollama超时: {e}")
            logger.info("Ollama服务响应超时，请检查服务状态")
            return []
        except Exception as e:
            logger.warning(f"连接本地Ollama失败（其他错误）: {type(e).__name__}: {e}")
            return []
    
    def _get_mock_local_models(self) -> List[Dict[str, Any]]:
        """获取模拟的本地模型列表，返回配置中支持的远端转发模型"""
        # 从配置中获取所有虚拟模型
        virtual_models = self.config_loader.get_all_virtual_models()
        mock_models = []
        
        for model_name in virtual_models:
            # 获取模型所属的组
            model_info = self.config_loader.get_model_config(model_name)
            family = "virtual"
            if model_info:
                model_config, _ = model_info
                family = model_config.model_group
            
            # 为每个虚拟模型创建模拟信息
            mock_model = {
                "name": model_name,
                "model": model_name,
                "modified_at": "2026-01-14T05:40:00.000000+08:00",
                "size": 405,
                "digest": "d3749919e45f955731da7a7e76849e20f7ed310725d3b8b52822e811f55d0a90",
                "details": {
                    "parent_model": "",
                    "format": "api",
                    "family": family,
                    "families": [family],
                    "parameter_size": "7B",
                    "quantization_level": "FP8_E4M3"
                }
            }
            mock_models.append(mock_model)
        
        logger.info(f"返回 {len(mock_models)} 个模拟本地模型（基于配置的虚拟模型）")
        return mock_models
    
    async def get_combined_models(self) -> List[Dict[str, Any]]:
        """获取合并的模型列表（本地+虚拟）"""
        combined_models = []
        
        # 获取本地模型
        if self.config_loader.routing_config.get("auto_discover_local_models", True):
            cache_enabled = self.config_loader.routing_config.get("cache", {}).get("enabled", True)
            cache_interval = self.config_loader.routing_config.get("cache", {}).get("update_interval", 60)
            
            import time
            current_time = time.time()
            
            if (not cache_enabled or
                not self.local_models_cache or
                current_time - self.last_cache_update > cache_interval):
                logger.info("开始获取本地Ollama模型列表...")
                self.local_models_cache = await self.fetch_local_models()
                self.last_cache_update = current_time
                logger.info(f"本地模型缓存已更新，获取到 {len(self.local_models_cache)} 个模型")
            else:
                logger.debug(f"使用缓存的本地模型列表 ({len(self.local_models_cache)} 个模型)")
            
            combined_models.extend(self.local_models_cache)
            logger.info(f"已添加 {len(self.local_models_cache)} 个本地模型到合并列表")
        else:
            logger.info("自动发现本地模型功能已禁用")
        
        # 添加虚拟模型
        virtual_models = self.config_loader.get_all_virtual_models()
        logger.info(f"开始添加 {len(virtual_models)} 个虚拟模型")
        
        for model_name in virtual_models:
            logger.info(f"处理虚拟模型 {model_name}: model_info={self.config_loader.get_model_config(model_name)}")
            # 获取模型配置
            model_info = self.config_loader.get_model_config(model_name)
            family = "virtual"
            remote_host = ""
            remote_model = model_name
            details_family = "virtual"
            details_families = ["virtual"]
            full_model_name = model_name  # 默认使用纯模型名
            
            if model_info:
                model_config, _ = model_info
                family = model_config.model_group
                details_family = model_config.model_group
                details_families = [model_config.model_group]
                # 构造带组名的完整模型名
                full_model_name = f"{model_config.model_group}/{model_name}"
                
                # 尝试获取后端配置
                backend_mode = self.config_loader.routing_config.get("default_backend_mode", "openai_backend")
                backend = model_config.get_backend(backend_mode)
                if backend:
                    remote_host = backend.base_url
                    # 获取实际模型名
                    actual_model = model_config.get_actual_model(model_name, backend_mode)
                    if actual_model:
                        remote_model = actual_model
            
            # 创建虚拟模型信息（模仿云模型结构）
            virtual_model_info = {
                "name": full_model_name,  # 使用带组名的完整模型名
                "model": full_model_name,  # 使用带组名的完整模型名
                "remote_model": remote_model,
                "remote_host": remote_host,
                "modified_at": "2026-01-14T05:40:00.000000+08:00",
                "size": 405,
                "digest": "d3749919e45f955731da7a7e76849e20f7ed310725d3b8b52822e811f55d0a90",
                "details": {
                    "parent_model": "",
                    "format": "api",
                    "family": details_family,
                    "families": details_families,
                    "parameter_size": "7B",
                    "quantization_level": "FP8_E4M3"
                }
            }
            logger.debug(f"添加虚拟模型: {full_model_name}, remote_host: {remote_host}, remote_model: {remote_model}, family: {details_family}")
            combined_models.append(virtual_model_info)
        
        logger.info(f"合并模型列表完成: 总共 {len(combined_models)} 个模型")
        return combined_models
    
    async def route_request(self, model_name: str, backend_mode: Optional[str] = None) -> Optional[List[Tuple[BackendConfig, str]]]:
        """
        路由请求到合适的后端（支持多个后端按优先级尝试）
        
        Returns:
            [(BackendConfig, actual_model_name), ...] 或 None（表示使用本地Ollama）
        """
        if backend_mode is not None:
            # 如果指定了backend_mode，使用原来的单个后端逻辑
            backend_info = self.config_loader.get_backend_for_model(model_name, backend_mode)
            if backend_info is None:
                return None
            backend, actual_model = backend_info
            return [(backend, actual_model)]
        else:
            # 否则返回所有按顺序排列的后端
            return self.config_loader.get_backends_for_model(model_name)