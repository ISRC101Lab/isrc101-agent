"""
AI叫地主测试 - 验证AI在各种手牌情况下的叫分行为
"""

import pytest
from backend.card import Card, CardRank, CardSuit, CardUtils
from backend.game import GameState, Player
from backend.ai import SimpleAIPlayer, AIPlayerFactory


class TestAIBidding:
    """测试AI叫地主逻辑"""

    def test_good_hand_bids_at_least_2(self):
        """测试好牌叫2分以上 - 多个炸弹+大牌"""
        game = GameState("test_room")
        game.add_player("ai_player", "AI玩家", ai_type="simple")
        
        # 创建一手好牌：多个炸弹 + 大牌 (17张牌)
        # 质量 = 0.6725, 略低于0.7阈值, 实际叫2分
        good_hand = [
            # 炸弹: 4个A
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB),
            
            # 炸弹: 4个K
            Card(CardRank.KING, CardSuit.SPADE),
            Card(CardRank.KING, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.DIAMOND),
            Card(CardRank.KING, CardSuit.CLUB),
            
            # 大牌: 2个2
            Card(CardRank.TWO, CardSuit.SPADE),
            Card(CardRank.TWO, CardSuit.HEART),
            
            # 额外的牌
            Card(CardRank.QUEEN, CardSuit.SPADE),
            Card(CardRank.JACK, CardSuit.HEART),
            Card(CardRank.TEN, CardSuit.SPADE),
            Card(CardRank.NINE, CardSuit.HEART),
            Card(CardRank.EIGHT, CardSuit.SPADE),
            Card(CardRank.SEVEN, CardSuit.HEART),
            Card(CardRank.SIX, CardSuit.SPADE),
        ]
        
        game.players["ai_player"].cards = good_hand
        game.phase = game.phase.BIDDING
        
        ai_player = SimpleAIPlayer("ai_player")
        multiplier = ai_player.decide_bid(game, "ai_player")
        
        # 好牌(2炸弹)应该叫2分或以上
        assert multiplier >= 2, f"好牌应该叫2分或以上，实际叫了{multiplier}"

    def test_royal_hand_bids_3(self):
        """测试王炸+炸弹叫3分 - 王炸加普通炸弹"""
        game = GameState("test_room")
        game.add_player("ai_player", "AI玩家", ai_type="simple")
        
        # 创建一手有王炸+炸弹的好牌 (需要达到quality > 0.7才能叫3分)
        # 需要: 2炸弹(0.4) + 大牌(0.18) + 连牌(0.3) = 0.88
        royal_hand = [
            Card(CardRank.SMALL_JOKER),  # 小王
            Card(CardRank.BIG_JOKER),    # 大王 - 王炸
            
            # 炸弹: 4个A
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB),
            
            # 大牌: 2个2 + K
            Card(CardRank.TWO, CardSuit.SPADE),
            Card(CardRank.TWO, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.SPADE),
            Card(CardRank.KING, CardSuit.HEART),
            
            # 连牌
            Card(CardRank.QUEEN, CardSuit.SPADE),
            Card(CardRank.JACK, CardSuit.HEART),
            Card(CardRank.TEN, CardSuit.SPADE),
            Card(CardRank.NINE, CardSuit.HEART),
            Card(CardRank.EIGHT, CardSuit.SPADE),
            Card(CardRank.SEVEN, CardSuit.HEART),
            Card(CardRank.SIX, CardSuit.SPADE),
        ]
        
        game.players["ai_player"].cards = royal_hand
        game.phase = game.phase.BIDDING
        
        ai_player = SimpleAIPlayer("ai_player")
        multiplier = ai_player.decide_bid(game, "ai_player")
        
        # 有王炸+炸弹的好牌应该叫3分
        assert multiplier == 3, f"有王炸+炸弹的好牌应该叫3分，实际叫了{multiplier}"

    def test_medium_hand_bids_2(self):
        """测试中等牌叫2分"""
        game = GameState("test_room")
        game.add_player("ai_player", "AI玩家", ai_type="simple")
        
        # 创建一手中等牌：一个炸弹 + 一些大牌
        medium_hand = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB),  # 炸弹
            
            Card(CardRank.TWO, CardSuit.SPADE),
            Card(CardRank.KING, CardSuit.HEART),
            Card(CardRank.QUEEN, CardSuit.SPADE),
            Card(CardRank.JACK, CardSuit.HEART),
            Card(CardRank.TEN, CardSuit.SPADE),
            Card(CardRank.NINE, CardSuit.HEART),
            Card(CardRank.EIGHT, CardSuit.SPADE),
            Card(CardRank.SEVEN, CardSuit.HEART),
            Card(CardRank.SIX, CardSuit.SPADE),
            Card(CardRank.FIVE, CardSuit.HEART),
            Card(CardRank.FOUR, CardSuit.SPADE),
            Card(CardRank.THREE, CardSuit.HEART),
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
        ]
        
        game.players["ai_player"].cards = medium_hand
        game.phase = game.phase.BIDDING
        
        ai_player = SimpleAIPlayer("ai_player")
        multiplier = ai_player.decide_bid(game, "ai_player")
        
        # 中等牌应该叫2分
        assert multiplier == 2, f"中等牌应该叫2分，实际叫了{multiplier}"

    def test_poor_hand_bids_0(self):
        """测试差牌不叫"""
        game = GameState("test_room")
        game.add_player("ai_player", "AI玩家", ai_type="simple")
        
        # 创建一手差牌：没有炸弹，只有低牌
        poor_hand = [
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.THREE, CardSuit.HEART),
            Card(CardRank.FOUR, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
            Card(CardRank.FIVE, CardSuit.SPADE),
            Card(CardRank.FIVE, CardSuit.HEART),
            Card(CardRank.SIX, CardSuit.SPADE),
            Card(CardRank.SIX, CardSuit.HEART),
            Card(CardRank.SEVEN, CardSuit.SPADE),
            Card(CardRank.SEVEN, CardSuit.HEART),
            Card(CardRank.EIGHT, CardSuit.SPADE),
            Card(CardRank.EIGHT, CardSuit.HEART),
            Card(CardRank.NINE, CardSuit.SPADE),
            Card(CardRank.NINE, CardSuit.HEART),
            Card(CardRank.TEN, CardSuit.SPADE),
            Card(CardRank.JACK, CardSuit.HEART),
            Card(CardRank.QUEEN, CardSuit.SPADE),
            Card(CardRank.KING, CardSuit.HEART),
        ]
        
        game.players["ai_player"].cards = poor_hand
        game.phase = game.phase.BIDDING
        
        ai_player = SimpleAIPlayer("ai_player")
        multiplier = ai_player.decide_bid(game, "ai_player")
        
        # 差牌应该不叫(0分)
        assert multiplier == 0, f"差牌应该不叫(0分)，实际叫了{multiplier}"

    def test_straight_hand_bids_at_least_1(self):
        """测试有连牌的手至少叫1分"""
        game = GameState("test_room")
        game.add_player("ai_player", "AI玩家", ai_type="simple")
        
        # 创建一手有连牌的牌
        straight_hand = [
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
            Card(CardRank.FIVE, CardSuit.SPADE),
            Card(CardRank.SIX, CardSuit.HEART),
            Card(CardRank.SEVEN, CardSuit.SPADE),
            Card(CardRank.EIGHT, CardSuit.HEART),
            Card(CardRank.NINE, CardSuit.SPADE),
            Card(CardRank.TEN, CardSuit.HEART),
            Card(CardRank.JACK, CardSuit.SPADE),
            Card(CardRank.QUEEN, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.TWO, CardSuit.HEART),
            Card(CardRank.THREE, CardSuit.HEART),
            Card(CardRank.FOUR, CardSuit.DIAMOND),
            Card(CardRank.FIVE, CardSuit.DIAMOND),
            Card(CardRank.SIX, CardSuit.DIAMOND),
        ]
        
        game.players["ai_player"].cards = straight_hand
        game.phase = game.phase.BIDDING
        
        ai_player = SimpleAIPlayer("ai_player")
        multiplier = ai_player.decide_bid(game, "ai_player")
        
        # 有连牌的中等牌至少应该叫1分
        assert multiplier >= 1, f"有连牌的牌至少应该叫1分，实际叫了{multiplier}"


