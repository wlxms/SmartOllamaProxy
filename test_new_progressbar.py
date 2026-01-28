#!/usr/bin/env python3
"""
测试新的进度条设计
"""
import sys
import time
sys.path.insert(0, '.')

from smart_logger import get_smart_logger

def test_new_progressbar():
    """测试新的ProgressBar设计"""
    print("=== 测试新的ProgressBar设计 ===")
    
    smart_logger = get_smart_logger()
    
    # 测试1: 已知总大小的进度条
    print("\n测试1: 已知总大小的进度条")
    if hasattr(smart_logger, 'progress'):
        progress_bar = smart_logger.progress.create(
            total=100,
            description="[TestRouter] 接收中",
            bar_id="test_bar_1"
        )
        print("进度条创建成功")
        
        # 模拟接收数据
        for i in range(0, 101, 10):
            bytes_received = i * 1024  # 模拟字节数
            chunk_count = i // 10
            extra_info = f"({bytes_received/1024:.1f}KB, 块: {chunk_count})"
            progress_bar.update(10, extra_info=extra_info)
            time.sleep(0.1)
        
        progress_bar.close()
        print("进度条更新和关闭成功")
    else:
        print("SmartLogger没有progress属性")
        return False
    
    # 测试2: 未知总大小的进度条（循环模式）
    print("\n测试2: 未知总大小的进度条（循环模式）")
    progress_bar2 = smart_logger.progress.create(
        total=0,  # 总大小为0，触发循环模式
        description="[TestRouter] 接收中",
        bar_id="test_bar_2"
    )
    
    # 模拟接收数据
    bytes_received = 0
    chunk_count = 0
    for i in range(15):
        bytes_received += 512 * 1024  # 每次增加0.5MB
        chunk_count += 1
        
        # 更新进度条
        extra_info = f"({bytes_received/(1024*1024):.1f}MB, 块: {chunk_count})"
        progress_bar2.update(0, extra_info=extra_info)  # advance=0，只更新额外信息
        time.sleep(0.1)
    
    progress_bar2.close()
    print("循环进度条测试成功")
    
    # 测试3: 不同宽度的进度条
    print("\n测试3: 不同宽度的进度条")
    
    # 创建自定义配置
    from smart_logger import LogConfig
    custom_config = {
        "enabled": True,
        "log_dir": "logs",
        "log_level": "INFO",
        "log_types": {
            "progress": {
                "enabled": True,
                "save_to_file": False,
                "show_in_console": True,
                "async_mode": False
            }
        },
        "progress": {
            "width": 30,  # 更窄的宽度
            "fill_char": "|",
            "empty_char": " ",
            "show_percentage": True,
            "show_elapsed_time": True
        }
    }
    
    config = LogConfig(custom_config)
    from smart_logger import ProgressBar, ProgressConfig
    
    # 测试窄进度条
    progress_config = ProgressConfig(custom_config["progress"])
    narrow_bar = ProgressBar(
        total=50,
        description="[Narrow]",
        config=progress_config,
        bar_id="narrow_bar"
    )
    
    for i in range(0, 51, 5):
        narrow_bar.update(5)
        time.sleep(0.05)
    
    narrow_bar.close()
    print("窄进度条测试成功")
    
    # 测试宽进度条
    custom_config["progress"]["width"] = 60
    progress_config_wide = ProgressConfig(custom_config["progress"])
    wide_bar = ProgressBar(
        total=200,
        description="[WideBar]",
        config=progress_config_wide,
        bar_id="wide_bar"
    )
    
    for i in range(0, 201, 20):
        wide_bar.update(20)
        time.sleep(0.05)
    
    wide_bar.close()
    print("宽进度条测试成功")
    
    print("\n=== 所有测试完成 ===")
    return True

if __name__ == "__main__":
    success = test_new_progressbar()
    sys.exit(0 if success else 1)