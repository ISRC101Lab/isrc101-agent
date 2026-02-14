"""斗地主风格UI - 扑克牌组件"""

from dataclasses import dataclass
from typing import Optional
from rich.console import Console
from rich.text import Text
from rich.style import Style
from rich.color import Color

from ..rendering import get_icon


# 牌的花色
class Suit:
    """扑克牌花色"""
    SPADES = "♠"      # 黑桃
    HEARTS = "♥"      # 红心
    CLUBS = "♣"       # 梅花
    DIAMONDS = "♦"     # 方块
    JOKER = "🃏"       # 王牌
    
    # 颜色
    RED = "#F85149"    # 红桃/方块
    BLACK = "#E6EDF3"  # 黑桃/梅花


# 特殊牌面
class Rank:
    """扑克牌点数"""
    Joker = "Joker"
    Two = "2"
    Three = "3"
    Four = "4"
    Five = "5"
    Six = "6"
    Seven = "7"
    Eight = "8"
    Nine = "9"
    Ten = "10"
    Jack = "J"
    Queen = "Q"
    King = "K"
    Ace = "A"
    
    @staticmethod
    def all():
        return ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2", "Joker"]


# 工具牌类型 - 映射到具体工具
TOOL_CARD_MAP = {
    "read_file": ("📄", "读文件", Suit.CLUBS, "4"),
    "write_file": ("✏️", "写文件", Suit.CLUBS, "5"),
    "str_replace": ("✏️", "编辑", Suit.CLUBS, "6"),
    "delete_file": ("🗑️", "删除", Suit.CLUBS, "7"),
    "list_directory": ("📁", "目录", Suit.CLUBS, "8"),
    "find_files": ("🔍", "搜索", Suit.CLUBS, "9"),
    "search_files": ("🔍", "搜索", Suit.CLUBS, "10"),
    "bash": ("💻", "终端", Suit.SPADES, "J"),
    "web_fetch": ("🌐", "网页", Suit.HEARTS, "Q"),
    "web_search": ("🌐", "搜索", Suit.HEARTS, "K"),
    "read_image": ("📷", "图片", Suit.HEARTS, "A"),
    "create_file": ("✨", "新建", Suit.DIAMONDS, "2"),
    "find_symbol": ("📋", "符号", Suit.DIAMONDS, "3"),
}


# 消息类型 - 模拟斗地主中的"牌"
MESSAGE_CARD_MAP = {
    "user": ("👤", "用户", Suit.HEARTS, "7"),
    "assistant": ("🤖", "AI", Suit.SPADES, "8"),
    "thinking": ("💭", "思考", Suit.HEARTS, "9"),
    "tool": ("🔧", "工具", Suit.SPADES, "10"),
    "system": ("⚙️", "系统", Suit.DIAMONDS, "J"),
    "error": ("❌", "错误", Suit.HEARTS, "K"),
    "success": ("✅", "成功", Suit.HEARTS, "A"),
}


