#!/usr/bin/env python3
"""
测试流式logger修复后的功能
验证：
1. 输入流记录（打印请求JSON）
2. 流式chunk记录（默认不记录，除非verbose_json_logging=True）
3. 流式结束记录（打印完整组装JSON）
"""
import sys
import os
import time
import json as json_module

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stream_logger import init_global_logger, get_global_logger, LogLevel

def test_stream_logger():
    """测试流式logger的基本功能"""
    print("=== 测试流式logger修复 ===")
    
    # 初始化logger，启用控制台日志，禁用详细JSON日志（chunk记录）
    logger = init_global_logger(
        log_dir="test_logs",
        verbose_json_logging=False,  # 禁用chunk记录
        enable_console_logging=True,
        log_level=LogLevel.DEBUG
    )
    
    print("1. 测试输入流记录")
    request_data = {
        "messages": [
            {"role": "user", "content": "Hello, world!"}
        ],
        "temperature": 0.7
    }
    
    # 记录输入流
    log_id = logger.log_input_stream(
        data=request_data,
        router_name="TestRouter",
        model_name="test-model",
        stream=True
    )
    print(f"   生成的log_id: {log_id}")
    
    print("2. 测试流式chunk记录（verbose_json_logging=False，应不记录chunk）")
    # 模拟几个chunk
    chunks = [
        'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
        'data: [DONE]\n\n'
    ]
    
    for i, chunk in enumerate(chunks):
        logger.log_stream_chunk(
            session_id=log_id,
            chunk_data=chunk,
            chunk_index=i,
            total_bytes=len(chunk) * (i+1)
        )
        print(f"   记录chunk {i}，但verbose_json_logging=False，应无控制台输出")
    
    print("3. 测试流式结束，应打印完整组装JSON")
    logger.end_stream(log_id)
    
    print("4. 测试verbose_json_logging=True时的chunk记录")
    # 重新初始化logger，启用详细JSON日志
    logger2 = init_global_logger(
        log_dir="test_logs",
        verbose_json_logging=True,
        enable_console_logging=True,
        log_level=LogLevel.DEBUG
    )
    log_id2 = logger2.start_stream(metadata={"test": "verbose"})
    for i in range(2):
        logger2.log_stream_chunk(
            session_id=log_id2,
            chunk_data=f'chunk {i}',
            chunk_index=i,
            total_bytes=100 * (i+1)
        )
        print(f"   记录chunk {i}，verbose_json_logging=True，应有chunk日志")
    
    logger2.end_stream(log_id2)
    
    print("=== 测试完成 ===")
    
    # 清理测试日志目录（忽略错误）
    import shutil
    if os.path.exists("test_logs"):
        try:
            shutil.rmtree("test_logs", ignore_errors=True)
            print("清理测试日志目录")
        except:
            pass

if __name__ == "__main__":
    test_stream_logger()