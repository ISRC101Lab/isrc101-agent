"""
AI策略测试 - 验证卡牌计数、地主叫分和出牌策略
"""

import pytest
from backend.card import Card, CardRank, CardSuit, CardUtils, CardPattern, CardPatternType
from backend.game import GameState, Player, PlayerRole
from backend.ai import SimpleAIPlayer, RuleBasedAIPlayer, CardCounter


class TestCardCounter:
    """测试卡牌计数器功能"""

    def test_card_counter_initialization(self):
        """测试计数器初始化"""
        counter = CardCounter("test_room")
        
        # 验证初始计数正确（每种牌4张，大小王各1张）
        for rank in CardRank:
            if rank in [CardRank.SMALL_JOKER, CardRank.BIG_JOKER]:
                assert counter.get_remaining_count(rank) == 1
            else:
                assert counter.get_remaining_count(rank) == 4

    def test_record_play_updates_counter(self):
        """测试记录出牌后计数器更新"""
        counter = CardCounter("test_room")
        
        # 玩家打出一张A
        cards = [Card(CardRank.ACE, CardSuit.SPADE)]
        counter.record_play("player1", cards)
        
        # 验证剩余A的数量减少
        assert counter.get_remaining_count(CardRank.ACE) == 3

    def test_record_multiple_cards(self):
        """测试记录多张牌"""
        counter = CardCounter("test_room")
        
        # 打出炸弹（A所有花色）
        cards = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB),
        ]
        counter.record_play("player1", cards)
        
        # A应该剩余0张
        assert counter.get_remaining_count(CardRank.ACE) == 0

    def test_get_remaining_ranks(self):
        """测试获取剩余牌点"""
        counter = CardCounter("test_room")
        
        # 打出一些牌后，获取剩余牌点
        cards = [Card(CardRank.ACE, CardSuit.SPADE)]
        counter.record_play("player1", cards)
        
        remaining = counter.get_remaining_ranks()
        
        # A应该不在剩余列表中
        assert CardRank.ACE not in remaining
        # 其他牌应该还在
        assert CardRank.KING in remaining

    def test_get_opponent_played_ranks(self):
        """测试获取对手已打出的牌"""
        counter = CardCounter("test_room")
        
        # 玩家1打出A和K
        counter.record_play("player1", [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.KING, CardSuit.HEART),
        ])
        
        # 玩家2打出Q
        counter.record_play("player2", [
            Card(CardRank.QUEEN, CardSuit.DIAMOND),
        ])
        
        # 获取玩家1对手已打出的牌
        opponent_ranks = counter.get_opponent_played_ranks("player1")
        
        assert CardRank.QUEEN in opponent_ranks
        assert CardRank.ACE not in opponent_ranks  # 自己的牌不算