@dataclass
class Card:
    """一张扑克牌"""
    rank: str           # 点数: 3,4,5,6,7,8,9,10,J,Q,K,A,2,Joker
    suit: str           # 花色: ♠♥♣♦
    front: str          # 正面内容
    face_up: bool = True
    
    @property
    def is_red(self) -> bool:
        """是否为红色牌（红心/方块）"""
        return self.suit in (Suit.HEARTS, Suit.DIAMONDS)
    
    @property
    def color(self) -> str:
        """牌面颜色"""
        return Suit.RED if self.is_red else "#E6EDF3"
    
    def render(self, width: int = 8, height: int = 6) -> Text:
        """渲染单张牌"""
        text = Text()
        
        # 牌背样式（未翻开）
        if not self.face_up:
            return self._render_back(width, height)
        
        # 牌面
        return self._render_front(width, height)
    
    def _render_front(self, width: int, height: int) -> Text:
        """渲染牌正面"""
        text = Text()
        
        # 顶角
        top_left = f"{self.rank}{self.suit}"
        top_right = f"{self.suit}{self.rank}"
        
        # 中间图案
        center = self.suit * ((height - 2) // 2)
        
        # 底角
        bottom_left = f"{self.suit}{self.rank}"
        bottom_right = f"{self.rank}{self.suit}"
        
        color = self.color
        
        # 第一行：左上角
        text.append(f"{top_left:<{width-1}}", style=color)
        text.append("\n")
        
        # 中间行
        for i in range(height - 3):
            if i == (height - 3) // 2:
                # 中间显示内容（截断）
                content = self.front[:width-2] if len(self.front) > width-2 else self.front
                text.append(f" {content:^{width-2}} ", style=f"{color} bold")
            else:
                text.append(f" {self.suit:^{width-2}} ", style=color)
            text.append("\n")
        
        # 最后一行：右下角
        text.append(f"{'':>{width-1}}{bottom_right}", style=color)
        
        return text
    
    def _render_back(self, width: int, height: int) -> Text:
        """渲染牌背"""
        text = Text()
        pattern = "░"  # 牌背花纹
        
        for i in range(height):
            text.append(f" {pattern * (width-2)} ", style="#484F58")
            if i < height - 1:
                text.append("\n")
        
        return text


class CardStack:
    """牌堆 - 一叠牌"""
    
    def __init__(self, name: str = "牌堆", icon: str = "🃏"):
        self.name = name
        self.icon = icon
        self.cards: list[Card] = []
        self.max_visible = 10  # 最多显示多少张
    
    def add(self, card: Card):
        """添加一张牌"""
        self.cards.append(card)
    
    def pop(self) -> Optional[Card]:
        """出一张牌"""
        if self.cards:
            return self.cards.pop(0)
        return None
    
    def peek(self) -> Optional[Card]:
        """看顶牌"""
        if self.cards:
            return self.cards[0]
        return None
    
    @property
    def count(self) -> int:
        """牌数"""
        return len(self.cards)
    
    def is_empty(self) -> bool:
        return len(self.cards) == 0
    
    def render_count(self) -> str:
        """渲染牌数"""
        count = len(self.cards)
        if count == 0:
            return "[#6E7681]空[#6E7681]"
        return f"[#E6EDF3]{count}张[#6E7681]"


# 预置的特殊牌堆
class PresetStacks:
    """预设牌堆工厂"""
    
    @staticmethod
    def tool_stack() -> CardStack:
        """工具牌堆"""
        stack = CardStack("工具", "🔧")
        
        # 按斗地主大小顺序排列工具牌
        tools = [
            ("3", Suit.CLUBS, "read_file", "📄", "读"),
            ("4", Suit.CLUBS, "find_files", "🔍", "找"),
            ("5", Suit.CLUBS, "search_files", "🔎", "搜"),
            ("6", Suit.CLUBS, "list_directory", "📁", "列"),
            ("7", Suit.CLUBS, "str_replace", "✏️", "改"),
            ("8", Suit.CLUBS, "write_file", "✨", "写"),
            ("9", Suit.CLUBS, "create_file", "➕", "建"),
            ("10", Suit.CLUBS, "delete_file", "🗑️", "删"),
            ("J", Suit.SPADES, "bash", "💻", "终"),
            ("Q", Suit.SPADES, "web_fetch", "🌐", "网"),
            ("K", Suit.SPADES, "web_search", "🔎", "搜"),
            ("A", Suit.SPADES, "read_image", "📷", "图"),
            ("2", Suit.DIAMONDS, "find_symbol", "📋", "符"),
        ]
        
        for rank, suit, tool_id, icon, label in tools:
            card = Card(
                rank=rank,
                suit=suit,
                front=f"{icon}{label}",
                face_up=True
            )
            stack.add(card)
        
        return stack
