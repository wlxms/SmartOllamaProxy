#!/usr/bin/env python3
"""
测试progressbar功能
"""
import sys
import time
sys.path.insert(0, '.')

from smart_logger import get_smart_logger

def test_progressbar():
    """测试ProgressBar功能"""
    print("=== 测试ProgressBar功能 ===")
    
    smart_logger = get_smart_logger()
    
    # 测试1: 创建进度条
    print("测试1: 创建进度条...")
    if hasattr(smart_logger, 'progress'):
        progress_bar = smart_logger.progress.create(
            total=100,
            description="测试进度条",
            bar_id="test_bar_1"
        )
        print("✅ 进度条创建成功")
        
        # 更新进度
        for i in range(0, 101, 10):
            progress_bar.update(10)
            time.sleep(0.1)
        
        progress_bar.close()
        print("✅ 进度条更新和关闭成功")
    else:
        print("❌ SmartLogger没有progress属性")
        return False
    
    # 测试2: 测试未知总大小的进度条
    print("\n测试2: 测试未知总大小的进度条...")
    progress_bar2 = smart_logger.progress.create(
        total=100,  # 虚拟total
        description="未知大小测试",
        bar_id="test_bar_2"
    )
    
    # 模拟接收数据
    bytes_received = 0
    chunk_count = 0
    for i in range(10):
        bytes_received += 1024 * 1024  # 每次增加1MB
        chunk_count += 1
        
        # 更新进度：每接收1MB增加1%进度
        mb_received = bytes_received / (1024 * 1024)
        new_progress = min(int(mb_received), 99)
        
        if new_progress > progress_bar2.current:
            progress_bar2.update(new_progress - progress_bar2.current)
        
        # 更新描述
        progress_bar2.description = f"测试: 已接收 {bytes_received/(1024*1024):.1f}MB, 块: {chunk_count}"
        time.sleep(0.1)
    
    progress_bar2.close()
    print("✅ 未知大小进度条测试成功")
    
    # 测试3: 测试base_router中的进度显示方法
    print("\n测试3: 测试base_router进度显示方法...")
    try:
        from routers.base_router import BackendRouter
        from config_loader import BackendConfig
        
        # 创建模拟配置
        config_data = {
            "base_url": "http://example.com",
            "api_key": "test_key",
            "timeout": 30,
            "headers": {},
            "litellm_params": {}
        }
        config = BackendConfig(config_data)
        
        # 创建测试路由器类
        class TestRouter(BackendRouter):
            async def handle_request(self, actual_model, request_data, stream=False, support_thinking=False):
                pass
            
            def convert_to_ollama_format(self, response_data, virtual_model):
                return {}
        
        router = TestRouter(config)
        
        # 测试_print_stream_progress方法
        print("测试_print_stream_progress方法...")
        
        # 情况1: 已知content_length
        print("情况1: 已知content_length")
        router._print_stream_progress(
            chunk_count=5,
            total_bytes=5000,
            content_length=10000,
            log_id="test_log_1"
        )
        time.sleep(0.5)
        
        # 情况2: 未知content_length
        print("\n情况2: 未知content_length")
        router._print_stream_progress(
            chunk_count=10,
            total_bytes=2048,
            content_length=None,
            log_id="test_log_2"
        )
        time.sleep(0.5)
        
        # 测试_print_stream_complete方法
        print("\n测试_print_stream_complete方法...")
        router._print_stream_complete(
            chunk_count=15,
            total_bytes=3072,
            log_id="test_log_1"
        )
        
        print("✅ base_router进度显示方法测试成功")
        
    except Exception as e:
        print(f"❌ base_router测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n=== 所有测试通过 ===")
    return True

if __name__ == "__main__":
    success = test_progressbar()
    sys.exit(0 if success else 1)