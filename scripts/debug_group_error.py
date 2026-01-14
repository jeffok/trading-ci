#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试 'group' 变量未定义错误
"""

import sys
import traceback
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis
    from libs.common.config import settings
    from libs.mq.redis_streams import RedisStreamsClient
    
    print("=== 测试 Redis Streams 客户端 ===")
    
    # 测试连接
    client = RedisStreamsClient(settings.redis_url)
    print(f"✅ Redis 连接成功")
    
    # 测试 ensure_group
    try:
        client.ensure_group("stream:trade_plan", settings.redis_stream_group)
        print(f"✅ ensure_group 成功: group={settings.redis_stream_group}")
    except Exception as e:
        print(f"❌ ensure_group 失败: {e}")
        traceback.print_exc()
    
    # 测试 read_group
    try:
        consumer = f"{settings.redis_stream_consumer}-test"
        msgs = client.read_group("stream:trade_plan", settings.redis_stream_group, consumer, count=1, block_ms=1000)
        print(f"✅ read_group 成功: 读取到 {len(msgs)} 条消息")
    except Exception as e:
        print(f"❌ read_group 失败: {e}")
        traceback.print_exc()
        print(f"   错误类型: {type(e).__name__}")
        print(f"   错误消息: {str(e)}")
        if "group" in str(e).lower():
            print(f"   ⚠️  错误消息中包含 'group'")
    
    # 测试 ack
    try:
        if msgs:
            client.ack(msgs[0].stream, settings.redis_stream_group, msgs[0].message_id)
            print(f"✅ ack 成功")
    except Exception as e:
        print(f"❌ ack 失败: {e}")
        traceback.print_exc()
    
except Exception as e:
    print(f"❌ 测试失败: {e}")
    traceback.print_exc()
    sys.exit(1)
