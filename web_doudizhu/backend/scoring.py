"""
计分系统模块
"""

import json
import sqlite3
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
from .game import GameState, PlayerRole


class ScoringSystem:
    """计分系统"""
    
    def __init__(self, db_path: str = "data/game_scores.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """初始化数据库"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建游戏记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                game_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 创建玩家积分表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS player_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                total_games INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                total_score INTEGER DEFAULT 0,
                last_played TIMESTAMP,
                UNIQUE(player_id)
            )
        ''')
        
        # 创建游戏详情表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS game_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER,
                player_id TEXT NOT NULL,
                player_name TEXT NOT NULL,
                role TEXT NOT NULL,
                score_change INTEGER NOT NULL,
                final_score INTEGER NOT NULL,
                FOREIGN KEY (game_id) REFERENCES game_records (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_game(self, game: GameState):
        """保存游戏记录"""
        game_data = json.dumps(game.to_dict(), ensure_ascii=False)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 插入游戏记录
        cursor.execute(
            'INSERT INTO game_records (room_id, game_data) VALUES (?, ?)',
            (game.room_id, game_data)
        )
        
        game_id = cursor.lastrowid
        
        # 更新玩家积分
        for player_id, player in game.players.items():
            # 更新玩家总积分
            cursor.execute('''
                INSERT OR IGNORE INTO player_scores (player_id, player_name) 
                VALUES (?, ?)
            ''', (player_id, player.name))
            
            cursor.execute('''
                UPDATE player_scores 
                SET total_games = total_games + 1,
                    wins = wins + ?,
                    total_score = total_score + ?,
                    last_played = ?
                WHERE player_id = ?
            ''', (
                1 if game.winner == player_id else 0,
                player.score,
                datetime.now().isoformat(),
                player_id
            ))
            
            # 插入游戏详情
            cursor.execute('''
                INSERT INTO game_details 
                (game_id, player_id, player_name, role, score_change, final_score)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                game_id,
                player_id,
                player.name,
                player.role.value,
                player.score,
                self._get_player_total_score(player_id) + player.score
            ))
        
        conn.commit()
        conn.close()
    
    def get_player_stats(self, player_id: str) -> Optional[Dict]:
        """获取玩家统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT player_name, total_games, wins, total_score, last_played
            FROM player_scores
            WHERE player_id = ?
        ''', (player_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return {
            'player_id': player_id,
            'player_name': row[0],
            'total_games': row[1],
            'wins': row[2],
            'win_rate': row[2] / row[1] if row[1] > 0 else 0,
            'total_score': row[3],
            'avg_score': row[3] / row[1] if row[1] > 0 else 0,
            'last_played': row[4]
        }
    
    def get_leaderboard(self, limit: int = 10) -> List[Dict]:
        """获取排行榜"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT player_id, player_name, total_score, wins, total_games
            FROM player_scores
            WHERE total_games >= 5
            ORDER BY total_score DESC
            LIMIT ?
        ''', (limit,))
        
        leaderboard = []
        for row in cursor.fetchall():
            leaderboard.append({
                'player_id': row[0],
                'player_name': row[1],
                'total_score': row[2],
                'wins': row[3],
                'total_games': row[4],
                'win_rate': row[3] / row[4] if row[4] > 0 else 0
            })
        
        conn.close()
        return leaderboard
    
    def get_game_history(self, player_id: str = None, limit: int = 20) -> List[Dict]:
        """获取游戏历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if player_id:
            cursor.execute('''
                SELECT gr.id, gr.room_id, gr.created_at, gd.role, gd.score_change
                FROM game_records gr
                JOIN game_details gd ON gr.id = gd.game_id
                WHERE gd.player_id = ?
                ORDER BY gr.created_at DESC
                LIMIT ?
            ''', (player_id, limit))
        else:
            cursor.execute('''
                SELECT gr.id, gr.room_id, gr.created_at, 
                       GROUP_CONCAT(gd.player_name || ':' || gd.role || ':' || gd.score_change)
                FROM game_records gr
                JOIN game_details gd ON gr.id = gd.game_id
                GROUP BY gr.id
                ORDER BY gr.created_at DESC
                LIMIT ?
            ''', (limit,))
        
        history = []
        for row in cursor.fetchall():
            if player_id:
                history.append({
                    'game_id': row[0],
                    'room_id': row[1],
                    'created_at': row[2],
                    'role': row[3],
                    'score_change': row[4]
                })
            else:
                players_info = []
                for info in row[3].split(','):
                    name, role, score = info.split(':')
                    players_info.append({
                        'name': name,
                        'role': role,
                        'score_change': int(score)
                    })
                
                history.append({
                    'game_id': row[0],
                    'room_id': row[1],
                    'created_at': row[2],
                    'players': players_info
                })
        
        conn.close()
        return history
    
    def _get_player_total_score(self, player_id: str) -> int:
        """获取玩家当前总积分"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT total_score FROM player_scores WHERE player_id = ?
        ''', (player_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        return row[0] if row else 0
    
    def calculate_multiplier(self, game: GameState) -> int:
        """计算游戏倍数"""
        multiplier = game.base_multiplier
        
        # 炸弹倍数
        multiplier *= (2 ** game.bomb_count)
        
        # 春天/反春天
        if game.winner:
            winner = game.players[game.winner]
            
            if winner.role == PlayerRole.LANDLORD:
                # 地主春天：农民一张牌都没出
                farmers = [p for p in game.players.values() if p.role == PlayerRole.FARMER]
                if all(len(p.cards) == 17 for p in farmers):
                    multiplier *= 2
            else:
                # 农民反春天：地主只出了一手牌
                landlord = next(p for p in game.players.values() if p.role == PlayerRole.LANDLORD)
                if len(landlord.cards) == 17:  # 地主还有17张牌（只出了一手牌）
                    multiplier *= 2
        
        return multiplier
    
    def calculate_scores(self, game: GameState) -> Dict[str, int]:
        """计算玩家得分"""
        multiplier = self.calculate_multiplier(game)
        base_score = 1  # 基础分
        
        scores = {}
        for player_id, player in game.players.items():
            if player.role == game.players[game.winner].role:
                # 获胜方得分
                if player.role == PlayerRole.LANDLORD:
                    scores[player_id] = base_score * multiplier * 2
                else:
                    scores[player_id] = base_score * multiplier
            else:
                # 失败方扣分
                scores[player_id] = -base_score * multiplier
        
        return scores
    
    def get_player_rank(self, player_id: str) -> Optional[Dict]:
        """获取玩家排名信息"""
        leaderboard = self.get_leaderboard(limit=100)
        
        for i, player in enumerate(leaderboard, 1):
            if player['player_id'] == player_id:
                return {
                    'rank': i,
                    'total_players': len(leaderboard),
                    **player
                }
        
        return None
    
    def export_stats(self, output_path: str = "data/stats_export.json"):
        """导出统计信息"""
        stats = {
            'timestamp': datetime.now().isoformat(),
            'leaderboard': self.get_leaderboard(limit=50),
            'total_games': self._get_total_games(),
            'total_players': self._get_total_players()
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        
        return output_path
    
    def _get_total_games(self) -> int:
        """获取总游戏数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM game_records')
        count = cursor.fetchone()[0]
        
        conn.close()
        return count
    
    def _get_total_players(self) -> int:
        """获取总玩家数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM player_scores')
        count = cursor.fetchone()[0]
        
        conn.close()
        return count


class ScoreCalculator:
    """分数计算器"""
    
    @staticmethod
    def calculate_final_score(base_score: int, multiplier: int, 
                            is_winner: bool, role: PlayerRole) -> int:
        """计算最终得分"""
        score = base_score * multiplier
        
        if is_winner:
            if role == PlayerRole.LANDLORD:
                return score * 2
            else:
                return score
        else:
            return -score
    
    @staticmethod
    def calculate_multiplier(base_multiplier: int, bomb_count: int, 
                           is_spring: bool = False) -> int:
        """计算倍数"""
        multiplier = base_multiplier
        multiplier *= (2 ** bomb_count)
        
        if is_spring:
            multiplier *= 2
        
        return multiplier
    
    @staticmethod
    def analyze_game_result(game: GameState) -> Dict:
        """分析游戏结果"""
        winner = game.players[game.winner]
        loser_role = PlayerRole.FARMER if winner.role == PlayerRole.LANDLORD else PlayerRole.LANDLORD
        
        # 检查是否春天
        is_spring = False
        if winner.role == PlayerRole.LANDLORD:
            farmers = [p for p in game.players.values() if p.role == PlayerRole.FARMER]
            is_spring = all(len(p.cards) == 17 for p in farmers)
        else:
            landlord = next(p for p in game.players.values() if p.role == PlayerRole.LANDLORD)
            is_spring = len(landlord.cards) == 17
        
        return {
            'winner': {
                'id': game.winner,
                'name': winner.name,
                'role': winner.role.value
            },
            'is_spring': is_spring,
            'bomb_count': game.bomb_count,
            'base_multiplier': game.base_multiplier,
            'final_multiplier': 2 ** game.bomb_count * (2 if is_spring else 1) * game.base_multiplier,
            'game_duration': (game.finished_at - game.started_at).total_seconds() if game.finished_at and game.started_at else 0
        }