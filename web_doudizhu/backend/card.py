"""
扑克牌定义和牌型判断模块
"""

from enum import Enum
from typing import List, Tuple, Optional, Dict, Set


class CardSuit(Enum):
    """花色枚举"""
    SPADE = "♠"    # 黑桃
    HEART = "♥"    # 红心
    DIAMOND = "♦"  # 方块
    CLUB = "♣"     # 梅花
    JOKER = "🃏"   # 王


class CardRank(Enum):
    """点数枚举"""
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14
    TWO = 15
    SMALL_JOKER = 16  # 小王
    BIG_JOKER = 17    # 大王


class Card:
    """扑克牌类"""
    
    def __init__(self, rank: CardRank, suit: CardSuit = None):
        self.rank = rank
        self.suit = suit if suit else CardSuit.JOKER
        
    def __str__(self):
        if self.rank in [CardRank.SMALL_JOKER, CardRank.BIG_JOKER]:
            return "小王" if self.rank == CardRank.SMALL_JOKER else "大王"
        
        rank_str = {
            CardRank.THREE: "3",
            CardRank.FOUR: "4",
            CardRank.FIVE: "5",
            CardRank.SIX: "6",
            CardRank.SEVEN: "7",
            CardRank.EIGHT: "8",
            CardRank.NINE: "9",
            CardRank.TEN: "10",
            CardRank.JACK: "J",
            CardRank.QUEEN: "Q",
            CardRank.KING: "K",
            CardRank.ACE: "A",
            CardRank.TWO: "2"
        }.get(self.rank, str(self.rank.value))
        
        return f"{self.suit.value}{rank_str}"
    
    def __repr__(self):
        return str(self)
    
    def __eq__(self, other):
        if not isinstance(other, Card):
            return False
        return self.rank == other.rank and self.suit == other.suit
    
    def __hash__(self):
        return hash((self.rank, self.suit))
    
    @property
    def value(self) -> int:
        """获取牌的点数值（用于比较大小）"""
        return self.rank.value


class CardPatternType(Enum):
    """牌型枚举"""
    SINGLE = "单张"
    PAIR = "对子"
    TRIPLE = "三张"
    TRIPLE_WITH_SINGLE = "三带一"
    TRIPLE_WITH_PAIR = "三带二"
    STRAIGHT = "顺子"
    STRAIGHT_PAIR = "连对"
    AIRPLANE = "飞机"
    AIRPLANE_WITH_SINGLES = "飞机带单"
    AIRPLANE_WITH_PAIRS = "飞机带对"
    FOUR_WITH_TWO_SINGLES = "四带二单"
    FOUR_WITH_TWO_PAIRS = "四带二对"
    BOMB = "炸弹"
    ROCKET = "王炸"
    INVALID = "无效"


class CardPattern:
    """牌型类"""
    
    def __init__(self, pattern_type: CardPatternType, cards: List[Card], main_rank: CardRank = None):
        self.pattern_type = pattern_type
        self.cards = cards
        self.main_rank = main_rank  # 主要点数（用于比较大小）
        
    def __str__(self):
        return f"{self.pattern_type.value}: {self.cards}"
    
    def __repr__(self):
        return str(self)
    
    @property
    def value(self) -> int:
        """获取牌型的比较值"""
        if self.pattern_type == CardPatternType.ROCKET:
            return 1000  # 王炸最大
        elif self.pattern_type == CardPatternType.BOMB:
            return 900 + self.main_rank.value  # 炸弹次之
        elif self.main_rank:
            return self.main_rank.value
        return 0


