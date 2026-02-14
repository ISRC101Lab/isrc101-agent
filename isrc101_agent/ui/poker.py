"""斗地主风格UI - 牌桌布局渲染器"""

import shutil
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.style import Style
from rich.color import Color
from rich.layout import Layout
from rich.live import Live

from .cards import Card, CardStack, Suit, Rank, TOOL_CARD_MAP, MESSAGE_CARD_MAP
from ..rendering import get_icon
from ..theme import ACCENT, BORDER, DIM, TEXT, MUTED, SUCCESS, ERROR, WARN, INFO


class PokerTable:
    """斗地主牌桌 - 主布局容器"""
    
    def __init__(self, console: Optional[Console] = None):
        self.console = console or Console()
        self.width = shutil.get_terminal_size().columns
        
        # 牌堆
        self.ai_messages = CardStack("AI消息", "🤖")
        self.user_messages = CardStack("用户消息", "👤")
        self.tool_calls = CardStack("工具", "🔧")
        self.current_play = CardStack("当前", "💬")
        
        # 当前消息缓存
        self.current_user_msg = ""
        self.current_ai_msg = ""
        self.current_tool_name = ""
        self.current_tool_result = ""
    
    def set_current_message(self, user: str = "", ai: str = "", tool: str = "", result: str = ""):
        """设置当前消息内容"""
        if user:
            self.current_user_msg = user
        if ai:
            self.current_ai_msg = ai
        if tool:
            self.current_tool_name = tool
        if result:
            self.current_tool_result = result
    
    def add_ai_message(self, content: str):
        """添加AI消息到牌堆"""
        card = Card(
            rank="8",
            suit=Suit.SPADES,
            front=self._truncate(content, 20),
            face_up=True
        )
        self.ai_messages.add(card)
    
    def add_user_message(self, content: str):
        """添加用户消息到牌堆"""
        card = Card(
            rank="7",
            suit=Suit.HEARTS,
            front=self._truncate(content, 20),
            face_up=True
        )
        self.user_messages.add(card)
    
    def add_tool_call(self, tool_name: str, args: str = ""):
        """添加工具调用到牌堆"""
        tool_info = TOOL_CARD_MAP.get(tool_name, ("🔧", "工具", Suit.CLUBS, "9"))
        icon, label, suit, rank = tool_info
        
        content = f"{icon}{label}"
        if args:
            content += f":{self._truncate(args, 10)}"
        
        card = Card(
            rank=rank,
            suit=suit,
            front=content,
            face_up=True
        )
        self.tool_calls.add(card)
    
    @staticmethod
    def _truncate(s: str, max_len: int) -> str:
        if len(s) <= max_len:
            return s
        return s[:max_len-1] + "…"
    
    def render_card_mini(self, rank: str, suit: str, label: str, count: int = 0) -> Text:
        """渲染迷你卡片 - 用于显示牌数"""
        text = Text()
        
        is_red = suit in (Suit.HEARTS, Suit.DIAMONDS)
        color = Suit.RED if is_red else "#E6EDF3"
        
        # 紧凑格式: [♠3×8]
        if count > 0:
            text.append(f"[{suit}{rank}×{count}]", style=color)
        else:
            text.append(f"[{suit}{rank}]", style=color)
        
        return text
    
    def render_tool_card(self, tool_id: str, selected: bool = False) -> Panel:
        """渲染单张工具牌"""
        tool_info = TOOL_CARD_MAP.get(tool_id, ("🔧", "未知", Suit.CLUBS, "?"))
        icon, label, suit, rank = tool_info
        
        is_red = suit in (Suit.HEARTS, Suit.DIAMONDS)
        color = Suit.RED if is_red else "#E6EDF3"
        
        # 边框样式
        border = ACCENT if selected else BORDER
        
        content = Text()
        content.append(f"{suit}{rank}\n", style=f"bold {color}")
        content.append(f"  {icon}\n", style=color)
        content.append(f" {label}", style="#8B949E")
        
        return Panel(
            content,
            border_style=border,
            padding=(0, 1),
            width=10,
            height=5,
        )
    
    def render_hand_cards(self, tools: list[str], selected: Optional[str] = None) -> Table:
        """渲染手牌区 - 工具选择"""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column()
        
        for i, tool_id in enumerate(tools):
            tool_info = TOOL_CARD_MAP.get(tool_id, ("🔧", "未知", Suit.CLUBS, "?"))
            icon, label, suit, rank = tool_info
            
            is_red = suit in (Suit.HEARTS, Suit.DIAMONDS)
            color = Suit.RED if is_red else "#E6EDF3"
            
            # 当前选中
            is_sel = tool_id == selected
            pointer = "▶" if is_sel else " "
            
            row = Text()
            row.append(f"{pointer} ", style=ACCENT if is_sel else DIM)
            row.append(f"{suit}{rank} ", style=f"bold {color}")
            row.append(f"{icon} {label}", style="#8B949E" if not is_sel else TEXT)
            
            table.add_row(row)
        
        return table
    
    def render_table(self) -> None:
        """渲染整个牌桌"""
        console = self.console
        
        console.print()
        
        # === 顶部：消息牌堆（AI + 用户）===
        self._render_top_area(console)
        
        console.print()
        
        # === 中间：当前出牌区 ===
        self._render_play_area(console)
        
        console.print()
        
        # === 底部：手牌区（工具） ===
        self._render_hand_area(console)
        
        console.print()
    
    def _render_top_area(self, console: Console):
        """渲染顶部区域 - 牌堆"""
        table = Table(box=None, padding=(0, 4))
        table.add_column("ai", style="center", width=self.width // 2 - 2)
        table.add_column("user", style="center", width=self.width // 2 - 2)
        
        # AI消息堆
        ai_text = Text()
        ai_text.append(f"🤖 AI ", style=f"bold {ACCENT}")
        ai_text.append(f"[{self.ai_messages.count}张]", style=DIM)
        ai_text.append("\n")
        
        # 显示最近的AI消息（最多3张）
        for i, card in enumerate(self.ai_messages.cards[-3:]):
            color = card.color
            ai_text.append(f"  {card.suit}{card.rank} ", style=color)
            ai_text.append(f"{card.front}\n", style="#8B949E")
        
        # 用户消息堆
        user_text = Text()
        user_text.append(f"👤 用户 ", style=f"bold {ACCENT}")
        user_text.append(f"[{self.user_messages.count}张]", style=DIM)
        user_text.append("\n")
        
        for i, card in enumerate(self.user_messages.cards[-3:]):
            color = card.color
            user_text.append(f"  {card.suit}{card.rank} ", style=color)
            user_text.append(f"{card.front}\n", style="#8B949E")
        
        table.add_row(ai_text, user_text)
        console.print(table)
    
    def _render_play_area(self, console: Console):
        """渲染出牌区 - 当前对话"""
        # 标题
        title = Text()
        title.append("💬 ", style=ACCENT)
        title.append("当前对话", style=f"bold {TEXT}")
        
        content = Text()
        
        # 用户消息
        if self.current_user_msg:
            content.append("👤 ", style=SUCCESS)
            content.append("你: ", style="bold #E6EDF3")
            content.append(self._wrap_text(self.current_user_msg, 50), style="#8B949E")
            content.append("\n\n")
        
        # AI消息
        if self.current_ai_msg:
            content.append("🤖 ", style=ACCENT)
            content.append("AI: ", style="bold #E6EDF3")
            content.append(self._wrap_text(self.current_ai_msg, 50), style="#8B949E")
            content.append("\n\n")
        
        # 工具调用
        if self.current_tool_name:
            tool_info = TOOL_CARD_MAP.get(self.current_tool_name, ("🔧", self.current_tool_name, Suit.CLUBS, "?"))
            icon, label, suit, rank = tool_info
            
            content.append(f"{icon} ", style=WARN)
            content.append(f"工具: ", style="bold #E6EDF3")
            content.append(f"{suit}{rank} {label}", style="#8B949E")
            
            if self.current_tool_result:
                content.append("\n")
                content.append(f"  └─ ", style=DIM)
                content.append(self._wrap_text(self.current_tool_result, 45), style="#6E7681")
            
            content.append("\n")
        
        if not (self.current_user_msg or self.current_ai_msg or self.current_tool_name):
            content.append("[#6E7681]等待出牌...[#6E7681]", style=DIM)
        
        console.print(Panel(
            content,
            title=title,
            border_style=BORDER,
            padding=(1, 2),
        ))
    
    def _render_hand_area(self, console: Console):
        """渲染手牌区 - 工具选择"""
        # 标题
        title = Text()
        title.append("🔧 ", style=ACCENT)
        title.append("工具手牌", style=f"bold {TEXT}")
        
        # 工具列表
        tools = list(TOOL_CARD_MAP.keys())
        
        content = Text()
        
        # 显示所有工具牌
        for i, tool_id in enumerate(tools):
            tool_info = TOOL_CARD_MAP.get(tool_id)
            if not tool_info:
                continue
                
            icon, label, suit, rank = tool_info
            is_red = suit in (Suit.HEARTS, Suit.DIAMONDS)
            color = Suit.RED if is_red else "#E6EDF3"
            
            # 检查是否已使用
            used = any(
                TOOL_CARD_MAP.get(t, ("", "", "", ""))[2] == suit and 
                TOOL_CARD_MAP.get(t, ("", "", "", ""))[3] == rank
                for t in self.tool_calls.cards
            )
            
            if i > 0 and i % 5 == 0:
                content.append("\n")
            
            if used:
                content.append(f"[{suit}{rank}]{icon}{label}", style=f"{color} dim")
            else:
                content.append(f"[{suit}{rank}]{icon}{label}", style=color)
            
            content.append("  ", style=DIM)
        
        console.print(Panel(
            content,
            title=title,
            border_style=BORDER,
            padding=(1, 2),
        ))
    
    @staticmethod
    def _wrap_text(text: str, width: int) -> str:
        """简单的文本换行"""
        if len(text) <= width:
            return text
        return text[:width-1] + "…"
    
    def render_tool_call_simple(self, tool_name: str, args: dict) -> None:
        """简单渲染工具调用 - 扑克牌风格"""
        console = self.console
        
        tool_info = TOOL_CARD_MAP.get(tool_name, ("🔧", tool_name, Suit.CLUBS, "?"))
        icon, label, suit, rank = tool_info
        
        is_red = suit in (Suit.HEARTS, Suit.DIAMONDS)
        color = Suit.RED if is_red else "#E6EDF3"
        
        # 牌面
        content = Text()
        content.append(f"┌─────────┐\n", style=color)
        content.append(f"│{rank}       │\n", style=color)
        content.append(f"│    {icon}    │\n", style=color)
        content.append(f"│       {rank}│\n", style=color)
        content.append(f"└─────────┘", style=color)
        
        # 详细信息
        detail = f" {label}: "
        if tool_name == "read_file":
            detail += args.get("path", "")
        elif tool_name == "bash":
            cmd = args.get("command", "")[:30]
            detail += cmd
        elif tool_name == "search_files":
            detail += f"{args.get('pattern', '')} in {args.get('path', '.')}"
        else:
            detail += str(args)[:30]
        
        console.print(f"  {content} {detail}", end="")
    
    def render_result_simple(self, result: str, elapsed: float = 0) -> None:
        """简单渲染结果"""
        time_str = f" [{DIM}]({elapsed:.1f}s)[/{DIM}]" if elapsed >= 0.1 else ""
        
        # 判断结果类型
        is_error = result.startswith(("⚠", "⛔", "⏱", "Error:", "❌"))
        is_success = result.startswith(("✓", "✅", "Created", "Edited", "Deleted"))
        
        if is_error:
            style = ERROR
            icon = "❌"
        elif is_success:
            style = SUCCESS
            icon = "✅"
        else:
            style = "#8B949E"
            icon = "✓"
        
        # 截断结果
        lines = result.split("\n")
        first_line = lines[0][:60]
        if len(lines) > 1:
            first_line += f" ... ({len(lines)-1}行)"
        
        console.print(f"{icon} {first_line}[style]{time_str}")


# 便捷函数
def create_poker_table() -> PokerTable:
    """创建牌桌实例"""
    return PokerTable()


def render_card(rank: str, suit: str, label: str, width: int = 10) -> Panel:
    """渲染单张扑克牌"""
    is_red = suit in (Suit.HEARTS, Suit.DIAMONDS)
    color = Suit.RED if is_red else "#E6EDF3"
    
    content = Text()
    content.append(f"{rank}{suit}\n", style=f"bold {color}")
    content.append(f"  {label}", style="#8B949E")
    
    return Panel(
        content,
        border_style=ACCENT,
        padding=(0, 1),
        width=width,
    )



def render_poker_startup(console: Console, config) -> PokerTable:
    """斗地主风格启动界面
    
    返回 PokerTable 实例供后续使用
    """
    from rich.table import Table
    from ..config import Config
    
    preset = config.get_active_preset()
    key = preset.resolve_api_key()
    
    # 创建牌桌
    table = PokerTable(console)
    
    console.print()
    
    # === 标题区 ===
    title = Text()
    title.append("┌", style=ACCENT)
    title.append("─" * 50, style=BORDER)
    title.append("┐", style=ACCENT)
    console.print(title)
    
    # 标题
    header = Text()
    header.append("│", style=ACCENT)
    header.append(" 🃏  isrc101-agent  🃏 ", style=f"bold {ACCENT}")
    header.append(" " * 22)
    header.append(" AI Coding Assistant ", style=DIM)
    header.append("│", style=ACCENT)
    console.print(header)
    
    # 分隔线
    sep = Text()
    sep.append("├", style=ACCENT)
    sep.append("─" * 50, style=BORDER)
    sep.append("┤", style=ACCENT)
    console.print(sep)
    
    # === 状态区 ===
    key_status = "✅" if key else "❌"
    web_text = "🌐 ON" if config.web_enabled else "📴 off"
    skills_list = config.enabled_skills
    skills_text = ", ".join(skills_list) if skills_list else "无"
    mode_colors = {"agent": "🟢", "ask": "🟡"}
    mode_icon = mode_colors.get(config.chat_mode, "⚪")
    
    # 状态行
    def status_row(label: str, value: str, icon: str = "▸"):
        row = Text()
        row.append("│", style=ACCENT)
        row.append(f" {icon} ", style=DIM)
        row.append(f"{label}:", style="#6E7681")
        row.append(f" {value}", style=TEXT)
        row.append(" " * (40 - len(label) - len(value)))
        row.append("│", style=ACCENT)
        return row
    
    console.print(status_row("model", f"{config.active_model} → {preset.model}"))
    console.print(status_row("mode", f"{mode_icon} {config.chat_mode}"))
    console.print(status_row("web", web_text))
    console.print(status_row("key", f"{key_status} {'已配置' if key else '未配置'}"))
    console.print(status_row("context", f"{preset.context_window:,} tokens"))
    console.print(status_row("skills", skills_text))
    console.print(status_row("project", config.project_root[:30] + "..." if len(config.project_root) > 30 else config.project_root))
    
    # 底部
    footer = Text()
    footer.append("└", style=ACCENT)
    footer.append("─" * 50, style=BORDER)
    footer.append("┘", style=ACCENT)
    console.print(footer)
    
    console.print()
    
    # === 工具手牌展示 ===
    _render_tool_hand(console)
    
    # === 提示 ===
    tips = Text()
    tips.append("  💡 ", style=ACCENT)
    tips.append("输入消息开始对话  ·  ", style=DIM)
    tips.append("/", style=ACCENT)
    tips.append("命令  ·  ", style=DIM)
    tips.append("/help", style=ACCENT)
    tips.append("帮助  ·  ", style=DIM)
    tips.append("Esc+Enter", style=ACCENT)
    tips.append("多行", style=DIM)
    console.print(tips)
    console.print()
    
    return table


def _render_tool_hand(console: Console):
    """渲染工具手牌"""
    from rich.text import Text
    from rich.table import Table
    
    # 标题
    title = Text()
    title.append("🃏 ", style=ACCENT)
    title.append("工具手牌 (选择工具出牌)", style=f"bold {TEXT}")
    console.print(title)
    console.print()
    
    # 直接打印工具牌
    tools = list(TOOL_CARD_MAP.items())
    
    # 每行显示5张牌
    for i in range(0, len(tools), 5):
        row_tools = tools[i:i+5]
        line = "  "
        for tool_id, (icon, label, suit, rank) in row_tools:
            is_red = suit in (Suit.HEARTS, Suit.DIAMONDS)
            color = Suit.RED if is_red else "#E6EDF3"
            line += f"[{color}]{suit}{rank}[/{color}] {icon} {label:<6}  "
        console.print(line)
    console.print()
