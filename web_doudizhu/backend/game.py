"""
游戏状态机和规则验证模块
"""

import random
import json
from typing import List, Dict, Optional, Tuple, Set
from enum import Enum
from datetime import datetime
from .card import Card, CardUtils, CardPattern, CardPatternType


class GamePhase(Enum):
    """游戏阶段枚举"""
    WAITING = "等待开始"
    DEALING = "发牌"
    BIDDING = "叫地主"
    PLAYING = "出牌"
    FINISHED = "结束"


class PlayerRole(Enum):
    """玩家角色枚举"""
    FARMER = "农民"
    LANDLORD = "地主"


class GameState:
    """游戏状态类"""
    
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.phase = GamePhase.WAITING
        self.players = {}  # player_id -> Player
        self.deck = []
        self.current_player = None
        self.landlord = None
        self.base_multiplier = 1
        self.bomb_count = 0
        self.last_pattern = None
        self.last_player = None
        self.last_action = None  # 用于前端AI反馈: {type: 'bid'|'pass'|'play', multiplier: x, cards: [...]}
        self.history = []
        self.created_at = datetime.now()
        self.started_at = None
        self.finished_at = None
        self.winner = None
        
    def add_player(self, player_id: str, player_name: str, ai_type: str = None):
        """添加玩家"""
        if len(self.players) >= 3:
            raise ValueError("房间已满")
        
        player = Player(player_id, player_name, ai_type)
        self.players[player_id] = player
        
        if len(self.players) == 3:
            self.start_game()
    
    def start_game(self, skip_bidding: bool = False):
        """开始游戏
        skip_bidding: True则直接进入打牌阶段，跳过叫地主
        """
        self.phase = GamePhase.DEALING
        self.started_at = datetime.now()

        # 重置叫分状态
        self.bid_status = {}
        self.landlord = None
        self.base_multiplier = 1
        # 重开次数（防止无限循环）
        self.restart_count = 0

        # 创建并洗牌
        self.deck = CardUtils.create_deck()
        random.shuffle(self.deck)

        # 发牌
        player_ids = list(self.players.keys())
        for i, player_id in enumerate(player_ids):
            start = i * 17
            end = start + 17
            self.players[player_id].cards = self.deck[start:end]
            self.players[player_id].cards = CardUtils.sort_cards(self.players[player_id].cards)
            # 重置玩家角色
            self.players[player_id].role = PlayerRole.FARMER
            # 初始化叫分状态
            self.bid_status[player_id] = None

        # 留底牌
        self.deck = self.deck[51:54]  # 最后3张牌

        # 设置当前玩家为第一个玩家
        self.current_player = player_ids[0]

        if skip_bidding:
            # 直接进入打牌阶段，跳过叫地主
            # 随机指定一个地主
            self.landlord = player_ids[random.randint(0, 2)]
            self.players[self.landlord].role = PlayerRole.LANDLORD
            # 地主拿底牌
            self.players[self.landlord].cards.extend(self.deck)
            self.players[self.landlord].cards = CardUtils.sort_cards(self.players[self.landlord].cards)
            self.deck = []
            # 进入打牌阶段
            self.phase = GamePhase.PLAYING
            self.current_player = self.landlord
        else:
            self.phase = GamePhase.BIDDING
    
    def bid(self, player_id: str, multiplier: int) -> bool:
        """叫地主/抢地主"""
        if self.phase != GamePhase.BIDDING:
            return False
        
        if player_id != self.current_player:
            return False
        
        player_ids = list(self.players.keys())
        
        # 设置last_action用于前端AI反馈
        self.last_action = {
            'type': 'bid',
            'multiplier': multiplier,
            'player_id': player_id
        }
        
        # 记录叫地主的玩家
        if multiplier > 0:
            # 叫地主/抢地主
            if multiplier > self.base_multiplier:
                self.base_multiplier = multiplier
            
            # 如果之前已经有地主，现在被抢了
            if self.landlord is not None and self.landlord != player_id:
                # 之前的地主变成农民
                self.players[self.landlord].role = PlayerRole.FARMER
            
            self.landlord = player_id
            self.players[player_id].role = PlayerRole.LANDLORD
        
        # 记录每个玩家的叫分状态
        if not hasattr(self, 'bid_status'):
            self.bid_status = {pid: None for pid in player_ids}
        
        self.bid_status[player_id] = multiplier
        
        # 检查是否所有玩家都已经表态
        all_bid = all(v is not None for v in self.bid_status.values())
        
        if all_bid:
            # 所有玩家都表态了
            if self.landlord is None:
                # 没人叫地主，重新发牌（最多重开5次）
                if self.restart_count >= 5:
                    # 强制指定第一个玩家为地主
                    self.landlord = list(self.players.keys())[0]
                    self.players[self.landlord].role = PlayerRole.LANDLORD
                    self.players[self.landlord].cards.extend(self.deck)
                    self.players[self.landlord].cards = CardUtils.sort_cards(self.players[self.landlord].cards)
                    self.deck = []
                    self.phase = GamePhase.PLAYING
                    self.current_player = self.landlord
                    return True
                self.start_game()
                return True
            
            # 确定地主，获得底牌
            self.players[self.landlord].cards.extend(self.deck)
            self.players[self.landlord].cards = CardUtils.sort_cards(self.players[self.landlord].cards)
            self.deck = []
            
            # 进入出牌阶段
            self.phase = GamePhase.PLAYING
            self.current_player = self.landlord  # 地主先出牌
            return True
        
        # 下一个玩家
        current_index = player_ids.index(player_id)
        next_index = (current_index + 1) % 3
        self.current_player = player_ids[next_index]
        
        return True
    
    def play_cards(self, player_id: str, card_indices: List[int]) -> bool:
        """出牌"""
        if self.phase != GamePhase.PLAYING:
            return False
        
        if player_id != self.current_player:
            return False
        
        player = self.players[player_id]
        
        # 验证出牌索引
        if not all(0 <= idx < len(player.cards) for idx in card_indices):
            return False
        
        # 获取要出的牌
        cards_to_play = [player.cards[idx] for idx in sorted(card_indices, reverse=True)]
        
        # 判断牌型
        pattern = CardUtils.is_valid_pattern(cards_to_play)
        if pattern.pattern_type == CardPatternType.INVALID:
            return False
        
        # 验证出牌规则
        if not self._validate_play(player_id, pattern):
            return False
        
        # 设置last_action用于前端AI反馈
        self.last_action = {
            'type': 'play',
            'cards': [str(c) for c in cards_to_play],
            'player_id': player_id
        }
        
        # 记录炸弹
        if pattern.pattern_type in [CardPatternType.BOMB, CardPatternType.ROCKET]:
            self.bomb_count += 1
        
        # 移除玩家手中的牌
        for idx in sorted(card_indices, reverse=True):
            player.cards.pop(idx)
        
        # 更新游戏状态
        self.last_pattern = pattern
        self.last_player = player_id
        self.history.append({
            'player': player_id,
            'cards': [str(card) for card in cards_to_play],
            'pattern': pattern.pattern_type.value,
            'timestamp': datetime.now().isoformat()
        })
        
        # 检查游戏是否结束
        if len(player.cards) == 0:
            self._finish_game(player_id)
            return True
        
        # 更新当前玩家
        player_ids = list(self.players.keys())
        current_index = player_ids.index(player_id)
        next_index = (current_index + 1) % 3
        self.current_player = player_ids[next_index]
        
        # 如果下家是上家出牌的玩家，清空上家牌型（一轮结束）
        if self.current_player == self.last_player:
            self.last_pattern = None
            self.last_player = None
        
        return True
    
    def pass_turn(self, player_id: str) -> bool:
        """过牌"""
        if self.phase != GamePhase.PLAYING:
            return False
        
        if player_id != self.current_player:
            return False
        
        # 不能首轮过牌（除非是有人先出了牌）
        if self.last_pattern is None and len(self.history) == 0:
            return False
        
        # 设置last_action用于前端AI反馈
        self.last_action = {
            'type': 'pass',
            'player_id': player_id
        }
        
        # 更新当前玩家
        player_ids = list(self.players.keys())
        current_index = player_ids.index(player_id)
        next_index = (current_index + 1) % 3
        self.current_player = player_ids[next_index]
        
        # 如果下一家是last_player，说明一圈结束，清空上家牌型
        if self.current_player == self.last_player:
            self.last_pattern = None
            self.last_player = None
        
        return True
    
    def _validate_play(self, player_id: str, pattern: CardPattern) -> bool:
        """验证出牌是否合法"""
        # 如果是首轮出牌，必须包含黑桃3（地主除外）
        # 检查是否还有历史记录，如果没有则是首轮
        is_first_round = self.last_pattern is None and len(self.history) == 0
        
        if is_first_round:
            if self.landlord == player_id:
                # 地主首轮可以出任意牌
                return True
            
            # 农民首轮必须出包含黑桃3的牌
            player = self.players[player_id]
            
            # 检查出的牌是否包含黑桃3
            has_spade_3 = any(
                card.rank.value == 3 and card.suit.value == "♠" 
                for card in pattern.cards
            )
            
            if not has_spade_3:
                return False
            
            return True
        
        # 非首轮出牌，必须能压过上家
        if self.last_pattern is None:
            return True  # 没有上家，可以出任意合法牌型
            
        return CardUtils.can_beat(self.last_pattern, pattern)
    
    def _finish_game(self, winner_id: str):
        """结束游戏"""
        self.phase = GamePhase.FINISHED
        self.finished_at = datetime.now()
        self.winner = winner_id
        
        # 计算分数
        self._calculate_scores()
    
    def _calculate_scores(self):
        """计算分数"""
        winner = self.players[self.winner]
        
        # 基础倍数
        multiplier = self.base_multiplier
        
        # 炸弹倍数
        multiplier *= (2 ** self.bomb_count)
        
        # 春天/反春天
        if winner.role == PlayerRole.LANDLORD:
            # 地主春天：农民一张牌都没出
            farmers = [p for p in self.players.values() if p.role == PlayerRole.FARMER]
            if all(len(p.cards) == 17 for p in farmers):
                multiplier *= 2
        else:
            # 农民反春天：地主只出了一手牌
            landlord = next(p for p in self.players.values() if p.role == PlayerRole.LANDLORD)
            if len(landlord.cards) == 17:  # 地主还有17张牌（只出了一手牌）
                multiplier *= 2
        
        # 计算分数
        base_score = 1  # 基础分
        score = base_score * multiplier
        
        # 分配分数
        for player in self.players.values():
            if player.role == winner.role:
                player.score += score * 2 if winner.role == PlayerRole.LANDLORD else score
            else:
                player.score -= score
    
    def to_dict(self) -> Dict:
        """转换为字典（用于序列化）"""
        # 获取地主牌（底牌）- 在叫地主阶段显示底牌
        landlord_cards = []
        
        if self.phase.value == "叫地主":
            # 叫地主阶段，底牌还没分给地主
            landlord_cards = [str(c) for c in self.deck] if len(self.deck) == 3 else []
        elif self.landlord and self.phase.value == "出牌":
            # 出牌阶段，底牌已经在地主手里，这里返回空数组让前端不显示重复
            landlord_cards = []
        
        return {
            'room_id': self.room_id,
            'phase': self.phase.value,
            'players': {pid: p.to_dict() for pid, p in self.players.items()},
            'current_player': self.current_player,
            'landlord': self.landlord,
            'landlord_cards': landlord_cards,
            'base_multiplier': self.base_multiplier,
            'bomb_count': self.bomb_count,
            'last_pattern': self.last_pattern.pattern_type.value if self.last_pattern else None,
            'last_pattern_details': {
                'cards': [str(c) for c in self.last_pattern.cards] if self.last_pattern else [],
                'pattern_type': self.last_pattern.pattern_type.value if self.last_pattern else None
            } if self.last_pattern else None,
            'last_player': self.last_player,
            'last_action': self.last_action,
            'winner': self.winner,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'finished_at': self.finished_at.isoformat() if self.finished_at else None
        }