class TestAIPlayerFactory:
    """测试AI玩家工厂"""

    def test_create_simple_ai(self):
        """测试创建简单AI玩家"""
        ai = AIPlayerFactory.create_ai("simple", "test_ai", "测试AI")
        
        assert ai is not None
        assert ai.id == "test_ai"
        assert ai.name == "测试AI"
        assert isinstance(ai, SimpleAIPlayer)


class TestFullBiddingFlow:
    """测试完整叫牌流程"""

    def test_three_players_bidding_sequence(self):
        """测试三个AI玩家的完整叫牌流程"""
        game = GameState("test_room")
        
        # 添加3个AI玩家
        game.add_player("ai_1", "AI玩家1", ai_type="simple")
        game.add_player("ai_2", "AI玩家2", ai_type="simple")
        game.add_player("ai_3", "AI玩家3", ai_type="simple")
        
        # 开始游戏（发牌）
        game.start_game()
        
        # 验证游戏处于叫牌阶段
        assert game.phase == game.phase.BIDDING
        
        # 为每个玩家创建AI并叫分
        for player_id in game.players:
            ai = AIPlayerFactory.create_ai("simple", player_id)
            multiplier = ai.decide_bid(game, player_id)
            
            # 叫分应该在0-3之间
            assert 0 <= multiplier <= 3, f"叫分应该在0-3之间，实际为{multiplier}"
            
            # 执行叫分
            game.bid(player_id, multiplier)
        
        # 叫牌流程完成，应该确定地主
        assert game.landlord is not None or game.phase == game.phase.BIDDING
        
        # 如果确定地主，应该进入出牌阶段
        if game.landlord:
            assert game.phase == game.phase.PLAYING
            # 地主应该有20张牌（17张手牌+3张底牌）
            assert len(game.players[game.landlord].cards) == 20


if __name__ == "__main__":
    print("运行AI叫地主测试...")
    pytest.main([__file__, "-v"])
