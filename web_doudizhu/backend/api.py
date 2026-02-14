"""
FastAPI Web API 后端
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
import json
import uuid
import asyncio
import os
from datetime import datetime

from .game import GameState, GameManager, PlayerRole
from .ai import AIPlayerFactory
from .scoring import ScoringSystem


app = FastAPI(title="斗地主游戏API", version="1.0.0")

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
import os

# 挂载前端文件目录
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_dir):
    app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")

# 挂载静态资源目录
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 初始化管理器
game_manager = GameManager()
scoring_system = ScoringSystem()
active_connections: Dict[str, WebSocket] = {}


class CreateRoomRequest(BaseModel):
    """创建房间请求"""
    room_name: str
    player_name: str


class JoinRoomRequest(BaseModel):
    """加入房间请求"""
    room_id: str
    player_name: str


class BidRequest(BaseModel):
    """叫地主请求"""
    multiplier: int


class PlayCardsRequest(BaseModel):
    """出牌请求"""
    card_indices: List[int]


class AddAIRequest(BaseModel):
    """添加AI玩家请求"""
    ai_type: str = "simple"
    ai_name: str = None


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "斗地主游戏API",
        "version": "1.0.0",
        "endpoints": {
            "GET /": "API信息",
            "GET /health": "健康检查",
            "GET /frontend": "游戏前端界面",
            "GET /rooms": "获取房间列表",
            "POST /rooms": "创建房间",
            "POST /rooms/{room_id}/join": "加入房间",
            "POST /rooms/{room_id}/ai": "添加AI玩家",
            "GET /rooms/{room_id}": "获取房间信息",
            "POST /rooms/{room_id}/bid": "叫地主",
            "POST /rooms/{room_id}/play": "出牌",
            "POST /rooms/{room_id}/pass": "过牌",
            "GET /leaderboard": "获取排行榜",
            "GET /players/{player_id}/stats": "获取玩家统计"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "dou_dizhu_game"
    }


@app.get("/frontend")
async def serve_frontend():
    """提供前端界面"""
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(frontend_path):
        return FileResponse(frontend_path)
    else:
        raise HTTPException(status_code=404, detail="前端文件未找到")


@app.get("/api/rooms")
async def list_rooms():
    """获取房间列表"""
    rooms = game_manager.list_games()
    return {"rooms": rooms, "count": len(rooms)}


@app.post("/api/rooms")
async def create_room(request: CreateRoomRequest):
    """创建房间"""
    room_id = str(uuid.uuid4())[:8]
    player_id = str(uuid.uuid4())[:8]
    
    try:
        game = game_manager.create_game(room_id)
        game.add_player(player_id, request.player_name)
        
        # 自动添加两个AI玩家
        ai_names = ["电脑玩家1", "电脑玩家2"]
        for i, ai_name in enumerate(ai_names):
            if len(game.players) < 3:
                ai_id = f"ai_{str(uuid.uuid4())[:8]}"
                game.add_player(ai_id, ai_name)
                
                # 广播AI加入
                await _broadcast_message(room_id, {
                    "type": "player_joined",
                    "player_id": ai_id,
                    "player_name": ai_name
                })
        
        # 游戏应该已经自动开始了
        if game.phase == GamePhase.BIDDING:
            await _broadcast_game_state(room_id, game)
            
            # 如果第一个玩家是AI，开始处理AI
            if game.current_player.startswith("ai_"):
                await _handle_ai_turn(game, room_id)
        
        return {
            "room_id": room_id,
            "player_id": player_id,
            "message": "房间创建成功",
            "game_started": True
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/rooms/{room_id}/join")
async def join_room(room_id: str, request: JoinRoomRequest):
    """加入房间"""
    game = game_manager.get_game(room_id)
    if not game:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if len(game.players) >= 3:
        raise HTTPException(status_code=400, detail="房间已满")
    
    player_id = str(uuid.uuid4())[:8]
    game.add_player(player_id, request.player_name)
    
    return {
        "player_id": player_id,
        "message": "加入房间成功",
        "player_count": len(game.players)
    }


@app.post("/api/rooms/{room_id}/ai")
async def add_ai_player(room_id: str, request: AddAIRequest):
    """添加AI玩家"""
    game = game_manager.get_game(room_id)
    if not game:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if len(game.players) >= 3:
        raise HTTPException(status_code=400, detail="房间已满")
    
    ai_id = f"ai_{str(uuid.uuid4())[:8]}"
    ai_name = request.ai_name or f"{request.ai_type} AI"
    
    # 创建AI玩家
    ai_player = AIPlayerFactory.create_ai(request.ai_type, ai_id, ai_name)
    
    # 添加AI玩家到游戏
    game.add_player(ai_id, ai_name)
    
    # 如果是第三个玩家，自动开始游戏
    if len(game.players) == 3:
        game.start_game()
    
    return {
        "ai_id": ai_id,
        "ai_name": ai_name,
        "ai_type": request.ai_type,
        "message": "AI玩家添加成功"
    }


@app.get("/api/rooms/{room_id}")
async def get_room_info(room_id: str):
    """获取房间信息"""
    game = game_manager.get_game(room_id)
    if not game:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    return game.to_dict()


@app.post("/api/rooms/{room_id}/bid")
async def bid(room_id: str, player_id: str, request: BidRequest):
    """叫地主"""
    game = game_manager.get_game(room_id)
    if not game:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if player_id not in game.players:
        raise HTTPException(status_code=404, detail="玩家不在房间中")
    
    success = game.bid(player_id, request.multiplier)
    
    if not success:
        raise HTTPException(status_code=400, detail="叫地主失败")
    
    # 通知所有连接的客户端
    await _broadcast_game_state(room_id, game)
    
    return {"success": True, "message": "叫地主成功"}


@app.post("/api/rooms/{room_id}/play")
async def play_cards(room_id: str, player_id: str, request: PlayCardsRequest):
    """出牌"""
    game = game_manager.get_game(room_id)
    if not game:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if player_id not in game.players:
        raise HTTPException(status_code=404, detail="玩家不在房间中")
    
    success = game.play_cards(player_id, request.card_indices)
    
    if not success:
        raise HTTPException(status_code=400, detail="出牌失败")
    
    # 如果是AI玩家，自动进行下一步
    if player_id.startswith("ai_"):
        await _handle_ai_turn(game, room_id)
    
    # 通知所有连接的客户端
    await _broadcast_game_state(room_id, game)
    
    return {"success": True, "message": "出牌成功"}


@app.post("/api/rooms/{room_id}/pass")
async def pass_turn(room_id: str, player_id: str):
    """过牌"""
    game = game_manager.get_game(room_id)
    if not game:
        raise HTTPException(status_code=404, detail="房间不存在")
    
    if player_id not in game.players:
        raise HTTPException(status_code=404, detail="玩家不在房间中")
    
    success = game.pass_turn(player_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="过牌失败")
    
    # 如果是AI玩家，自动进行下一步
    if player_id.startswith("ai_"):
        await _handle_ai_turn(game, room_id)
    
    # 通知所有连接的客户端
    await _broadcast_game_state(room_id, game)
    
    return {"success": True, "message": "过牌成功"}


@app.get("/api/leaderboard")
async def get_leaderboard(limit: int = 10):
    """获取排行榜"""
    leaderboard = scoring_system.get_leaderboard(limit)
    return {"leaderboard": leaderboard}


@app.get("/api/players/{player_id}/stats")
async def get_player_stats(player_id: str):
    """获取玩家统计信息"""
    stats = scoring_system.get_player_stats(player_id)
    if not stats:
        raise HTTPException(status_code=404, detail="玩家不存在")
    
    return stats


@app.get("/api/games/history")
async def get_game_history(player_id: Optional[str] = None, limit: int = 20):
    """获取游戏历史"""
    history = scoring_system.get_game_history(player_id, limit)
    return {"history": history}


@app.websocket("/ws/{room_id}/{player_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, player_id: str):
    """WebSocket连接"""
    await websocket.accept()
    
    # 存储连接
    connection_key = f"{room_id}_{player_id}"
    active_connections[connection_key] = websocket
    
    try:
        # 发送初始游戏状态
        game = game_manager.get_game(room_id)
        if game:
            await websocket.send_json({
                "type": "game_state",
                "data": game.to_dict()
            })
        
        # 保持连接
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理消息
            await _handle_websocket_message(room_id, player_id, message)
            
    except WebSocketDisconnect:
        # 移除连接
        if connection_key in active_connections:
            del active_connections[connection_key]
        
        # 通知其他玩家
        await _broadcast_message(room_id, {
            "type": "player_left",
            "player_id": player_id
        })


async def _handle_websocket_message(room_id: str, player_id: str, message: Dict):
    """处理WebSocket消息"""
    msg_type = message.get("type")
    game = game_manager.get_game(room_id)
    
    if not game:
        return
    
    if msg_type == "bid":
        multiplier = message.get("multiplier", 1)
        game.bid(player_id, multiplier)
        await _broadcast_game_state(room_id, game)
        
        # 如果下一个是AI，处理AI
        if game.current_player.startswith("ai_") and game.phase.value == "叫地主":
            await _handle_ai_turn(game, room_id)
    
    elif msg_type == "play":
        # 支持两种格式：card_indices（旧的索引方式）或 cards（新的牌字符串方式）
        card_data = message.get("cards")
        
        if card_data:
            # 使用牌字符串方式
            # 将字符串转换为Card对象
            from .card import Card, CardRank, CardSuit
            
            card_objects = []
            for card_str in card_data:
                try:
                    # 解析牌字符串，如 "♠3", "♥A", "小王", "大王"
                    if card_str in ["小王", "SJ"]:
                        card_objects.append(Card(CardRank.SMALL_JOKER))
                    elif card_str in ["大王", "BJ"]:
                        card_objects.append(Card(CardRank.BIG_JOKER))
                    else:
                        # 普通牌：格式如 "♠3", "♥A"
                        suit_char = card_str[0]
                        rank_str = card_str[1:]
                        
                        suit_map = {
                            "♠": CardSuit.SPADE,
                            "♥": CardSuit.HEART,
                            "♦": CardSuit.DIAMOND,
                            "♣": CardSuit.CLUB
                        }
                        
                        rank_map = {
                            "3": CardRank.THREE, "4": CardRank.FOUR, "5": CardRank.FIVE,
                            "6": CardRank.SIX, "7": CardRank.SEVEN, "8": CardRank.EIGHT,
                            "9": CardRank.NINE, "10": CardRank.TEN, "J": CardRank.JACK,
                            "Q": CardRank.QUEEN, "K": CardRank.KING, "A": CardRank.ACE,
                            "2": CardRank.TWO
                        }
                        
                        suit = suit_map.get(suit_char)
                        rank = rank_map.get(rank_str)
                        
                        if suit and rank:
                            card_objects.append(Card(rank, suit))
                except Exception as e:
                    print(f"解析牌失败: {card_str}, {e}")
            
            # 找到这些牌在玩家手中的索引
            if card_objects and player_id in game.players:
                player_cards = game.players[player_id].cards
                indices = []
                
                for card_obj in card_objects:
                    for i, pc in enumerate(player_cards):
                        if pc.rank == card_obj.rank and pc.suit == card_obj.suit:
                            if i not in indices:
                                indices.append(i)
                                break
                
                success = game.play_cards(player_id, indices)
        else:
            # 使用旧的索引方式
            card_indices = message.get("card_indices", [])
            success = game.play_cards(player_id, card_indices)
        
        if success:
            await _broadcast_game_state(room_id, game)
            
            # 如果下一个是AI，处理AI
            if game.current_player.startswith("ai_") and game.phase.value == "出牌" and game.winner is None:
                await _handle_ai_turn(game, room_id)
    
    elif msg_type == "pass":
        success = game.pass_turn(player_id)
        
        if success:
            await _broadcast_game_state(room_id, game)
            
            # 如果下一个是AI，处理AI
            if game.current_player.startswith("ai_") and game.phase.value == "出牌" and game.winner is None:
                await _handle_ai_turn(game, room_id)


async def _broadcast_game_state(room_id: str, game: GameState):
    """广播游戏状态"""
    message = {
        "type": "game_state",
        "data": game.to_dict()
    }
    
    await _broadcast_message(room_id, message)
    
    # 如果游戏结束，保存记录
    if game.phase.value == "结束":
        scoring_system.save_game(game)


async def _broadcast_message(room_id: str, message: Dict):
    """广播消息给房间内的所有连接"""
    for connection_key in list(active_connections.keys()):
        if connection_key.startswith(f"{room_id}_"):
            websocket = active_connections[connection_key]
            try:
                await websocket.send_json(message)
            except:
                # 连接已断开，移除
                del active_connections[connection_key]


async def _handle_ai_turn(game: GameState, room_id: str):
    """处理AI玩家的回合"""
    # 等待一小段时间让前端更新
    await asyncio.sleep(0.5)
    
    if game.phase.value == "叫地主" and game.current_player.startswith("ai_"):
        # AI叫地主/抢地主
        ai_player = AIPlayerFactory.create_ai("simple", game.current_player)
        multiplier = ai_player.decide_bid(game, game.current_player)
        
        await asyncio.sleep(1)  # 模拟思考时间
        
        game.bid(game.current_player, multiplier)
        await _broadcast_game_state(room_id, game)
        
        # 如果游戏进入出牌阶段，继续处理AI出牌
        if game.phase.value == "出牌" and game.current_player.startswith("ai_"):
            await _handle_ai_turn(game, room_id)
    
    elif game.phase.value == "出牌" and game.current_player.startswith("ai_"):
        # AI出牌
        ai_player = AIPlayerFactory.create_ai("simple", game.current_player)
        
        await asyncio.sleep(1)  # 模拟思考时间
        
        # 决定出牌还是过牌
        if ai_player.decide_pass(game, game.current_player):
            game.pass_turn(game.current_player)
        else:
            card_indices = ai_player.decide_play(game, game.current_player)
            if card_indices:
                game.play_cards(game.current_player, card_indices)
            else:
                game.pass_turn(game.current_player)
        
        await _broadcast_game_state(room_id, game)
        
        # 如果游戏还没结束，继续处理下一个AI
        if (game.phase.value == "出牌" and 
            game.current_player.startswith("ai_") and
            game.winner is None):
            await _handle_ai_turn(game, room_id)


# 静态文件服务（如果存在）
import os
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)