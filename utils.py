"""
Smart Ollama Proxy - 通用工具函数

包含可复用的工具函数和配置，例如：
1. orjson初始化（性能优化的JSON处理）
2. Unicode字符串清理函数
3. 其他通用工具函数
"""

try:
    import orjson as _orjson
    # 创建兼容的json模块
    class _FastJSON:
        @staticmethod
        def dumps(obj, **kwargs):
            # 忽略orjson不支持的参数（如separators, indent）
            # 处理ensure_ascii
            option = _orjson.OPT_NON_STR_KEYS | _orjson.OPT_SERIALIZE_NUMPY
            if kwargs.get('ensure_ascii') is False:
                # 如果OPT_NON_ASCII常量存在，则使用它
                # 注意：某些orjson版本可能没有这个常量
                if hasattr(_orjson, 'OPT_NON_ASCII'):
                    option |= _orjson.OPT_NON_ASCII
            # 如果indent为True，回退到标准json
            if kwargs.get('indent'):
                import json as std_json
                return std_json.dumps(obj, **kwargs)
            # orjson.dumps返回bytes，解码为str以保持兼容性
            return _orjson.dumps(obj, option=option).decode()
        @staticmethod
        def loads(s, **kwargs):
            return _orjson.loads(s)
    json = _FastJSON()
    # Add JSONDecodeError for compatibility
    import json as std_json
    json.JSONDecodeError = std_json.JSONDecodeError
except ImportError:
    import json


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


def sanitize_message(msg: dict) -> dict:
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


__all__ = ['json', 'sanitize_unicode_string', 'sanitize_message']