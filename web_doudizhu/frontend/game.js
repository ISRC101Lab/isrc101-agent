/**
 * 斗地主游戏 - 连接后端的完整前端逻辑
 */

const API_BASE = window.location.origin;

class DouDizhuGame {
    constructor() {
        this.ws = null;
        this.roomId = null;
        this.playerId = null;
        this.playerName = null;
        this.gameState = null;
        this.previousGameState = null;
        this.selectedCards = new Set();
        this.myHand = [];
        this.players = {};
        this.currentPlayerId = null;
        this.landlordId = null;
        this.multiplier = 1;
        this.isConnected = false;
        
        // AI反馈状态
        this.thinkingPlayerId = null;
        this.thinkingTimeout = null;
        
        // 牌面渲染配置
        this.suitSymbols = {
            'S': '♠', 'H': '♥', 'D': '♦', 'C': '♣'
        };
        
        this.rankValues = {
            '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
            'J': 11, 'Q': 12, 'K': 13, 'A': 14, '2': 15,
            'JOKER': 16, 'BIG_JOKER': 17
        };
        
        this.initEventListeners();
    }
    
    initEventListeners() {
        // 开始游戏
        document.getElementById('connect-btn')?.addEventListener('click', () => this.connectToGame());
        
        // 叫地主
        document.getElementById('call-landlord-btn')?.addEventListener('click', () => this.bid(1));
        document.getElementById('bid-2x-btn')?.addEventListener('click', () => this.bid(2));
        document.getElementById('pass-bid-btn')?.addEventListener('click', () => this.bid(0));
        
        // 出牌
        document.getElementById('play-cards-btn')?.addEventListener('click', () => this.playCards());
        document.getElementById('pass-turn-btn')?.addEventListener('click', () => this.passTurn());
        
        // 提示和整理
        document.getElementById('hint-btn')?.addEventListener('click', () => this.getHint());
        document.getElementById('sort-hand-btn')?.addEventListener('click', () => this.sortHand());
        
        // 退出
        document.getElementById('quit-btn')?.addEventListener('click', () => this.quitGame());
        
        // 聊天
        document.getElementById('chat-send-btn')?.addEventListener('click', () => this.sendChat());
        document.getElementById('chat-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendChat();
        });
        
        // 再来一局
        document.getElementById('play-again-btn')?.addEventListener('click', () => this.playAgain());
        