class Player:
    """玩家类"""
    
    def __init__(self, player_id: str, name: str, ai_type: str = None):
        self.id = player_id
        self.name = name
        self.cards = []
        self.role = PlayerRole.FARMER
        self.score = 0
        self.is_ready = False
        self.ai_type = ai_type  # AI类型（如果为None则是人类玩家）
    
    def to_dict(self) -> Dict:
        """转换为字典（用于序列化）"""
        return {
            'id': self.id,
            'name': self.name,
            'cards': [str(c) for c in self.cards],  # 添加手牌信息
            'card_count': len(self.cards),
            'role': self.role.value,
            'score': self.score,
            'is_ready': self.is_ready,
            'ai_type': self.ai_type
        }


class GameManager:
    """游戏管理器（单例）"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.games = {}
        return cls._instance
    
    def create_game(self, room_id: str) -> GameState:
        """创建新游戏"""
        if room_id in self.games:
            raise ValueError(f"房间 {room_id} 已存在")
        
        game = GameState(room_id)
        self.games[room_id] = game
        return game
    
    def get_game(self, room_id: str) -> Optional[GameState]:
        """获取游戏"""
        return self.games.get(room_id)
    
    def remove_game(self, room_id: str):
        """移除游戏"""
        if room_id in self.games:
            del self.games[room_id]
    
    def list_games(self) -> List[Dict]:
        """列出所有游戏"""
        return [
            {
                'room_id': room_id,
                'phase': game.phase.value,
                'player_count': len(game.players),
                'created_at': game.created_at.isoformat()
            }
            for room_id, game in self.games.items()
        ]