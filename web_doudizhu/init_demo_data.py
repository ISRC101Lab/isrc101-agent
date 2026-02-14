#!/usr/bin/env python3
"""
初始化演示数据
"""

import sqlite3
import json
from datetime import datetime, timedelta
import uuid

def init_demo_data():
    """初始化演示数据"""
    conn = sqlite3.connect('data/game_scores.db')
    cursor = conn.cursor()
    
    # 创建示例玩家
    demo_players = [
        ("player_001", "小明", 10, 6, 120),
        ("player_002", "小红", 12, 5, 95),
        ("player_003", "小刚", 8, 4, 75),
        ("player_004", "AI-简单", 20, 8, 150),
        ("player_005", "AI-困难", 15, 12, 210),
    ]
    
    print("添加示例玩家...")
    for player_id, name, total_games, wins, total_score in demo_players:
        last_played = (datetime.now() - timedelta(days=total_games)).isoformat()
        cursor.execute("""
            INSERT OR REPLACE INTO player_scores 
            (player_id, player_name, total_games, wins, total_score, last_played)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (player_id, name, total_games, wins, total_score, last_played))
    
    # 创建示例游戏记录
    print("添加示例游戏记录...")
    for i in range(5):
        room_id = f"demo_room_{i+1}"
        game_data = {
            "room_id": room_id,
            "players": ["小明", "小红", "小刚"],
            "winner": "小明" if i % 2 == 0 else "小红",
            "landlord": "小明" if i % 2 == 0 else "小红",
            "score": 100 if i % 2 == 0 else 80,
            "duration": 300 + i * 60,  # 5-9分钟
            "played_at": (datetime.now() - timedelta(days=i)).isoformat()
        }
        
        cursor.execute("""
            INSERT INTO game_records (room_id, game_data, created_at)
            VALUES (?, ?, ?)
        """, (room_id, json.dumps(game_data, ensure_ascii=False), datetime.now().isoformat()))
        
        game_id = cursor.lastrowid
        
        # 添加游戏详情
        players_data = [
            ("player_001", "小明", "地主" if i % 2 == 0 else "农民", 50 if i % 2 == 0 else -25, 170 if i % 2 == 0 else 70),
            ("player_002", "小红", "农民" if i % 2 == 0 else "地主", -25 if i % 2 == 0 else 50, 70 if i % 2 == 0 else 145),
            ("player_003", "小刚", "农民", -25, 50),
        ]
        
        for player_id, player_name, role, score_change, final_score in players_data:
            cursor.execute("""
                INSERT INTO game_details (game_id, player_id, player_name, role, score_change, final_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (game_id, player_id, player_name, role, score_change, final_score))
    
    conn.commit()
    conn.close()
    print("演示数据初始化完成！")
    
    # 显示统计数据
    print("\n当前统计数据:")
    conn = sqlite3.connect('data/game_scores.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM player_scores")
    player_count = cursor.fetchone()[0]
    print(f"玩家数量: {player_count}")
    
    cursor.execute("SELECT COUNT(*) FROM game_records")
    game_count = cursor.fetchone()[0]
    print(f"游戏记录数量: {game_count}")
    
    cursor.execute("SELECT player_name, total_games, wins, total_score FROM player_scores ORDER BY total_score DESC LIMIT 5")
    print("\n排行榜前5名:")
    for row in cursor.fetchall():
        name, games, wins, score = row
        win_rate = (wins / games * 100) if games > 0 else 0
        print(f"  {name}: {score}分 ({games}局, {win_rate:.1f}%胜率)")
    
    conn.close()

if __name__ == "__main__":
    init_demo_data()