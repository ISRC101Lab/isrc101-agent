"""
AI玩家策略模块
"""

import random
from typing import List, Dict, Optional, Tuple
from .card import Card, CardUtils, CardPattern, CardPatternType
from .game import GameState, PlayerRole


class AIPlayer:
    """AI玩家基类"""
    
    def __init__(self, player_id: str, name: str = "AI玩家"):
        self.id = player_id
        self.name = name
        self.difficulty = "medium"
    
    def decide_bid(self, game: GameState, player_id: str) -> int:
        """决定叫地主倍数"""
        raise NotImplementedError
    
    def decide_play(self, game: GameState, player_id: str) -> Optional[List[int]]:
        """决定出牌（返回牌索引列表）"""
        raise NotImplementedError
    
    def decide_pass(self, game: GameState, player_id: str) -> bool:
        """决定是否过牌"""
        raise NotImplementedError


class SimpleAIPlayer(AIPlayer):
    """简单AI玩家（基于规则）"""
    
    def __init__(self, player_id: str, name: str = "简单AI"):
        super().__init__(player_id, name)
        self.difficulty = "easy"
    
    def decide_bid(self, game: GameState, player_id: str) -> int:
        """简单叫地主策略：根据手牌质量决定"""
        player = game.players[player_id]
        cards = player.cards
        
        # 计算手牌质量
        quality = self._calculate_hand_quality(cards)
        
        # 根据质量决定叫地主倍数
        if quality > 0.7:
            return 3  # 好牌叫3分
        elif quality > 0.5:
            return 2  # 中等牌叫2分
        elif quality > 0.3:
            return 1  # 差牌叫1分
        else:
            return 0  # 不叫
    
    def decide_play(self, game: GameState, player_id: str) -> Optional[List[int]]:
        """简单出牌策略"""
        player = game.players[player_id]
        cards = player.cards
        
        # 如果是首轮出牌
        if game.last_pattern is None:
            return self._first_play(cards, player.role == PlayerRole.LANDLORD)
        
        # 如果有能压过的牌
        valid_plays = self._find_valid_plays(cards, game.last_pattern)
        if valid_plays:
            # 选择最小的能压过的牌
            return self._select_best_play(valid_plays, cards, strategy="min")
        
        # 没有能压过的牌，考虑出炸弹
        bombs = self._find_bombs(cards)
        if bombs and self._should_play_bomb(game, player_id):
            # 选择最小的炸弹
            return min(bombs, key=lambda x: max(cards[i].value for i in x))
        
        # 没有能出的牌，返回None（表示要过牌）
        return None
    
    def decide_pass(self, game: GameState, player_id: str) -> bool:
        """决定是否过牌"""
        player = game.players[player_id]
        
        # 如果有能压过的牌但不想出
        if game.last_pattern is not None:
            valid_plays = self._find_valid_plays(player.cards, game.last_pattern)
            if valid_plays:
                # 根据手牌质量决定是否过牌
                quality = self._calculate_hand_quality(player.cards)
                if quality < 0.4:  # 手牌差，尽量过牌
                    return True
                # 如果牌很大但想保留，也过牌
                if self._has_good_cards_to_keep(player.cards):
                    return True
        
        return False
    
    def _calculate_hand_quality(self, cards: List[Card]) -> float:
        """计算手牌质量（0-1）"""
        if not cards:
            return 0
        
        # 计算大牌数量
        big_cards = sum(1 for card in cards if card.value >= 14)  # A、2、王
        
        # 计算炸弹数量
        bomb_count = len(self._find_all_bombs(cards))
        
        # 计算连牌潜力
        straight_potential = self._calculate_straight_potential(cards)
        
        # 综合质量
        quality = (
            (big_cards / len(cards) * 0.3) +
            (min(bomb_count, 3) / 3 * 0.4) +
            (straight_potential * 0.3)
        )
        
        return min(quality, 1.0)
    
    def _find_all_bombs(self, cards: List[Card]) -> List[List[int]]:
        """找到所有炸弹"""
        bombs = []
        card_count = CardUtils.count_cards(cards)
        
        # 普通炸弹
        for rank, count in card_count.items():
            if count == 4:
                indices = [i for i, card in enumerate(cards) if card.rank == rank]
                bombs.append(indices)
        
        # 王炸
        small_joker = next((i for i, card in enumerate(cards) if card.rank.value == 16), None)
        big_joker = next((i for i, card in enumerate(cards) if card.rank.value == 17), None)
        if small_joker is not None and big_joker is not None:
            bombs.append([small_joker, big_joker])
        
        return bombs
    
    def _find_bombs(self, cards: List[Card]) -> List[List[int]]:
        """找到炸弹（简化版）"""
        return self._find_all_bombs(cards)
    
    def _calculate_straight_potential(self, cards: List[Card]) -> float:
        """计算连牌潜力"""
        # 统计连续点数
        values = sorted(set(card.value for card in cards if card.value <= 14))  # 排除2和王
        
        if len(values) < 2:
            return 0
        
        max_straight = 1
        current_straight = 1
        
        for i in range(1, len(values)):
            if values[i] == values[i-1] + 1:
                current_straight += 1
                max_straight = max(max_straight, current_straight)
            else:
                current_straight = 1
        
        return min(max_straight / 8, 1.0)  # 最长8连
    
    def _first_play(self, cards: List[Card], is_landlord: bool) -> List[int]:
        """首轮出牌策略"""
        # 地主出最小的单张
        if is_landlord:
            return [0]  # 最小牌
        
        # 农民必须出包含黑桃3的牌
        spade_3_index = next((i for i, card in enumerate(cards) 
                             if card.value == 3 and card.suit.value == "♠"), None)
        
        if spade_3_index is not None:
            # 尝试出单张黑桃3
            return [spade_3_index]
        
        # 如果没有黑桃3（不应该发生），出最小牌
        return [0]
    
    def _find_valid_plays(self, cards: List[Card], last_pattern: CardPattern) -> List[List[int]]:
        """找到所有能压过上家的出牌组合"""
        valid_plays = []
        
        # 生成所有可能的出牌组合
        all_combinations = self._generate_combinations(cards, len(last_pattern.cards))
        
        for combo in all_combinations:
            combo_cards = [cards[i] for i in combo]
            pattern = CardUtils.is_valid_pattern(combo_cards)
            
            if (pattern.pattern_type != CardPatternType.INVALID and 
                CardUtils.can_beat(last_pattern, pattern)):
                valid_plays.append(combo)
        
        return valid_plays
    
    def _generate_combinations(self, cards: List[Card], size: int) -> List[List[int]]:
        """生成指定大小的组合（简化版，只生成部分）"""
        combinations = []
        n = len(cards)
        
        # 限制组合数量，避免性能问题
        max_combinations = 100
        
        # 生成单张、对子、三张等简单组合
        if size == 1:
            return [[i] for i in range(n)]
        elif size == 2:
            # 只考虑相同点数的对子
            card_count = CardUtils.count_cards(cards)
            for rank, count in card_count.items():
                if count >= 2:
                    indices = [i for i, card in enumerate(cards) if card.rank == rank]
                    combinations.append(indices[:2])
        
        # 添加更多组合逻辑（简化）
        return combinations[:max_combinations]
    
    def _select_best_play(self, valid_plays: List[List[int]], cards: List[Card], 
                         strategy: str = "min") -> List[int]:
        """选择最佳出牌"""
        if not valid_plays:
            return []
        
        if strategy == "min":
            # 选择点数最小的牌
            return min(valid_plays, key=lambda x: max(cards[i].value for i in x))
        elif strategy == "max":
            # 选择点数最大的牌
            return max(valid_plays, key=lambda x: max(cards[i].value for i in x))
        else:
            # 默认选择第一个
            return valid_plays[0]
    
    def _has_good_cards_to_keep(self, cards: List[Card]) -> bool:
        """判断是否有好牌需要保留"""
        # 检查是否有炸弹
        bombs = self._find_bombs(cards)
        if bombs:
            return True
        
        # 检查是否有大牌（2、A、K）
        big_cards = [card for card in cards if card.value >= 13]
        return len(big_cards) >= 3
    
    def _should_play_bomb(self, game: GameState, player_id: str) -> bool:
        """判断是否应该出炸弹"""
        player = game.players[player_id]
        
        # 如果是地主且手牌很少，出炸弹
        if player.role == PlayerRole.LANDLORD and len(player.cards) <= 5:
            return True
        
        # 如果是农民且队友手牌很少，出炸弹
        if player.role == PlayerRole.FARMER:
            teammates = [p for p in game.players.values() 
                        if p.role == PlayerRole.FARMER and p.id != player_id]
            if teammates and len(teammates[0].cards) <= 3:
                return True
        
        # 随机决定（简化）
        return random.random() > 0.7


