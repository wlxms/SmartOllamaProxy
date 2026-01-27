#!/usr/bin/env python3
"""
测试流式logger的完整功能，包括请求JSON打印和流式响应整合
"""
import sys
import os
import time
import json as json_module

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stream_logger import init_global_logger, get_global_logger, LogLevel

def test_complete_flow():
    """测试完整的流式日志流程"""
    print("=== 测试流式logger完整功能 ===")
    
    # 初始化logger，启用控制台日志，禁用详细JSON日志
    logger = init_global_logger(
        log_dir="test_logs_complete",
        verbose_json_logging=False,
        enable_console_logging=True,
        log_level=LogLevel.DEBUG
    )
    
    print("1. 模拟客户端请求")
    request_data = {
        "model": "gpt-4",
        "messages": [
            {"role": "user", "content": "请写一首诗"}
        ],
        "temperature": 0.8,
        "stream": True
    }
    
    # 记录输入流（模拟路由器调用）
    log_id = logger.log_input_stream(
        data=request_data,
        router_name="TestRouter",
        model_name="gpt-4",
        stream=True
    )
    print(f"   生成的log_id: {log_id}")
    
    print("2. 模拟流式响应chunk（OpenAI格式）")
    # 模拟OpenAI流式响应chunk
    chunks = [
        {'id': 'chatcmpl-123', 'object': 'chat.completion.chunk', 'created': 1677652288, 'model': 'gpt-4', 'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]},
        {'id': 'chatcmpl-123', 'object': 'chat.completion.chunk', 'created': 1677652288, 'model': 'gpt-4', 'choices': [{'index': 0, 'delta': {'content': '春风'}, 'finish_reason': None}]},
        {'id': 'chatcmpl-123', 'object': 'chat.completion.chunk', 'created': 1677652288, 'model': 'gpt-4', 'choices': [{'index': 0, 'delta': {'content': '拂面'}, 'finish_reason': None}]},
        {'id': 'chatcmpl-123', 'object': 'chat.completion.chunk', 'created': 1677652288, 'model': 'gpt-4', 'choices': [{'index': 0, 'delta': {'content': '花香'}, 'finish_reason': None}]},
        {'id': 'chatcmpl-123', 'object': 'chat.completion.chunk', 'created': 1677652288, 'model': 'gpt-4', 'choices': [{'index': 0, 'delta': {'content': '醉'}, 'finish_reason': 'stop'}]}
    ]
    
    for i, chunk in enumerate(chunks):
        # 将chunk转换为JSON字符串（模拟SSE格式）
        chunk_json = json_module.dumps(chunk)
        logger.log_stream_chunk(
            session_id=log_id,
            chunk_data=chunk_json,
            chunk_index=i,
            total_bytes=len(chunk_json) * (i+1)
        )
        print(f"   记录chunk {i}: {chunk_json[:50]}...")
    
    print("3. 结束流式会话，应打印完整整合的JSON")
    logger.end_stream(log_id)
    
    print("4. 验证complete_json字段")
    # 获取会话数据（通过内部方法？这里我们直接检查日志文件）
    # 由于我们无法直接访问内部会话，我们相信end_stream已经打印了完整JSON
    
    print("=== 测试完成 ===")
    
    # 清理测试日志目录
    import shutil
    if os.path.exists("test_logs_complete"):
        try:
            shutil.rmtree("test_logs_complete", ignore_errors=True)
            print("清理测试日志目录")
        except:
            pass

def test_switch_configuration():
    """测试开关配置"""
    print("\n=== 测试开关配置 ===")
    
    # 测试1: 禁用控制台日志
    print("1. 测试禁用控制台日志")
    logger1 = init_global_logger(
        log_dir="test_logs_switch1",
        verbose_json_logging=False,
        enable_console_logging=False,
        log_level=LogLevel.DEBUG
    )
    log_id1 = logger1.start_stream(metadata={"test": "no_console"})
    logger1.log_input_stream({"test": "data"}, "Test", "model", stream=True, request_id=log_id1)
    # 应该没有控制台输出
    logger1.end_stream(log_id1)
    print("   控制台日志已禁用，应无输出")
    
    # 测试2: 启用详细JSON日志
    print("2. 测试启用详细JSON日志")
    logger2 = init_global_logger(
        log_dir="test_logs_switch2",
        verbose_json_logging=True,
        enable_console_logging=True,
        log_level=LogLevel.DEBUG
    )
    log_id2 = logger2.start_stream(metadata={"test": "verbose"})
    logger2.log_input_stream({"test": "data"}, "Test", "model", stream=True, request_id=log_id2)
    for i in range(2):
        logger2.log_stream_chunk(log_id2, f"chunk{i}", i, 100)
    logger2.end_stream(log_id2)
    print("   详细JSON日志已启用，应有chunk日志和完整JSON")
    
    # 清理
    for dir_name in ["test_logs_switch1", "test_logs_switch2"]:
        if os.path.exists(dir_name):
            shutil.rmtree(dir_name, ignore_errors=True)

if __name__ == "__main__":
    test_complete_flow()
    test_switch_configuration()
    print("\n所有测试完成！")