class CardUtils:
    """牌型判断工具类"""
    
    @staticmethod
    def create_deck() -> List[Card]:
        """创建一副完整的扑克牌（54张）"""
        deck = []
        
        # 普通牌
        for suit in [CardSuit.SPADE, CardSuit.HEART, CardSuit.DIAMOND, CardSuit.CLUB]:
            for rank in [CardRank.THREE, CardRank.FOUR, CardRank.FIVE, CardRank.SIX,
                        CardRank.SEVEN, CardRank.EIGHT, CardRank.NINE, CardRank.TEN,
                        CardRank.JACK, CardRank.QUEEN, CardRank.KING, CardRank.ACE, CardRank.TWO]:
                deck.append(Card(rank, suit))
        
        # 大小王
        deck.append(Card(CardRank.SMALL_JOKER))
        deck.append(Card(CardRank.BIG_JOKER))
        
        return deck
    
    @staticmethod
    def sort_cards(cards: List[Card]) -> List[Card]:
        """按点数从小到大排序"""
        return sorted(cards, key=lambda c: c.value)
    
    @staticmethod
    def count_cards(cards: List[Card]) -> Dict[CardRank, int]:
        """统计每种点数的牌的数量"""
        count = {}
        for card in cards:
            count[card.rank] = count.get(card.rank, 0) + 1
        return count
    
    @staticmethod
    def is_valid_pattern(cards: List[Card]) -> Optional[CardPattern]:
        """判断一组牌是否构成有效牌型"""
        if not cards:
            return None
        
        sorted_cards = CardUtils.sort_cards(cards)
        card_count = CardUtils.count_cards(sorted_cards)
        
        # 单张
        if len(cards) == 1:
            return CardPattern(CardPatternType.SINGLE, sorted_cards, sorted_cards[0].rank)
        
        # 对子
        if len(cards) == 2 and len(card_count) == 1:
            rank = list(card_count.keys())[0]
            if rank not in [CardRank.SMALL_JOKER, CardRank.BIG_JOKER]:
                return CardPattern(CardPatternType.PAIR, sorted_cards, rank)
        
        # 王炸
        if len(cards) == 2:
            ranks = set(card.rank for card in cards)
            if ranks == {CardRank.SMALL_JOKER, CardRank.BIG_JOKER}:
                return CardPattern(CardPatternType.ROCKET, sorted_cards, CardRank.BIG_JOKER)
        
        # 三张
        if len(cards) == 3 and len(card_count) == 1:
            rank = list(card_count.keys())[0]
            return CardPattern(CardPatternType.TRIPLE, sorted_cards, rank)
        
        # 炸弹
        if len(cards) == 4 and len(card_count) == 1:
            rank = list(card_count.keys())[0]
            return CardPattern(CardPatternType.BOMB, sorted_cards, rank)
        
        # 三带一
        if len(cards) == 4:
            counts = list(card_count.values())
            if 3 in counts and 1 in counts:
                for rank, count in card_count.items():
                    if count == 3:
                        return CardPattern(CardPatternType.TRIPLE_WITH_SINGLE, sorted_cards, rank)
        
        # 三带二
        if len(cards) == 5:
            counts = list(card_count.values())
            if 3 in counts and 2 in counts:
                for rank, count in card_count.items():
                    if count == 3:
                        return CardPattern(CardPatternType.TRIPLE_WITH_PAIR, sorted_cards, rank)
        
        # 顺子（5张或以上连续点数）
        if len(cards) >= 5:
            ranks = sorted([card.rank for card in cards if card.rank.value <= CardRank.ACE.value])
            if len(ranks) == len(cards):  # 没有2和王
                values = [rank.value for rank in ranks]
                if all(values[i] + 1 == values[i+1] for i in range(len(values)-1)):
                    return CardPattern(CardPatternType.STRAIGHT, sorted_cards, ranks[-1])
        
        # 连对（3对或以上连续点数）
        if len(cards) >= 6 and len(cards) % 2 == 0:
            pair_ranks = []
            for rank, count in card_count.items():
                if count == 2 and rank.value <= CardRank.ACE.value:
                    pair_ranks.append(rank)
                else:
                    break
            if len(pair_ranks) >= 3:
                pair_ranks.sort(key=lambda r: r.value)
                values = [rank.value for rank in pair_ranks]
                if all(values[i] + 1 == values[i+1] for i in range(len(values)-1)):
                    return CardPattern(CardPatternType.STRAIGHT_PAIR, sorted_cards, pair_ranks[-1])
        
        # 飞机（2个或以上连续三张）
        if len(cards) >= 6:
            triple_ranks = []
            for rank, count in card_count.items():
                if count == 3 and rank.value <= CardRank.ACE.value:
                    triple_ranks.append(rank)
            if len(triple_ranks) >= 2:
                triple_ranks.sort(key=lambda r: r.value)
                values = [rank.value for rank in triple_ranks]
                if all(values[i] + 1 == values[i+1] for i in range(len(values)-1)):
                    # 纯飞机
                    if len(cards) == len(triple_ranks) * 3:
                        return CardPattern(CardPatternType.AIRPLANE, sorted_cards, triple_ranks[-1])
                    # 飞机带单
                    elif len(cards) == len(triple_ranks) * 4:
                        return CardPattern(CardPatternType.AIRPLANE_WITH_SINGLES, sorted_cards, triple_ranks[-1])
                    # 飞机带对
                    elif len(cards) == len(triple_ranks) * 5:
                        return CardPattern(CardPatternType.AIRPLANE_WITH_PAIRS, sorted_cards, triple_ranks[-1])
        
        # 四带二单
        if len(cards) == 6:
            counts = list(card_count.values())
            if 4 in counts and counts.count(1) == 2:
                for rank, count in card_count.items():
                    if count == 4:
                        return CardPattern(CardPatternType.FOUR_WITH_TWO_SINGLES, sorted_cards, rank)
        
        # 四带二对
        if len(cards) == 8:
            counts = list(card_count.values())
            if 4 in counts and counts.count(2) == 2:
                for rank, count in card_count.items():
                    if count == 4:
                        return CardPattern(CardPatternType.FOUR_WITH_TWO_PAIRS, sorted_cards, rank)
        
        return CardPattern(CardPatternType.INVALID, sorted_cards)
    
    @staticmethod
    def can_beat(prev_pattern: CardPattern, current_pattern: CardPattern) -> bool:
        """判断当前牌型是否能压过上家牌型"""
        if current_pattern.pattern_type == CardPatternType.INVALID:
            return False
        
        # 王炸可以压任何牌
        if current_pattern.pattern_type == CardPatternType.ROCKET:
            return True
        
        # 炸弹可以压非炸弹牌型
        if current_pattern.pattern_type == CardPatternType.BOMB:
            if prev_pattern.pattern_type not in [CardPatternType.BOMB, CardPatternType.ROCKET]:
                return True
            # 炸弹之间比较大小
            return current_pattern.value > prev_pattern.value
        
        # 相同牌型比较
        if current_pattern.pattern_type == prev_pattern.pattern_type:
            if len(current_pattern.cards) == len(prev_pattern.cards):
                return current_pattern.value > prev_pattern.value
        
        return False