class RuleBasedAIPlayer(AIPlayer):
    """基于规则的AI玩家（更智能）"""
    
    def __init__(self, player_id: str, name: str = "规则AI"):
        super().__init__(player_id, name)
        self.difficulty = "medium"
        self.memory = {}  # 记忆其他玩家出过的牌
    
    def decide_bid(self, game: GameState, player_id: str) -> int:
        """基于规则的叫地主策略"""
        player = game.players[player_id]
        cards = player.cards
        
        # 评估手牌
        score = self._evaluate_hand(cards)
        
        # 根据分数决定叫地主
        if score >= 80:
            return 3
        elif score >= 60:
            return 2
        elif score >= 40:
            return 1
        else:
            return 0
    
    def decide_play(self, game: GameState, player_id: str) -> Optional[List[int]]:
        """基于规则的出牌策略"""
        # 更新记忆
        self._update_memory(game)
        
        player = game.players[player_id]
        cards = player.cards
        
        # 分析局势
        situation = self._analyze_situation(game, player_id)
        
        # 根据局势选择策略
        if situation == "dominant":
            return self._aggressive_play(cards, game.last_pattern)
        elif situation == "defensive":
            return self._defensive_play(cards, game.last_pattern)
        else:
            return self._neutral_play(cards, game.last_pattern)
    
    def _evaluate_hand(self, cards: List[Card]) -> int:
        """评估手牌质量（0-100）"""
        if not cards:
            return 0
        
        score = 0
        
        # 大牌分数
        for card in cards:
            if card.value == 17:  # 大王
                score += 20
            elif card.value == 16:  # 小王
                score += 15
            elif card.value == 15:  # 2
                score += 10
            elif card.value == 14:  # A
                score += 8
            elif card.value == 13:  # K
                score += 6
            elif card.value == 12:  # Q
                score += 5
        
        # 炸弹分数
        bombs = self._find_all_bombs(cards)
        score += len(bombs) * 25
        
        # 连牌分数
        straight_score = self._calculate_straight_score(cards)
        score += straight_score
        
        # 控制分数范围
        return min(score, 100)
    
    def _calculate_straight_score(self, cards: List[Card]) -> int:
        """计算连牌分数"""
        # 简化实现
        values = sorted(card.value for card in cards if card.value <= 14)
        
        if len(values) < 5:
            return 0
        
        max_len = 1
        current_len = 1
        
        for i in range(1, len(values)):
            if values[i] == values[i-1] + 1:
                current_len += 1
                max_len = max(max_len, current_len)
            else:
                current_len = 1
        
        if max_len >= 5:
            return (max_len - 4) * 5  # 每多一张加5分
        
        return 0
    
    def _update_memory(self, game: GameState):
        """更新记忆（记录出过的牌）"""
        # 简化实现：只记录最近一轮
        if game.history:
            last_play = game.history[-1]
            player = last_play['player']
            cards = last_play['cards']
            
            if player not in self.memory:
                self.memory[player] = []
            
            self.memory[player].extend(cards)
    
    def _analyze_situation(self, game: GameState, player_id: str) -> str:
        """分析当前局势"""
        player = game.players[player_id]
        
        # 计算手牌数量优势
        card_counts = [len(p.cards) for p in game.players.values()]
        my_count = len(player.cards)
        
        # 如果手牌很少，处于优势
        if my_count <= 5:
            return "dominant"
        
        # 如果手牌很多，处于劣势
        if my_count >= 15:
            return "defensive"
        
        return "neutral"
    
    def _aggressive_play(self, cards: List[Card], last_pattern: CardPattern) -> Optional[List[int]]:
        """进攻性出牌策略"""
        # 尽量出大牌压制
        if last_pattern is None:
            # 首轮出中等牌
            mid_index = len(cards) // 2
            return [mid_index]
        
        # 找能压过的最小牌
        valid_plays = self._find_valid_plays(cards, last_pattern)
        if valid_plays:
            return self._select_best_play(valid_plays, cards, strategy="min")
        
        return None
    
    def _defensive_play(self, cards: List[Card], last_pattern: CardPattern) -> Optional[List[int]]:
        """防守性出牌策略"""
        # 尽量保留好牌
        if last_pattern is None:
            # 首轮出小牌
            return [0]
        
        # 只有必要时才压牌
        valid_plays = self._find_valid_plays(cards, last_pattern)
        if valid_plays:
            # 选择最小的压牌
            return self._select_best_play(valid_plays, cards, strategy="min")
        
        return None
    
    def _neutral_play(self, cards: List[Card], last_pattern: CardPattern) -> Optional[List[int]]:
        """中性出牌策略"""
        # 使用简单AI的策略
        simple_ai = SimpleAIPlayer("temp")
        return simple_ai.decide_play(None, cards, last_pattern)
    
    # 复用简单AI的一些方法
    _find_valid_plays = SimpleAIPlayer._find_valid_plays
    _select_best_play = SimpleAIPlayer._select_best_play
    _find_all_bombs = SimpleAIPlayer._find_all_bombs


# AI工厂
class AIPlayerFactory:
    """AI玩家工厂"""
    
    @staticmethod
    def create_ai(ai_type: str, player_id: str, name: str = None) -> AIPlayer:
        """创建AI玩家"""
        if ai_type == "simple":
            return SimpleAIPlayer(player_id, name or "简单AI")
        elif ai_type == "rule_based":
            return RuleBasedAIPlayer(player_id, name or "规则AI")
        else:
            raise ValueError(f"未知的AI类型: {ai_type}")