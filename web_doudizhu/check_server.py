#!/usr/bin/env python3
"""
服务器状态检查脚本
"""

import requests
import sys
import time
from datetime import datetime

def check_server_status(base_url="http://localhost:8000"):
    """检查服务器状态"""
    endpoints = {
        "健康检查": f"{base_url}/health",
        "API信息": f"{base_url}/",
        "排行榜": f"{base_url}/leaderboard",
        "房间列表": f"{base_url}/rooms",
    }
    
    print("=" * 60)
    print(f"服务器状态检查 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"基础URL: {base_url}")
    print("=" * 60)
    
    all_ok = True
    
    for name, url in endpoints.items():
        try:
            start_time = time.time()
            response = requests.get(url, timeout=5)
            elapsed = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                status = "✓"
                all_ok = True
            else:
                status = "✗"
                all_ok = False
            
            print(f"{status} {name:15} {url:35} {response.status_code:3} {elapsed:6.1f}ms")
            
            # 显示部分响应内容
            if name == "健康检查":
                data = response.json()
                print(f"    状态: {data.get('status', 'N/A')}")
                print(f"    服务: {data.get('service', 'N/A')}")
                
        except requests.exceptions.ConnectionError:
            print(f"✗ {name:15} {url:35} 连接失败")
            all_ok = False
        except requests.exceptions.Timeout:
            print(f"✗ {name:15} {url:35} 超时")
            all_ok = False
        except Exception as e:
            print(f"✗ {name:15} {url:35} 错误: {str(e)[:30]}")
            all_ok = False
    
    print("=" * 60)
    
    # 数据库检查
    try:
        import sqlite3
        import os
        
        if os.path.exists("data/game_scores.db"):
            conn = sqlite3.connect("data/game_scores.db")
            cursor = conn.cursor()
            
            # 检查表
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            table_count = len(tables)
            
            # 检查数据
            total_records = 0
            for table in tables:
                table_name = table[0]
                if table_name != "sqlite_sequence":
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    total_records += count
            
            conn.close()
            
            print(f"数据库检查:")
            print(f"  表数量: {table_count}")
            print(f"  总记录数: {total_records}")
            
            if table_count >= 3:  # 至少应该有3个表
                print("  ✓ 数据库结构正常")
            else:
                print("  ⚠ 数据库表数量异常")
                all_ok = False
        else:
            print("  ⚠ 数据库文件不存在")
            all_ok = False
            
    except Exception as e:
        print(f"  ✗ 数据库检查失败: {str(e)[:30]}")
        all_ok = False
    
    print("=" * 60)
    
    if all_ok:
        print("✓ 所有检查通过！服务器运行正常。")
        return 0
    else:
        print("⚠ 部分检查失败，请查看上面的错误信息。")
        return 1

def test_websocket():
    """测试WebSocket连接"""
    print("\nWebSocket连接测试...")
    try:
        import websocket
        import json
        
        ws_url = "ws://localhost:8000/ws/test_room/test_player"
        print(f"连接到: {ws_url}")
        
        # 创建WebSocket连接
        ws = websocket.create_connection(ws_url, timeout=5)
        
        # 发送测试消息
        test_message = {
            "type": "ping",
            "timestamp": datetime.now().isoformat()
        }
        ws.send(json.dumps(test_message))
        
        # 接收响应（如果有）
        try:
            response = ws.recv()
            print(f"  ✓ WebSocket连接成功")
            print(f"  响应: {response[:100]}...")
        except websocket.WebSocketTimeoutException:
            print(f"  ⚠ WebSocket连接成功，但无响应（可能正常）")
        
        ws.close()
        return True
        
    except ImportError:
        print("  ⚠ 未安装websocket-client库，跳过WebSocket测试")
        print("    安装: pip install websocket-client")
        return None
    except Exception as e:
        print(f"  ✗ WebSocket连接失败: {str(e)[:50]}")
        return False

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="斗地主游戏服务器状态检查")
    parser.add_argument("--url", default="http://localhost:8000", help="服务器基础URL")
    parser.add_argument("--websocket", action="store_true", help="测试WebSocket连接")
    
    args = parser.parse_args()
    
    # 检查HTTP端点
    http_status = check_server_status(args.url)
    
    # 测试WebSocket（如果指定）
    ws_status = None
    if args.websocket:
        ws_status = test_websocket()
    
    # 总结
    print("\n" + "=" * 60)
    print("检查总结:")
    print(f"  HTTP服务: {'正常' if http_status == 0 else '异常'}")
    
    if ws_status is not None:
        print(f"  WebSocket: {'正常' if ws_status else '异常'}")
    
    exit_code = 0 if http_status == 0 else 1
    if ws_status is False:
        exit_code = 1
    
    sys.exit(exit_code)