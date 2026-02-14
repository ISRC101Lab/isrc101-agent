#!/usr/bin/env python3
"""
诊断斗地主游戏连接问题
"""

import requests
import socket
import sys
import os

def check_port(host='localhost', port=8000):
    """检查端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except:
        return False

def test_api_connection(base_url='http://localhost:8000'):
    """测试API连接"""
    endpoints = [
        '/api/rooms',
        '/health',
        '/frontend'
    ]
    
    results = []
    for endpoint in endpoints:
        url = base_url + endpoint
        try:
            response = requests.get(url, timeout=5)
            results.append((endpoint, response.status_code, 'OK' if response.status_code == 200 else 'ERROR'))
        except requests.exceptions.ConnectionError:
            results.append((endpoint, 'N/A', '连接失败'))
        except Exception as e:
            results.append((endpoint, 'ERROR', str(e)))
    
    return results

def main():
    print("=" * 60)
    print("          斗地主游戏连接诊断工具")
    print("=" * 60)
    
    # 检查端口
    print("\n1. 检查服务器端口 (8000)...")
    if check_port('localhost', 8000):
        print("   ✅ 端口 8000 已开放")
    else:
        print("   ❌ 端口 8000 未开放 - 服务器可能未运行")
        print("      请运行: cd web_doudizhu && python main.py")
    
    # 测试API连接
    print("\n2. 测试API连接...")
    results = test_api_connection()
    
    all_ok = True
    for endpoint, status, message in results:
        if status == 200 or endpoint == '/health' and status == 200:
            print(f"   ✅ {endpoint}: {status} - {message}")
        else:
            print(f"   ❌ {endpoint}: {status} - {message}")
            all_ok = False
    
    # 检查前端文件
    print("\n3. 检查前端文件...")
    frontend_files = [
        ('/frontend/index.html', '游戏主界面'),
        ('/frontend/game.js', '游戏逻辑'),
        ('/frontend/style.css', '样式文件')
    ]
    
    for file_path, description in frontend_files:
        url = 'http://localhost:8000' + file_path
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                print(f"   ✅ {description}: 可用 ({len(response.text)} 字节)")
            else:
                print(f"   ❌ {description}: 不可用 (HTTP {response.status_code})")
                all_ok = False
        except:
            print(f"   ❌ {description}: 无法访问")
            all_ok = False
    
    # 总结
    print("\n" + "=" * 60)
    print("诊断结果:")
    
    if all_ok:
        print("✅ 所有检查通过！游戏应该可以正常运行。")
        print("\n访问游戏:")
        print("  1. 打开浏览器访问: http://localhost:8000/frontend")
        print("  2. 输入玩家名称，点击 'Connect to Server'")
        print("  3. 创建或加入房间开始游戏")
    else:
        print("❌ 发现一些问题，请根据以上提示进行修复。")
        print("\n常见问题解决:")
        print("  1. 确保服务器已运行: cd web_doudizhu && python main.py")
        print("  2. 检查端口 8000 是否被其他程序占用")
        print("  3. 检查防火墙设置")
        print("  4. 查看浏览器控制台错误 (F12 → Console)")
    
    print("=" * 60)

if __name__ == '__main__':
    main()