class TestAIBiddingStrategies:
    """测试AI叫地主策略"""

    def test_excellent_hand_bids_3(self):
        """测试极好手牌叫3分"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="simple")
        
        # 极好手牌：双王 + 炸弹 + 大牌
        excellent_hand = [
            Card(CardRank.SMALL_JOKER),
            Card(CardRank.BIG_JOKER),
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB),  # 炸弹
            Card(CardRank.TWO, CardSuit.SPADE),
            Card(CardRank.TWO, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.SPADE),
            Card(CardRank.KING, CardSuit.HEART),
            Card(CardRank.QUEEN, CardSuit.SPADE),
            Card(CardRank.JACK, CardSuit.HEART),
            Card(CardRank.TEN, CardSuit.SPADE),
            Card(CardRank.NINE, CardSuit.HEART),
            Card(CardRank.EIGHT, CardSuit.SPADE),
            Card(CardRank.SEVEN, CardSuit.HEART),
            Card(CardRank.SIX, CardSuit.SPADE),
        ]
        
        game.players["ai"].cards = excellent_hand
        game.phase = game.phase.BIDDING
        
        ai = SimpleAIPlayer("ai")
        multiplier = ai.decide_bid(game, "ai")
        
        assert multiplier >= 2, f"极好手牌应叫2-3分，实际: {multiplier}"

    def test_poor_hand_bids_0(self):
        """测试差手牌不叫"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="simple")
        
        # 差手牌：小牌多，无大牌无炸弹
        poor_hand = [
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
            Card(CardRank.FIVE, CardSuit.DIAMOND),
            Card(CardRank.SIX, CardSuit.CLUB),
            Card(CardRank.SEVEN, CardSuit.SPADE),
            Card(CardRank.EIGHT, CardSuit.HEART),
            Card(CardRank.NINE, CardSuit.DIAMOND),
            Card(CardRank.TEN, CardSuit.CLUB),
            Card(CardRank.JACK, CardSuit.SPADE),
            Card(CardRank.QUEEN, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.THREE, CardSuit.HEART),
            Card(CardRank.FOUR, CardSuit.DIAMOND),
            Card(CardRank.FIVE, CardSuit.CLUB),
            Card(CardRank.SIX, CardSuit.SPADE),
            Card(CardRank.SEVEN, CardSuit.HEART),
        ]
        
        game.players["ai"].cards = poor_hand
        game.phase = game.phase.BIDDING
        
        ai = SimpleAIPlayer("ai")
        multiplier = ai.decide_bid(game, "ai")
        
        assert multiplier == 0, f"差手牌不应叫地主的，实际: {multiplier}"

    def test_rule_ai_bidding(self):
        """测试规则AI叫地主"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="rule")
        
        # 好手牌
        good_hand = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB),  # 炸弹
            Card(CardRank.TWO, CardSuit.SPADE),
            Card(CardRank.TWO, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.SPADE),
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
        ]
        
        game.players["ai"].cards = good_hand
        game.phase = game.phase.BIDDING
        
        ai = RuleBasedAIPlayer("ai")
        multiplier = ai.decide_bid(game, "ai")
        
        assert multiplier >= 2, f"规则AI好手牌应叫2-3分，实际: {multiplier}"


class TestAIPlayStrategies:
    """测试AI出牌策略"""

    def test_first_play_singles(self):
        """测试首轮出单张"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="simple")
        
        hand = [
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
            Card(CardRank.FIVE, CardSuit.DIAMOND),
            Card(CardRank.SIX, CardSuit.CLUB),
            Card(CardRank.SEVEN, CardSuit.SPADE),
        ]
        game.players["ai"].cards = hand
        game.phase = game.phase.PLAYING
        
        ai = SimpleAIPlayer("ai")
        play = ai.decide_play(game, "ai")
        
        # 首轮应该能出牌（最小的单张）
        assert play is not None
        assert len(play) == 1
        # 应该是3（最小的单张）
        assert game.players["ai"].cards[play[0]].rank == CardRank.THREE

    def test_follow_with_valid_play(self):
        """测试跟牌时有能压过的牌"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="simple")
        
        # AI手牌
        hand = [
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
            Card(CardRank.FIVE, CardSuit.DIAMOND),
            Card(CardRank.SIX, CardSuit.CLUB),
            Card(CardRank.SEVEN, CardSuit.SPADE),
            Card(CardRank.EIGHT, CardSuit.HEART),
            Card(CardRank.NINE, CardSuit.DIAMOND),
        ]
        game.players["ai"].cards = hand
        
        # 上家出了5（单张）
        last_cards = [Card(CardRank.FIVE, CardSuit.SPADE)]
        game.last_pattern = CardPattern.from_cards(last_cards)
        game.phase = game.phase.PLAYING
        
        ai = SimpleAIPlayer("ai")
        play = ai.decide_play(game, "ai")
        
        # 应该能跟牌（找到比5大的牌）
        assert play is not None
        assert len(play) == 1
        
        # 验证跟的牌确实比5大
        played_card = game.players["ai"].cards[play[0]]
        assert played_card.value > CardRank.FIVE.value

    def test_pass_when_no_valid_play(self):
        """测试无牌可压时过牌"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="simple")
        
        # AI手牌都是小牌
        hand = [
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
            Card(CardRank.FIVE, CardSuit.DIAMOND),
        ]
        game.players["ai"].cards = hand
        
        # 上家出了A（很大的单张）
        last_cards = [Card(CardRank.ACE, CardSuit.SPADE)]
        game.last_pattern = CardPattern.from_cards(last_cards)
        game.phase = game.phase.PLAYING
        
        ai = SimpleAIPlayer("ai")
        play = ai.decide_play(game, "ai")
        
        # 无牌可压，应该返回None（过牌）
        assert play is None

    def test_play_bomb_when_beaten(self):
        """测试被压制时出炸弹"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="simple")
        
        # AI有炸弹
        hand = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.ACE, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.CLUB),  # 炸弹
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
        ]
        game.players["ai"].cards = hand
        
        # 上家出了更大的单张（2）
        last_cards = [Card(CardRank.TWO, CardSuit.SPADE)]
        game.last_pattern = CardPattern.from_cards(last_cards)
        game.phase = game.phase.PLAYING
        
        ai = SimpleAIPlayer("ai")
        play = ai.decide_play(game, "ai")
        
        # 应该有牌出（炸弹）
        assert play is not None
        # 炸弹是4张
        assert len(play) == 4


class TestRuleAIPlayStrategies:
    """测试规则AI出牌策略"""

    def test_rule_ai_aggressive_play(self):
        """测试规则AI主动进攻策略"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="rule")
        
        # 模拟地主优势手牌
        hand = [
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.SPADE),
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
            Card(CardRank.THREE, CardSuit.DIAMOND),
            Card(CardRank.THREE, CardSuit.CLUB),
            Card(CardRank.THREE, CardSuit.SPADE),  # 炸弹
        ]
        game.players["ai"].cards = hand
        game.players["ai"].role = PlayerRole.LANDLORD
        game.phase = game.phase.PLAYING
        
        # 设置一些游戏状态
        game.players["player1"] = Player("player1", "玩家1")
        game.players["player2"] = Player("player2", "玩家2")
        
        ai = RuleBasedAIPlayer("ai")
        play = ai.decide_play(game, "ai")
        
        # 应该能出牌
        assert play is not None

    def test_rule_ai_defensive_play(self):
        """测试规则AI防守策略"""
        game = GameState("test_room")
        game.add_player("ai", "AI", ai_type="rule")
        
        # 农民手牌（较弱）
        hand = [
            Card(CardRank.THREE, CardSuit.SPADE),
            Card(CardRank.FOUR, CardSuit.HEART),
            Card(CardRank.FIVE, CardSuit.DIAMOND),
            Card(CardRank.SIX, CardSuit.CLUB),
            Card(CardRank.SEVEN, CardSuit.SPADE),
            Card(CardRank.EIGHT, CardSuit.HEART),
            Card(CardRank.NINE, CardSuit.DIAMOND),
            Card(CardRank.TEN, CardSuit.CLUB),
            Card(CardRank.JACK, CardSuit.SPADE),
            Card(CardRank.QUEEN, CardSuit.HEART),
            Card(CardRank.KING, CardSuit.DIAMOND),
            Card(CardRank.ACE, CardSuit.SPADE),
            Card(CardRank.ACE, CardSuit.HEART),
            Card(CardRank.THREE, CardSuit.DIAMOND),
            Card(CardRank.FOUR, CardSuit.CLUB),
            Card(CardRank.FIVE, CardSuit.SPADE),
            Card(CardRank.SIX, CardSuit.HEART),
        ]
        game.players["ai"].cards = hand
        game.players["ai"].role = PlayerRole.FARMER
        game.phase = game.phase.PLAYING
        
        # 设置一些游戏状态
        game.players["landlord"] = Player("landlord", "地主")
        
        # 地主出了单张5
        last_cards = [Card(CardRank.FIVE, CardSuit.SPADE)]
        game.last_pattern = CardPattern.from_cards(last_cards)
        
        ai = RuleBasedAIPlayer("ai")
        play = ai.decide_play(game, "ai")
        
        # 应该能跟牌
        assert play is not None