        // 设置
        document.getElementById('close-settings')?.addEventListener('click', () => this.closeSettings());
    }
    
    // 连接到游戏
    async connectToGame() {
        const nameInput = document.getElementById('player-name');
        this.playerName = nameInput?.value?.trim() || '玩家';
        
        // 隐藏登录面板
        document.getElementById('login-panel')?.classList.add('hidden');
        
        try {
            this.addChatMessage('系统', '正在连接服务器...');
            
            // 创建房间
            const createResponse = await fetch(`${API_BASE}/rooms`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    room_name: '房间',
                    player_name: this.playerName
                })
            });
            
            if (!createResponse.ok) {
                throw new Error('创建房间失败');
            }
            
            const createData = await createResponse.json();
            this.roomId = createData.room_id;
            this.playerId = createData.player_id;
            
            this.addChatMessage('系统', `房间创建成功: ${this.roomId}`);
            
            // 添加两个AI玩家
            for (let i = 0; i < 2; i++) {
                const aiResponse = await fetch(`${API_BASE}/rooms/${this.roomId}/ai`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ai_type: i === 0 ? 'simple' : 'rule_based',
                        ai_name: i === 0 ? '电脑玩家1' : '电脑玩家2'
                    })
                });
                
                if (aiResponse.ok) {
                    this.addChatMessage('系统', 'AI玩家已加入');
                }
            }
            
            // 连接WebSocket
            await this.connectWebSocket();
            
            // 开始轮询游戏状态
            this.startPolling();
            
        } catch (error) {
            console.error('连接失败:', error);
            this.addChatMessage('系统', `连接失败: ${error.message}`);
        }
    }
    
    // 连接WebSocket
    async connectWebSocket() {
        return new Promise((resolve, reject) => {
            const wsUrl = `ws://${window.location.host}/ws/${this.roomId}/${this.playerId}`;
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                this.isConnected = true;
                this.addChatMessage('系统', 'WebSocket连接成功');
                resolve();
            };
            
            this.ws.onmessage = (event) => {
                const message = JSON.parse(event.data);
                this.handleWebSocketMessage(message);
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket错误:', error);
                this.addChatMessage('系统', 'WebSocket连接错误');
            };
            
            this.ws.onclose = () => {
                this.isConnected = false;
                this.addChatMessage('系统', 'WebSocket连接已关闭');
            };
            
            // 超时处理
            setTimeout(() => {
                if (!this.isConnected) {
                    reject(new Error('WebSocket连接超时'));
                }
            }, 5000);
        });
    }
    
    // 开始轮询游戏状态
    startPolling() {
        this.pollInterval = setInterval(() => {
            this.fetchGameState();
        }, 1000);
    }
    
    // 获取游戏状态
    async fetchGameState() {
        try {
            const response = await fetch(`${API_BASE}/rooms/${this.roomId}`);
            if (!response.ok) return;
            
            const data = await response.json();
            this.updateGameState(data);
        } catch (error) {
            console.error('获取游戏状态失败:', error);
        }
    }
    
    // 处理WebSocket消息
    handleWebSocketMessage(message) {
        const { type, data } = message;
        
        if (type === 'game_state') {
            this.updateGameState(data);
        } else if (type === 'player_left') {
            this.addChatMessage('系统', '有玩家离开了游戏');
        }
    }
    
    // 更新游戏状态
    updateGameState(data) {
        const oldPhase = this.gameState?.phase;
        this.gameState = data;
        
        // 更新玩家信息
        this.players = {};
        let myIndex = 0;
        
        Object.entries(data.players || {}).forEach(([pid, player], index) => {
            this.players[pid] = { ...player, id: pid };
            if (pid === this.playerId) {
                myIndex = index;
                this.myHand = player.cards || [];
            }
        });
        
        // 重新映射玩家位置
        this.repositionPlayers(myIndex);
        
        // 更新游戏阶段
        this.landlordId = data.landlord;
        this.currentPlayerId = data.current_player;
        this.multiplier = data.base_multiplier || 1;
        
        // 根据阶段显示不同UI
        if (data.phase === '叫地主') {
            this.showBidButtons();
        } else if (data.phase === '出牌') {
            this.showPlayButtons();
            this.updatePlayerRoles();
        } else if (data.phase === '结束') {
            this.showGameResult(data);
        }
        
        // 检测状态变化并触发AI动画
        this.detectStateChange();
        
        // 更新所有UI
        this.updateAllUI();
    }
    
    // 重新定位玩家（让自己在底部）
    repositionPlayers(myIndex) {
        // 调整玩家顺序，使自己始终在位置0
        if (myIndex !== 0) {
            const myPlayer = this.players[this.playerId];
            const keys = Object.keys(this.players);
            const newPlayers = {};
            
            keys.forEach((key, idx) => {
                const newIdx = (idx - myIndex + 3) % 3;
                newPlayers[newIdx] = this.players[key];
            });
            
            this.players = newPlayers;
        }
    }
    
    // 叫地主/抢地主
    async bid(multiplier) {
        try {
            const response = await fetch(`${API_BASE}/rooms/${this.roomId}/bid/${this.playerId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ multiplier })
            });
            
            if (response.ok) {
                const msg = multiplier === 0 ? '不叫' : (multiplier === 1 ? '叫地主' : '抢地主');
                this.addChatMessage(this.playerName, msg);
                this.hideBidButtons();
                this.showWaiting('等待其他玩家...');
            }
        } catch (error) {
            console.error('叫地主失败:', error);
        }
    }
    
    // 出牌
    async playCards() {
        if (this.selectedCards.size === 0) {
            this.addChatMessage('系统', '请选择要出的牌');
            return;
        }
        
        try {
            const cardIndices = Array.from(this.selectedCards);
            
            const response = await fetch(`${API_BASE}/rooms/${this.roomId}/play/${this.playerId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ card_indices: cardIndices })
            });
            
            if (response.ok) {
                this.addChatMessage(this.playerName, '出牌');
                this.selectedCards.clear();
                this.hidePlayButtons();
                this.showWaiting('等待其他玩家...');
            }
        } catch (error) {
            console.error('出牌失败:', error);
        }
    }
    
    // 过牌
    async passTurn() {
        try {
            const response = await fetch(`${API_BASE}/rooms/${this.roomId}/pass/${this.playerId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (response.ok) {
                this.addChatMessage(this.playerName, '过');
                this.selectedCards.clear();
                this.hidePlayButtons();
                this.showWaiting('等待其他玩家...');
            }
        } catch (error) {
            console.error('过牌失败:', error);
        }
    }
    
    // 提示
    getHint() {
        // 简化实现：自动选中能压过上家的最小牌
        if (this.gameState?.last_pattern_details?.cards) {
            // TODO: 实现智能提示
            this.addChatMessage('系统', '提示功能开发中...');
        }
    }
    
    // 整理手牌
    sortHand() {
        this.myHand.sort((a, b) => this.getCardValue(a) - this.getCardValue(b));
        this.selectedCards.clear();
        this.updateMyCards();
        this.addChatMessage('系统', '手牌已整理');
    }
    
    // 获取牌的数值
    getCardValue(card) {
        const rank = card.rank || card;
        if (rank === 'JOKER') return 16;
        if (rank === 'BIG_JOKER') return 17;
        const values = {'3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14, '2': 15};
        return values[rank] || 0;
    }
    
    // 显示游戏结果
    showGameResult(data) {
        const winner = data.winner;
        const isWin = winner === this.playerId;
        
        let text = '';
        if (this.landlordId === winner) {
            text = isWin ? '地主获胜！' : '地主获胜';
        } else {
            text = isWin ? '农民获胜！' : '农民获胜';
        }
        
        text += ` ${this.multiplier}倍`;
        
        this.showResult(isWin, text);
        
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
    }
    
    // 显示结果
    showResult(win, text) {
        const modal = document.getElementById('game-result-modal');
        const title = document.getElementById('result-title');
        const details = document.getElementById('result-details');
        
        title.textContent = win ? '胜利！' : '失败';
        details.textContent = text;
        
        document.getElementById('result-content').className = 'result-content ' + (win ? 'win' : 'lose');
        modal.classList.add('show');
    }
    
    // 再来一局
    async playAgain() {
        document.getElementById('game-result-modal')?.classList.remove('show');
        
        // 重新开始
        await this.connectToGame();
    }
    
    // ===== UI更新方法 =====
    
    updateAllUI() {
        this.updatePlayerCards();
        this.updateTurnIndicator();
        this.updateMultiplier();
    }
    
    updatePlayerCards() {
        // 更新其他玩家手牌数量
        Object.entries(this.players).forEach(([pid, player], idx) => {
            if (pid === this.playerId) return;
            const pos = idx === 1 ? 'left' : 'right';
            const countEl = document.getElementById(`player-${pos}-cards`);
            if (countEl) {
                countEl.textContent = player.card_count || 0;
            }
            
            // 更新玩家名称
            const nameEl = document.getElementById(`player-${pos}-player-name`);
            if (nameEl) {
                nameEl.textContent = player.name;
            }
        });
        
        // 更新自己的手牌数量
        const myCountEl = document.getElementById('bottom-player-cards');
        if (myCountEl) {
            myCountEl.textContent = this.myHand.length;
        }
        
        // 更新房间信息
        const roomDisplay = document.getElementById('room-id-display');
        if (roomDisplay && this.roomId) {
            roomDisplay.innerHTML = `<i class="fas fa-door-closed"></i> 房间: ${this.roomId}`;
        }
        
        // 更新玩家在线数
        const playersOnline = document.getElementById('players-online');
        if (playersOnline) {
            const count = Object.keys(this.players).length;
            playersOnline.innerHTML = `<i class="fas fa-users"></i> ${count}/3`;
        }
        
        // 更新对手手牌显示
        this.updateOpponentCardsDisplay();
    }
    
    updateOpponentCardsDisplay() {
        ['left', 'right'].forEach((pos, idx) => {
            const playerIdx = idx + 1;
            const player = this.players[playerIdx];
            const container = document.getElementById(`${pos}-opponent-cards`);
            if (!container || !player) return;
            
            container.innerHTML = '';
            const count = Math.min(player.card_count || 0, 6);
            
            for (let i = 0; i < count; i++) {
                const cardBack = document.createElement('div');
                cardBack.className = 'opponent-card-back';
                container.appendChild(cardBack);
            }
        });
    }
    
    updateTurnIndicator() {
        // 找出自己在players中的位置
        let myPos = null;
        Object.entries(this.players).forEach(([pid, player], idx) => {
            if (pid === this.playerId) {
                myPos = idx;
            }
        });
        
        if (myPos === null) return;
        
        // 当前玩家相对于自己的位置
        let currentRelativePos = null;
        Object.entries(this.players).forEach(([pid, player], idx) => {
            if (pid === this.currentPlayerId) {
                currentRelativePos = idx;
            }
        });
        
        ['left', 'right', 'bottom'].forEach((pos, idx) => {
            const box = document.getElementById(`${pos}-avatar-box`);
            if (!box) return;
            
            if (idx === currentRelativePos) {
                box.classList.add('active');
            } else {
                box.classList.remove('active');
            }
        });
    }
    
    updatePlayerRoles() {
        Object.entries(this.players).forEach(([pid, player], idx) => {
            const pos = idx === 0 ? 'bottom' : (idx === 1 ? 'left' : 'right');
            const box = document.getElementById(`${pos}-avatar-box`);
            if (!box) return;
            
            // 移除所有角色类
            box.classList.remove('landlord', 'farmer');
            
            if (pid === this.landlordId) {
                box.classList.add('landlord');
            } else if (this.landlordId) {
                // 有地主后，其他玩家显示农民标识
                box.classList.add('farmer');
            }
        });
    }
    
    updateMultiplier() {
        const display = document.getElementById('multiplier-display');
        const value = document.getElementById('multiplier-value');
        
        if (this.multiplier > 1) {
            // 记录旧值用于动画
            const oldValue = parseInt(value.textContent) || 1;
            value.textContent = this.multiplier;
            display.classList.add('show');
            
            // 倍率增加动画
            if (this.multiplier > oldValue) {
                value.style.transform = 'scale(1.3)';
                value.style.color = '#fff';
                setTimeout(() => {
                    value.style.transition = 'all 0.3s ease';
                    value.style.transform = 'scale(1)';
                    value.style.color = '';
                }, 150);
            }
        } else {
            display.classList.remove('show');
        }
    }
    
    // 显示底牌 - 带3D展开动画
    showLandlordCards() {
        if (!this.gameState?.landlord_cards) return;
        
        const container = document.getElementById('landlord-cards-area');
        if (!container) return;
        
        container.innerHTML = '<span class="landlord-label">底牌</span>';
        
        this.gameState.landlord_cards.forEach((cardStr, idx) => {
            const card = this.parseCard(cardStr);
            const cardEl = this.createCardElement(card, false);
            
            // 添加翻转动画类
            cardEl.classList.add('flipping');
            
            // 添加底牌展示动画
            setTimeout(() => {
                cardEl.style.opacity = '0';
                cardEl.style.transform = 'translateY(-30px) scale(0.5)';
                container.appendChild(cardEl);
                
                // 触发动画
                requestAnimationFrame(() => {
                    cardEl.style.transition = 'all 0.4s ease-out';
                    cardEl.style.opacity = '1';
                    cardEl.style.transform = '';
                    
                    // 翻转动画完成后移除类
                    setTimeout(() => {
                        cardEl.classList.remove('flipping');
                    }, 400);
                });
            }, idx * 150);
        });
        
        container.classList.add('show');
    }
    
    // 解析牌字符串
    parseCard(cardStr) {
        // 格式: "♠3", "♥A", "小王", "大王"
        if (cardStr.includes('小王') || cardStr === 'JOKER') return { rank: 'JOKER', suit: '' };
        if (cardStr.includes('大王') || cardStr === 'BIG_JOKER') return { rank: 'BIG_JOKER', suit: '' };
        
        const suits = {'♠': 'S', '♥': 'H', '♦': 'D', '♣': 'C'};
        for (const [suit, code] of Object.entries(suits)) {
            if (cardStr.includes(suit)) {
                const rank = cardStr.replace(suit, '');
                return { rank, suit: code };
            }
        }
        return { rank: cardStr, suit: '' };
    }
    
    // 显示已出的牌
    showPlayedCards() {
        if (!this.gameState?.last_pattern_details?.cards) return;
        
        const container = document.getElementById('current-play-cards');
        const label = document.getElementById('play-label');
        const info = document.getElementById('last-player-info');
        
        if (!container) return;
        
        container.innerHTML = '';
        
        this.gameState.last_pattern_details.cards.forEach((cardStr, idx) => {
            const card = this.parseCard(cardStr);
            const cardEl = this.createCardElement(card, true);
            
            // 添加出牌动画
            cardEl.classList.add('playing');
            cardEl.style.animationDelay = `${idx * 0.08}s`;
            
            container.appendChild(cardEl);
        });
        
        const patternType = this.gameState.last_pattern_details.pattern_type || '';
        const lastPlayer = this.gameState.last_player;
        const playerName = this.players[lastPlayer]?.name || '未知';
        
        if (label) {
            label.textContent = this.getPatternName(patternType);
            // 添加标签动画
            label.classList.remove('show');
            setTimeout(() => label.classList.add('show'), 100);
        }
        if (info) info.textContent = playerName + ' 出牌';
    }
    
    // 获取牌型名称
    getPatternName(patternType) {
        const names = {
            'single': '单张',
            'pair': '对子',
            'triple': '三张',
            'straight': '顺子',
            'straight_pair': '连对',
            'triple_straight': '飞机',
            'flush': '同花',
            'full_house': '葫芦',
            'bomb': '炸弹',
            'rocket': '王炸',
            'four_two': '四带二',
            'four_four': '四炸'
        };
        
        // 特殊牌型显示
        if (patternType === 'rocket') return '💥 王炸！';
        if (patternType === 'bomb') return '💣 炸弹！';
        
        return names[patternType] || patternType || '出牌';
    }
    
    // 创建牌元素 - 增强3D效果
    createCardElement(card, isPlayed) {
        const cardEl = document.createElement('div');
        cardEl.className = 'card';
        
        const rank = card.rank || card;
        const suit = card.suit || '';
        
        // 判断颜色
        const isRed = suit === 'H' || suit === 'D';
        if (suit) {
            cardEl.classList.add(isRed ? 'red' : 'black');
        } else if (rank === 'JOKER' || rank === 'BIG_JOKER') {
            cardEl.classList.add(rank === 'BIG_JOKER' ? 'joker-red' : 'joker-black');
        }
        
        if (!isPlayed && suit) {
            const suitSymbol = this.suitSymbols[suit] || '';
            cardEl.innerHTML = `
                <div class="card-corner">
                    <span>${rank}</span>
                    <span class="suit">${suitSymbol}</span>
                </div>
                <div class="card-center">${suitSymbol}</div>
                <div class="card-corner" style="transform: rotate(180deg);">
                    <span>${rank}</span>
                    <span class="suit">${suitSymbol}</span>
                </div>
            `;
        } else if (rank === 'JOKER') {
            cardEl.innerHTML = '<div class="card-center">小王</div>';
        } else if (rank === 'BIG_JOKER') {
            cardEl.innerHTML = '<div class="card-center">大王</div>';
        }
        
        return cardEl;
    }
    
    // 更新自己的手牌 - 带动画
    updateMyCards() {
        const container = document.getElementById('my-cards-container');
        if (!container) return;
        
        container.innerHTML = '';
        
        this.myHand.forEach((card, idx) => {
            const cardEl = this.createCardElement(card, false);
            
            // 添加发牌动画
            cardEl.classList.add('dealing');
            cardEl.style.animationDelay = `${idx * 0.03}s`;
            
            if (this.selectedCards.has(idx)) {
                cardEl.classList.add('selected');
            }
            
            // 点击事件 - 带触觉反馈和翻转效果
            cardEl.addEventListener('click', () => {
                // 添加点击动画效果
                cardEl.style.transition = 'transform 0.1s ease';
                cardEl.style.transform = 'scale(0.95)';

                setTimeout(() => {
                    cardEl.style.transform = '';
                }, 100);

                if (this.selectedCards.has(idx)) {
                    this.selectedCards.delete(idx);
                    cardEl.classList.remove('selected');
                } else {
                    this.selectedCards.add(idx);
                    cardEl.classList.add('selected');
                }
            });
            
            container.appendChild(cardEl);
        });
        
        // 更新手牌数量
        document.getElementById('bottom-player-cards').textContent = this.myHand.length;
    }
    
    // 显示叫地主按钮
    showBidButtons() {
        // 检查是否轮到自己叫地主
        if (this.currentPlayerId !== this.playerId) {
            this.showWaiting('等待其他玩家叫地主...');
            return;
        }
        
        document.getElementById('bid-buttons')?.classList.add('show');
        document.getElementById('play-buttons')?.classList.remove('show');
        this.hideWaiting();
        
        // 显示底牌
        if (this.gameState?.landlord_cards) {
            this.showLandlordCards();
        }
    }
    
    // 隐藏叫地主按钮
    hideBidButtons() {
        document.getElementById('bid-buttons')?.classList.remove('show');
    }
    
    // 显示出牌按钮
    showPlayButtons() {
        if (this.currentPlayerId !== this.playerId) {
            this.showWaiting(`等待 ${this.players[this.currentPlayerId]?.name || '其他玩家'} 出牌...`);
            return;
        }
        
        document.getElementById('play-buttons')?.classList.add('show');
        this.hideWaiting();
        
        // 显示底牌（如果是地主）
        if (this.landlordId === this.playerId && this.gameState?.landlord_cards) {
            this.showLandlordCards();
        }
        
        // 显示已出的牌
        this.showPlayedCards();
        
        // 更新自己的手牌
        this.updateMyCards();
    }
    
    // 隐藏出牌按钮
    hidePlayButtons() {
        document.getElementById('play-buttons')?.classList.remove('show');
    }
    
    // 显示等待
    showWaiting(text) {
        const indicator = document.getElementById('waiting-indicator');
        const textEl = document.getElementById('waiting-text');
        
        if (textEl) textEl.textContent = text;
        if (indicator) indicator.classList.add('show');
    }
    
    // 隐藏等待
    hideWaiting() {
        document.getElementById('waiting-indicator')?.classList.remove('show');
    }
    
    // 添加聊天消息
    addChatMessage(sender, text) {
        const container = document.getElementById('chat-messages');
        if (!container) return;
        
        const msg = document.createElement('div');
        msg.className = 'chat-message';
        msg.innerHTML = `<span class="sender">${sender}:</span><span class="content">${text}</span>`;
        container.appendChild(msg);
        container.scrollTop = container.scrollHeight;
    }
    
    // 发送聊天
    sendChat() {
        const input = document.getElementById('chat-input');
        const text = input?.value?.trim();
        
        if (text) {
            this.addChatMessage(this.playerName, text);
            input.value = '';
        }
    }
    
    // 退出游戏
    quitGame() {
        if (confirm('确定要退出游戏吗？')) {
            if (this.pollInterval) {
                clearInterval(this.pollInterval);
            }
            if (this.ws) {
                this.ws.close();
            }
            // 返回首页
            window.location.href = '/';
        }
    }
    
    // 关闭设置
    closeSettings() {
        document.getElementById('settings-modal')?.classList.remove('show');
    }
    
    // ===== AI反馈系统 =====
    
    // 检测游戏状态变化并触发AI动画
    detectStateChange() {
        if (!this.previousGameState) {
            this.previousGameState = JSON.parse(JSON.stringify(this.gameState));
            return;
        }
        
        const prev = this.previousGameState;
        const curr = this.gameState;
        
        // 检测当前玩家变化 - 触发思考动画
        if (prev.current_player !== curr.current_player) {
            const prevPlayer = prev.current_player;
            const currPlayer = curr.current_player;
            
            // 如果前一个玩家是AI，先显示动作再换人
            if (prevPlayer && this.isAI(prevPlayer)) {
                // 显示上一个AI的动作（如果还没有显示）
                const lastAction = this.getLastPlayerAction(prevPlayer, prev);
                if (lastAction) {
                    this.hideThinking(prevPlayer);
                    this.showAIAction(prevPlayer, lastAction);
                    
                    // 如果出了牌，播放飞牌动画
                    if (lastAction.type === 'play' && lastAction.cards) {
                        setTimeout(() => {
                            this.animateAICards(prevPlayer, lastAction.cards);
                        }, 300);
                    }
                } else {
                    this.hideThinking(prevPlayer);
                }
            }
            
            // 如果当前玩家是AI，显示思考状态
            if (currPlayer && this.isAI(currPlayer)) {
                // 延迟一点显示思考，让动作气泡先消失
                setTimeout(() => {
                    this.showThinking(currPlayer);
                }, 400);
            }
        }
        
        // 检测叫地主阶段的变化
        if (prev.phase !== '叫地主' && curr.phase === '叫地主') {
            // 新开始叫地主阶段
        }
        
        // 检测出牌变化 - AI出牌
        if (prev.last_action !== curr.last_action && curr.last_action) {
            const action = curr.last_action;
            const actionPlayer = action.player_id || curr.last_player;
            
            if (actionPlayer && this.isAI(actionPlayer)) {
                // 隐藏思考状态
                this.hideThinking(actionPlayer);
                
                // 显示动作气泡
                this.showAIAction(actionPlayer, action);
                
                // 如果出了牌，播放飞牌动画
                if (action.type === 'play' && action.cards && action.cards.length > 0) {
                    setTimeout(() => {
                        this.animateAICards(actionPlayer, action.cards);
                    }, 500);
                }
            }
            
            // 清除last_action以避免重复触发
            this.gameState.last_action = null;
        }
        
        // 检测地主确定
        if (prev.landlord !== curr.landlord && curr.landlord) {
            const landlordPid = curr.landlord;
            if (this.isAI(landlordPid)) {
                // 显示AI叫到地主的动画
                setTimeout(() => {
                    this.showAIAction(landlordPid, { type: 'become_landlord' });
                }, 800);
            }
        }
        
        // 检测牌数变化（AI出牌后手牌减少）
        this.detectCardCountChanges(prev, curr);
        
        this.previousGameState = JSON.parse(JSON.stringify(this.gameState));
    }
    
    // 获取玩家最后的动作
    getLastPlayerAction(playerId, state) {
        if (state.last_action && state.last_action.player_id === playerId) {
            return state.last_action;
        }
        // 检查历史动作
        if (state.action_history) {
            for (let i = state.action_history.length - 1; i >= 0; i--) {
                if (state.action_history[i].player_id === playerId) {
                    return state.action_history[i];
                }
            }
        }
        return null;
    }
    
    // 检测手牌数量变化
    detectCardCountChanges(prev, curr) {
        Object.entries(curr.players || {}).forEach(([pid, player]) => {
            const prevPlayer = prev.players?.[pid];
            if (prevPlayer && player.card_count !== prevPlayer.card_count) {
                // 牌数减少，可能是出牌了
                if (player.card_count < prevPlayer.card_count && this.isAI(pid)) {
                    // AI出牌了，但last_action可能还没更新
                    // 等待下一轮更新
                }
            }
        });
    }
    
    // 判断是否为AI玩家
    isAI(playerId) {
        const player = this.players[playerId];
        return player && player.name && (player.name.includes('电脑') || player.is_ai);
    }
    
    // 获取玩家在界面上的位置
    getPlayerPosition(playerId) {
        let pos = null;
        Object.entries(this.players).forEach(([pid, player], idx) => {
            if (pid === playerId) {
                pos = idx === 1 ? 'left' : (idx === 2 ? 'right' : 'bottom');
            }
        });
        return pos;
    }
    
    // 显示AI思考状态 - 增强版
    showThinking(playerId) {
        // 清除之前的思考超时
        if (this.thinkingTimeout) {
            clearTimeout(this.thinkingTimeout);
        }
        
        const pos = this.getPlayerPosition(playerId);
        if (!pos || pos === 'bottom') return; // 自己不需要思考动画
        
        const playerBox = document.getElementById(`${pos}-avatar-box`);
        if (!playerBox) return;
        
        // 创建思考动画元素 - 增强版带光晕
        let thinkingEl = playerBox.querySelector('.thinking-indicator');
        if (!thinkingEl) {
            thinkingEl = document.createElement('div');
            thinkingEl.className = 'thinking-indicator';
            thinkingEl.innerHTML = `
                <div class="thinking-ring"></div>
                <span></span><span></span><span></span>
            `;
            playerBox.appendChild(thinkingEl);
        }
        
        thinkingEl.classList.add('show');
        this.thinkingPlayerId = playerId;
        
        // 1-3秒后自动隐藏思考状态
        const thinkingTime = 1000 + Math.random() * 2000;
        this.thinkingTimeout = setTimeout(() => {
            this.hideThinking(playerId);
        }, thinkingTime);
    }
    
    // 隐藏AI思考状态 - 增强版
    hideThinking(playerId) {
        if (this.thinkingTimeout) {
            clearTimeout(this.thinkingTimeout);
            this.thinkingTimeout = null;
        }
        
        const pos = this.getPlayerPosition(playerId);
        if (!pos || pos === 'bottom') return;
        
        const playerBox = document.getElementById(`${pos}-avatar-box`);
        const thinkingEl = playerBox?.querySelector('.thinking-indicator');
        if (thinkingEl) {
            thinkingEl.classList.remove('show');
        }
        
        this.thinkingPlayerId = null;
    }
    
    // 显示AI动作气泡 - 增强版
    showAIAction(playerId, action) {
        const pos = this.getPlayerPosition(playerId);
        if (!pos || pos === 'bottom') return;
        
        const playerBox = document.getElementById(`${pos}-avatar-box`);
        if (!playerBox) return;
        
        // 获取动作文本和类型
        let actionText = '';
        let actionType = '';
        let actionEmoji = '';
        
        if (action.type === 'bid') {
            actionType = 'bid';
            if (action.multiplier === 0) {
                actionText = '不叫';
                actionEmoji = '🚫';
            } else if (action.multiplier === 1) {
                actionText = '叫地主';
                actionEmoji = '👑';
            } else if (action.multiplier === 2) {
                actionText = '抢地主';
                actionEmoji = '🔥';
            }
        } else if (action.type === 'pass') {
            actionType = 'pass';
            actionText = '过';
            actionEmoji = '⏭️';
        } else if (action.type === 'play') {
            actionType = 'play';
            // 检查牌型
            const patternType = action.pattern_type || '';
            const cardCount = action.cards?.length || 0;
            actionText = this.getActionPlayText(patternType, cardCount);
            actionEmoji = this.getActionPlayEmoji(patternType, cardCount);
        } else if (action.type === 'become_landlord') {
            actionType = 'landlord';
            actionText = '当地主';
            actionEmoji = '🏆';
        } else if (action.type === 'double') {
            actionType = 'bid';
            actionText = '加倍';
            actionEmoji = '⬆️';
        }
        
        if (!actionText) return;
        
        // 创建气泡元素 - 增强版
        const bubble = document.createElement('div');
        bubble.className = `action-bubble ${actionType}`;
        bubble.innerHTML = `
            <span class="bubble-emoji">${actionEmoji}</span>
            <span class="bubble-text">${actionText}</span>
            <div class="bubble-glow"></div>
        `;
        
        // 移除旧的气泡
        const oldBubble = playerBox.querySelector('.action-bubble');
        if (oldBubble) {
            oldBubble.remove();
        }
        
        playerBox.appendChild(bubble);
        
        // 显示气泡 - 带弹性动画
        requestAnimationFrame(() => {
            bubble.classList.add('show');
        });
        
        // 2.5秒后隐藏气泡（稍长一点让玩家看清）
        setTimeout(() => {
            bubble.classList.remove('show');
            setTimeout(() => bubble.remove(), 400);
        }, 2500);
    }
    
    // 获取出牌动作的文本
    getActionPlayText(patternType, cardCount) {
        const textMap = {
            'single': '单张',
            'pair': '对子',
            'triple': '三张',
            'straight': '顺子',
            'straight_pair': '连对',
            'triple_straight': '飞机',
            'flush': '同花',
            'full_house': '葫芦',
            'bomb': '炸弹',
            'rocket': '王炸',
            'four_two': '四带二',
            'four_four': '四炸'
        };
        
        if (patternType === 'bomb' || patternType === 'rocket') {
            return patternType === 'rocket' ? '王炸！' : '炸弹！';
        }
        
        if (cardCount >= 5 && textMap[patternType]) {
            return textMap[patternType];
        }
        
        return `出${cardCount}张`;
    }
    
    // 获取出牌动作的表情
    getActionPlayEmoji(patternType, cardCount) {
        if (patternType === 'rocket') return '💥';
        if (patternType === 'bomb') return '💣';
        if (patternType === 'full_house') return '🎯';
        if (patternType === 'straight' || patternType === 'straight_pair') return '📈';
        if (patternType === 'triple' || patternType === 'triple_straight') return '✈️';
        return '🃏';
    }
    
    // AI出牌的飞牌动画 - 增强版
    animateAICards(playerId, cards) {
        const fromPos = this.getPlayerPosition(playerId);
        if (!fromPos || fromPos === 'bottom') return;
        
        const cardContainer = document.getElementById('current-play-cards');
        if (!cardContainer) return;
        
        const cardCount = cards.length;
        
        // 创建飞行的牌
        cards.forEach((cardStr, idx) => {
            const card = this.parseCard(cardStr);
            const cardEl = this.createCardElement(card, true);
            
            // 设置起始位置
            cardEl.classList.add('flying-card');
            cardEl.style.position = 'fixed';
            cardEl.style.zIndex = '1000';
            cardEl.style.pointerEvents = 'none';
            
            // 计算起始和结束位置
            const startPos = this.getPlayerCardPosition(fromPos, idx, cardCount);
            const endPos = this.getCenterCardPosition(idx, cardCount);
            
            // 添加旋转角度 - 模拟抛物线
            const rotation = (Math.random() - 0.5) * 30 * (idx % 2 === 0 ? 1 : -1);
            
            cardEl.style.left = startPos.left + 'px';
            cardEl.style.top = startPos.top + 'px';
            cardEl.style.transform = 'scale(0.3) rotate(' + rotation + 'deg)';
            cardEl.style.opacity = '0.8';
            
            // 添加拖尾效果
            cardEl.style.boxShadow = '0 10px 30px rgba(0,0,0,0.5)';
            
            document.body.appendChild(cardEl);
            
            // 使用弹性缓动触发动画
            requestAnimationFrame(() => {
                cardEl.style.transition = 'all 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)';
                cardEl.style.left = endPos.left + 'px';
                cardEl.style.top = endPos.top + 'px';
                cardEl.style.transform = 'scale(1) rotate(0deg)';
                cardEl.style.opacity = '1';
                
                // 添加抛出时的缩放效果
                cardEl.animate([
                    { transform: 'scale(0.3) rotate(' + rotation + 'deg)' },
                    { transform: 'scale(1.1) rotate(0deg)' },
                    { transform: 'scale(1) rotate(0deg)' }
                ], {
                    duration: 500,
                    easing: 'cubic-bezier(0.34, 1.56, 0.64, 1)'
                });
            });
            
            // 动画结束后添加到正确位置并播放音效
            setTimeout(() => {
                // 播放出牌音效（可选）
                this.playCardSound();
                
                cardEl.remove();
                // 刷新已出牌的显示
                this.showPlayedCards();
            }, 550);
        });
        
        // 延迟显示牌型标签
        setTimeout(() => {
            const label = document.getElementById('play-label');
            if (label) {
                label.classList.remove('show');
                setTimeout(() => label.classList.add('show'), 100);
            }
        }, 600);
    }
    
    // 播放出牌音效（占位）
    playCardSound() {
        // 可以在这里添加音效播放逻辑
        // 暂时静默处理
    }
    
    // 获取对手玩家出牌时的起始位置（增强版）
    getPlayerCardPosition(pos, cardIndex, totalCards) {
        const playerBox = document.getElementById(`${pos}-avatar-box`);
        const rect = playerBox?.getBoundingClientRect();
        
        if (!rect) return { left: window.innerWidth / 2, top: window.innerHeight / 2 };
        
        // 根据玩家位置调整起始点
        let startX, startY;
        
        if (pos === 'left') {
            startX = rect.right - 20;
            startY = rect.top + rect.height / 2;
        } else if (pos === 'right') {
            startX = rect.left + 20;
            startY = rect.top + rect.height / 2;
        } else {
            startX = rect.left + rect.width / 2;
            startY = rect.top;
        }
        
        // 多张牌时分散起始位置
        if (totalCards > 1) {
            const offset = (cardIndex - (totalCards - 1) / 2) * 15;
            startX += offset;
        }
        
        return {
            left: startX,
            top: startY
        };
    }
    
    // 获取中心区域出牌的目标位置
    getCenterCardPosition(index, total) {
        const container = document.getElementById('current-play-cards');
        const rect = container?.getBoundingClientRect();
        
        if (!rect) return { left: window.innerWidth / 2, top: window.innerHeight / 2 - 50 };
        
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        const cardWidth = 80;
        const spacing = 25;
        
        const totalWidth = (total - 1) * spacing;
        const startX = centerX - totalWidth / 2;
        
        return {
            left: startX + index * spacing - cardWidth / 2,
            top: centerY - 60
        };
    }
}

// 初始化游戏
document.addEventListener('DOMContentLoaded', () => {
    window.game = new DouDizhuGame();
});
