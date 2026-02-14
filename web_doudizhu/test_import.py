#!/usr/bin/env python3
"""
测试项目导入
"""

import os
import sys

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("测试项目导入...")
print("=" * 50)

try:
    # 测试导入API
    from backend.api import app
    print("✅ FastAPI应用导入成功")
    print(f"   应用标题: {app.title}")
    print(f"   应用版本: {app.version}")
except Exception as e:
    print(f"❌ API导入失败: {e}")
    import traceback
    traceback.print_exc()

print()

try:
    # 测试导入卡牌模块
    from backend.card import Card, CardRank, CardSuit
    print("✅ 卡牌模块导入成功")
    
    # 创建测试卡牌
    card1 = Card(CardRank.ACE, CardSuit.SPADE)
    card2 = Card(CardRank.KING, CardSuit.HEART)
    print(f"   测试卡牌1: {card1}")
    print(f"   测试卡牌2: {card2}")
except Exception as e:
    print(f"❌ 卡牌模块导入失败: {e}")

print()

try:
    # 测试导入游戏模块
    from backend.game import GameState
    print("✅ 游戏模块导入成功")
    
    # 创建测试游戏
    game = GameState("test_room")
    print(f"   测试游戏房间: {game.room_id}")
    print(f"   游戏阶段: {game.phase}")
except Exception as e:
    print(f"❌ 游戏模块导入失败: {e}")

print()

try:
    # 测试导入AI模块
    from backend.ai import AIPlayer
    print("✅ AI模块导入成功")
except Exception as e:
    print(f"❌ AI模块导入失败: {e}")

print("=" * 50)
print("导入测试完成！")