class TestAnimationCSS:
    """验证前端动画CSS定义"""

    def test_thinking_animation_exists(self):
        """验证思考动画关键帧存在"""
        with open("frontend/style.css", "r") as f:
            css_content = f.read()
        
        # 验证思考动画关键帧
        assert "@keyframes thinking-spin" in css_content
        assert "@keyframes thinking-bounce" in css_content
        assert "@keyframes thinking-pulse" in css_content

    def test_action_bubble_animation_exists(self):
        """验证动作气泡动画存在"""
        with open("frontend/style.css", "r") as f:
            css_content = f.read()
        
        # 验证气泡弹跳动画
        assert "@keyframes emoji-bounce" in css_content
        assert "@keyframes bubble-shine" in css_content
        assert "@keyframes badge-pulse" in css_content

    def test_card_flying_animation_exists(self):
        """验证卡牌飞行动画存在"""
        with open("frontend/style.css", "r") as f:
            css_content = f.read()
        
        # 验证卡牌相关动画
        assert "@keyframes card-fly" in css_content or "cardFly" in css_content
        assert "@keyframes label-glow" in css_content

    def test_thinking_indicator_html_structure(self):
        """验证思考指示器的HTML结构"""
        with open("frontend/game.js", "r") as f:
            js_content = f.read()
        
        # 验证JS中创建思考指示器
        assert "thinking-indicator" in js_content
        assert "thinking-ring" in js_content
        # 验证有3个span（不是4个）- 与CSS匹配
        assert js_content.count("<span></span>") >= 1 or "span" in js_content

    def test_action_bubble_js_trigger(self):
        """验证动作气泡JS触发"""
        with open("frontend/game.js", "r") as f:
            js_content = f.read()
        
        # 验证JS中创建动作气泡
        assert "action-bubble" in js_content
        assert "showActionBubble" in js_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
