#!/usr/bin/env python3
"""
测试斗地主游戏连接问题
模拟浏览器行为检查常见问题
"""

import requests
import json
import sys
import time
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socket

def check_port(port=8000):
    """检查端口是否开放"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex(('localhost', port))
    sock.close()
    return result == 0

def test_api_endpoints():
    """测试所有API端点"""
    print("=== 测试API端点 ===")
    
    endpoints = [
        ('GET', '/api/rooms', '房间列表'),
        ('GET', '/health', '健康检查'),
        ('GET', '/frontend', '前端界面'),
        ('GET', '/frontend/index.html', 'HTML文件'),
        ('GET', '/frontend/game.js', 'JavaScript文件'),
        ('GET', '/frontend/style.css', 'CSS文件'),
    ]
    
    all_ok = True
    for method, endpoint, description in endpoints:
        try:
            url = f'http://localhost:8000{endpoint}'
            response = requests.get(url, timeout=5)
            status = '✅' if response.status_code == 200 else '❌'
            print(f"{status} {description:15} {endpoint:25} HTTP {response.status_code}")
            
            if response.status_code != 200:
                all_ok = False
                print(f"   错误: 期望200, 得到{response.status_code}")
                
            if endpoint == '/api/rooms':
                try:
                    data = response.json()
                    print(f"   响应: {json.dumps(data, ensure_ascii=False)}")
                except:
                    print(f"   响应: 无效JSON")
                    
        except Exception as e:
            print(f"❌ {description:15} {endpoint:25} 错误: {e}")
            all_ok = False
    
    return all_ok

def test_browser_simulation():
    """模拟浏览器连接流程"""
    print("\n=== 模拟浏览器连接流程 ===")
    
    # 1. 获取HTML文件
    print("1. 获取HTML文件...")
    try:
        response = requests.get('http://localhost:8000/frontend/index.html', timeout=5)
        if response.status_code == 200:
            html = response.text
            # 检查关键元素
            checks = [
                ('id="connect-btn"', '连接按钮'),
                ('id="connection-status"', '连接状态显示'),
                ('id="player-name"', '玩家名称输入'),
                ('game.js', 'JavaScript文件引用'),
            ]
            
            for pattern, desc in checks:
                if pattern in html:
                    print(f"   ✅ {desc}存在")
                else:
                    print(f"   ❌ {desc}不存在")
        else:
            print(f"   ❌ 获取HTML失败: HTTP {response.status_code}")
    except Exception as e:
        print(f"   ❌ 获取HTML失败: {e}")
    
    # 2. 模拟连接请求
    print("\n2. 模拟连接请求...")
    try:
        response = requests.get('http://localhost:8000/api/rooms', timeout=5)
        if response.status_code == 200:
            rooms = response.json()
            print(f"   ✅ API连接成功: {json.dumps(rooms, ensure_ascii=False)}")
            return True
        else:
            print(f"   ❌ API连接失败: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"   ❌ API连接失败: {e}")
        return False

def check_common_issues():
    """检查常见问题"""
    print("\n=== 检查常见问题 ===")
    
    issues = []
    
    # 检查端口占用
    if not check_port(8000):
        issues.append("❌ 端口8000未开放 - 服务器可能没有运行")
    else:
        print("✅ 端口8000已开放")
    
    # 检查API响应
    try:
        response = requests.get('http://localhost:8000/api/rooms', timeout=2)
        if response.status_code != 200:
            issues.append(f"❌ API响应异常: HTTP {response.status_code}")
        else:
            print("✅ API响应正常")
    except:
        issues.append("❌ API请求失败 - 服务器可能未启动或配置错误")
    
    # 检查前端文件
    files_to_check = [
        ('/frontend/index.html', 'HTML文件'),
        ('/frontend/game.js', 'JavaScript文件'),
        ('/frontend/style.css', 'CSS文件'),
    ]
    
    for file_path, desc in files_to_check:
        try:
            response = requests.get(f'http://localhost:8000{file_path}', timeout=2)
            if response.status_code != 200:
                issues.append(f"❌ {desc}不可访问: HTTP {response.status_code}")
            else:
                print(f"✅ {desc}可访问")
        except:
            issues.append(f"❌ {desc}请求失败")
    
    # 检查WebSocket支持
    try:
        response = requests.get('http://localhost:8000/', timeout=2)
        # 检查是否有WebSocket升级头支持
        if 'Upgrade' in response.headers.get('Connection', ''):
            print("✅ WebSocket支持检测到")
        else:
            # 这不是关键问题，只是信息
            print("ℹ️  WebSocket升级头未检测到（可能正常）")
    except:
        pass
    
    if issues:
        print("\n❌ 发现问题:")
        for issue in issues:
            print(f"   {issue}")
        return False
    else:
        print("\n✅ 未发现明显问题")
        return True

def provide_solutions():
    """提供解决方案"""
    print("\n=== 解决方案 ===")
    print("如果连接仍然失败，请尝试以下步骤:")
    print()
    print("1. 清除浏览器缓存:")
    print("   - Chrome/Edge: Ctrl+Shift+R 或 Ctrl+F5")
    print("   - Firefox: Ctrl+Shift+R 或 Ctrl+F5")
    print("   - Safari: Cmd+Option+R")
    print()
    print("2. 检查浏览器控制台错误:")
    print("   - Chrome/Edge: F12 → Console标签")
    print("   - Firefox: F12 → Console标签")
    print("   - Safari: Option+Cmd+I → Console标签")
    print()
    print("3. 使用调试页面:")
    print("   - 访问: http://localhost:8000/frontend/debug.html")
    print("   - 点击测试按钮检查所有连接")
    print()
    print("4. 验证服务器状态:")
    print("   - 确保服务器正在运行: python main.py")
    print("   - 检查端口占用: netstat -an | grep 8000")
    print()
    print("5. 备用启动方式:")
    print("   - 使用不同端口: PORT=8001 python main.py")
    print("   - 然后访问: http://localhost:8001/frontend")
    print()
    print("6. 检查防火墙/安全软件:")
    print("   - 确保端口8000未被防火墙阻止")
    print("   - 暂时禁用安全软件测试")

def main():
    print("斗地主游戏连接诊断工具")
    print("=" * 50)
    
    # 检查端口
    if not check_port(8000):
        print("❌ 端口8000未开放！")
        print("请确保服务器正在运行:")
        print("   cd web_doudizhu && python main.py")
        print()
        provide_solutions()
        return 1
    
    print("✅ 端口8000已开放，服务器可能正在运行")
    
    # 检查常见问题
    issues_ok = check_common_issues()
    
    # 测试API端点
    api_ok = test_api_endpoints()
    
    # 模拟浏览器连接
    browser_ok = test_browser_simulation()
    
    print("\n" + "=" * 50)
    print("诊断结果:")
    
    if issues_ok and api_ok and browser_ok:
        print("✅ 所有测试通过！")
        print("\n如果仍然有问题，可能是浏览器缓存或JavaScript执行问题。")
        print("请尝试清除浏览器缓存或使用调试页面。")
    else:
        print("⚠️  发现一些问题，请查看上面的错误信息。")
    
    provide_solutions()
    
    return 0 if (issues_ok and api_ok and browser_ok) else 1

if __name__ == '__main__':
    sys.exit(main())