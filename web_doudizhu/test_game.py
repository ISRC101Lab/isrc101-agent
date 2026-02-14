"""
斗地主游戏测试
"""

import pytest
from backend.card import Card, CardRank, CardSuit, CardUtils, CardPattern, CardPatternType
from backend.game import GameState, Player, GameManager


class TestCard:
    """测试扑克牌相关功能"""
    
    def test_card_creation(self):
        """测试创建扑克牌"""
        card = Card(CardRank.ACE, CardSuit.SPADE)
        assert card.rank == CardRank.ACE
        assert card.suit == CardSuit.SPADE
        
    def test_joker_card(self):
        """测试王牌"""
        small_joker = Card(CardRank.SMALL_JOKER)
        big_joker = Card(CardRank.BIG_JOKER)
        
        assert small_joker.rank == CardRank.SMALL_JOKER
        assert big_joker.rank == CardRank.BIG_JOKER
        assert small_joker.suit.value == "🃏"
        
    def test_card_comparison(self):
        """测试牌的大小比较"""
        card1 = Card(CardRank.THREE, CardSuit.SPADE)
        card2 = Card(CardRank.FOUR, CardSuit.SPADE)
        card3 = Card(CardRank.TWO, CardSuit.SPADE)
        
        assert card1.value < card2.value
        assert card3.value > card2.value


class TestCardPattern:
    """测试牌型判断"""
    
    def test_single_card(self):
        """测试单张牌型"""
        cards = [Card(CardRank.ACE, CardSuit.SPADE)]
        pattern = CardUtils.is_valid_pattern(cards)
        
        assert pattern is not None
        assert pattern.pattern_type == CardPatternType.SINGLE
        
    def test_pair(self):
        """测试对子牌型"""
        cards = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART)
        ]
        pattern = CardUtils.is_valid_pattern(cards)
        
        assert pattern is not None
        assert pattern.pattern_type == CardPatternType.PAIR
        
    def test_triplet(self):
        """测试三张牌型"""
        cards = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND)
        ]
        pattern = CardUtils.is_valid_pattern(cards)
        
        assert pattern is not None
        assert pattern.pattern_type == CardPatternType.TRIPLE
        
    def test_bomb(self):
        """测试炸弹牌型"""
        cards = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB)
        ]
        pattern = CardUtils.is_valid_pattern(cards)
        
        assert pattern is not None
        assert pattern.pattern_type == CardPatternType.BOMB
        
    def test_rocket(self):
        """测试火箭牌型"""
        cards = [
            Card(CardRank.SMALL_JOKER),
            Card(CardRank.BIG_JOKER)
        ]
        pattern = CardUtils.is_valid_pattern(cards)
        
        assert pattern is not None
        assert pattern.pattern_type == CardPatternType.ROCKET


class TestGame:
    """测试游戏逻辑"""
    
    def test_game_creation(self):
        """测试创建游戏"""
        game = GameState("test_room")
        assert game.room_id == "test_room"
        assert len(game.players) == 0
        
    def test_add_player(self):
        """测试添加玩家"""
        game = GameState("test_room")
        game.add_player("player1", "玩家1")
        
        assert len(game.players) == 1
        assert "player1" in game.players
        assert game.players["player1"].name == "玩家1"
        
    def test_deal_cards(self):
        """测试发牌"""
        game = GameState("test_room")
        game.add_player("player1", "玩家1")
        game.add_player("player2", "玩家2")
        game.add_player("player3", "玩家3")
        
        game.start_game()
        
        # 每个玩家应该有17张牌，底牌有3张
        for player_id in game.players:
            player = game.players[player_id]
            assert len(player.cards) == 17
            
        assert len(game.deck) == 3  # 底牌


if __name__ == "__main__":
    print("运行斗地主游戏测试...")
    pytest.main([__file__, "-v"])