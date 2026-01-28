#!/usr/bin/env python3
"""
测试smart_logger.performance.record()修复
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smart_logger import get_smart_logger, LogLevel

def test_performance_record():
    """测试performance.record()方法是否正常工作"""
    print("测试smart_logger.performance.record()修复...")
    
    # 获取智能日志记录器
    smart_logger = get_smart_logger()
    
    try:
        # 测试performance.record() - 之前会抛出ValueError
        smart_logger.performance.record(
            key="test_metric",
            value={
                "metric": "test",
                "value": 123,
                "unit": "count"
            },
            level=LogLevel.INFO
        )
        print("[OK] performance.record() 调用成功，没有抛出异常")
        
        # 测试data.record() - 应该仍然工作
        smart_logger.data.record(
            key="test_data",
            value={"data": "test"},
            level=LogLevel.INFO
        )
        print("[OK] data.record() 调用成功")
        
        # 测试process.info() - 应该工作
        smart_logger.process.info("测试流程日志")
        print("[OK] process.info() 调用成功")
        
        # 测试performance.info() - 应该工作
        smart_logger.performance.info("测试性能日志")
        print("[OK] performance.info() 调用成功")
        
        print("\n所有测试通过！修复成功。")
        return True
        
    except ValueError as e:
        print(f"[FAIL] 测试失败: {e}")
        print("错误信息:", str(e))
        return False
    except Exception as e:
        print(f"[FAIL] 测试出现意外错误: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_record_method_restrictions():
    """测试record方法的类型限制"""
    print("\n测试record方法的类型限制...")
    
    smart_logger = get_smart_logger()
    
    # 测试process.record() - 应该抛出异常（PROCESS类型不支持record）
    try:
        smart_logger.process.record("test", "value")
        print("[FAIL] process.record() 应该抛出异常但没有")
        return False
    except ValueError as e:
        if "record方法仅用于DATA和PERFORMANCE类型的日志" in str(e):
            print("[OK] process.record() 正确抛出异常")
        else:
            print(f"[FAIL] process.record() 抛出异常但消息不正确: {e}")
            return False
    
    # 测试progress.record() - 应该抛出异常（PROGRESS类型不支持record）
    # 注意：smart_logger.progress是ProgressManager，没有record方法
    # 所以这个测试会抛出AttributeError，不是我们要测试的
    
    print("[OK] record方法类型限制测试通过")
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Logger 修复测试")
    print("=" * 60)
    
    test1_passed = test_performance_record()
    test2_passed = test_record_method_restrictions()
    
    print("\n" + "=" * 60)
    if test1_passed and test2_passed:
        print("所有测试通过！修复成功。")
        sys.exit(0)
    else:
        print("测试失败！")
        sys.exit(1)