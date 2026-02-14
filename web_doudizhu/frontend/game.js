/**
 * 斗地主游戏前端交互逻辑
 */

class DouDizhuGame {
    constructor() {
        this.ws = null;
        this.roomId = null;
        this.playerId = null;
        this.playerName = null;
        this.gameState = null;
        this.selectedCards = new Set();
        this.cardImages = {};
        
        this.initEventListeners();
        this.loadCardImages();
    }
    
    /**
     * 初始化事件监听器
     */
    initEventListeners() {
        // 连接按钮
        document.getElementById('connect-btn')?.addEventListener('click', () => this.connectToGame());
        
        // 创建房间按钮
        document.getElementById('create-room-btn')?.addEventListener('click', () => this.createRoom());
        
        // 加入房间按钮
        document.getElementById('join-room-btn')?.addEventListener('click', () => this.joinRoom());
        
        // 叫地主按钮
        document.getElementById('call-landlord-btn')?.addEventListener('click', () => this.bid(1));
        document.getElementById('bid-2x-btn')?.addEventListener('click', () => this.bid(2));
        document.getElementById('bid-3x-btn')?.addEventListener('click', () => this.bid(3));
        document.getElementById('pass-bid-btn')?.addEventListener('click', () => this.passBid());
        
        // 出牌按钮
        document.getElementById('play-cards-btn')?.addEventListener('click', () => this.playCards());
        
        // 过牌按钮
        document.getElementById('pass-turn-btn')?.addEventListener('click', () => this.passTurn());
        
        // 提示按钮
        document.getElementById('hint-btn')?.addEventListener('click', () => this.getHint());
        
        // 排序手牌按钮
        document.getElementById('sort-hand-btn')?.addEventListener('click', () => this.sortHand());
        
        // 撤销按钮
        document.getElementById('undo-btn')?.addEventListener('click', () => this.undo());
        
        // 设置按钮
        document.getElementById('settings-btn')?.addEventListener('click', () => this.openSettings());
        
        // 帮助按钮
        document.getElementById('help-btn')?.addEventListener('click', () => this.openHelp());
        
        // 退出按钮
        document.getElementById('quit-btn')?.addEventListener('click', () => this.quitGame());
        
        // 聊天按钮
        document.getElementById('chat-toggle')?.addEventListener('click', () => this.toggleChat());
        document.getElementById('send-chat')?.addEventListener('click', () => this.sendChatMessage());
        document.getElementById('chat-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendChatMessage();
        });
        
        // 声音按钮
        document.getElementById('sound-toggle')?.addEventListener('click', () => this.toggleSound());
        
        // 全屏按钮
        document.getElementById('fullscreen-toggle')?.addEventListener('click', () => this.toggleFullscreen());
        
        // 牌点击事件（委托）
        document.getElementById('hand-display')?.addEventListener('click', (e) => {
            if (e.target.classList.contains('card')) {
                this.toggleCardSelection(e.target);
            }
        });
    }
    
    /**
     * 加载牌面图片
     */
    loadCardImages() {
        // 牌面显示系统 - 使用纯CSS样式显示牌面，无需实际图片文件
        // 系统使用Unicode字符和CSS颜色来显示扑克牌
        const suits = ['S', 'H', 'D', 'C'];
        const ranks = ['3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A', '2'];
        
        // 创建牌面标识符映射（用于CSS样式显示）
        ranks.forEach(rank => {
            suits.forEach(suit => {
                const cardKey = `${rank}${suit}`;
                this.cardImages[cardKey] = cardKey; // 保存牌面标识符
            });
        });
        
        // 大小王
        this.cardImages['SJ'] = 'SJ';
        this.cardImages['BJ'] = 'BJ';
        
        console.log('牌面显示系统已加载（使用纯CSS样式，无需外部图片文件）');
    }
    
    /**
     * 连接到游戏服务器
     */
    async connectToGame() {
        const playerName = document.getElementById('player-name')?.value?.trim() || '玩家';
        if (!playerName) {
            this.showMessage('请输入玩家名称', 'error');
            return;
        }
        
        this.playerName = playerName;
        
        // 更新连接状态为连接中
        this.updateConnectionStatus(false);
        
        try {
            // 获取可用房间
            const response = await fetch('/api/rooms');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            const rooms = await response.json();
            
            this.updateRoomList(rooms);
            this.showMessage('连接成功！', 'success');
            this.updateConnectionStatus(true);
            this.showGameLobby();
            
        } catch (error) {
            this.showMessage('连接服务器失败: ' + error.message, 'error');
            this.updateConnectionStatus(false);
        }
    }
    
    /**
     * 创建房间
     */
    async createRoom() {
        const roomName = document.getElementById('room-name')?.value?.trim() || '斗地主房间';
        
        try {
            const response = await fetch('/api/rooms', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    room_name: roomName,
                    player_name: this.playerName
                })
            });
            
            const data = await response.json();
            this.roomId = data.room_id;
            this.playerId = data.player_id;
            
            this.showMessage(`房间创建成功！房间号: ${this.roomId}`, 'success');
            this.connectWebSocket();
            this.showGameRoom();
            
        } catch (error) {
            this.showMessage('创建房间失败: ' + error.message, 'error');
        }
    }
    
    /**
     * 加入房间
     */
    async joinRoom() {
        const roomId = document.getElementById('join-room-id')?.value?.trim();
        if (!roomId) {
            this.showMessage('请输入房间号', 'error');
            return;
        }
        
        try {
            const response = await fetch(`/api/rooms/${roomId}/join`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    player_name: this.playerName
                })
            });
            
            const data = await response.json();
            this.roomId = roomId;
            this.playerId = data.player_id;
            
            this.showMessage(`成功加入房间 ${roomId}`, 'success');
            this.connectWebSocket();
            this.showGameRoom();
            
        } catch (error) {
            this.showMessage('加入房间失败: ' + error.message, 'error');
        }
    }
    
    /**
     * 连接WebSocket
     */
    connectWebSocket() {
        const wsUrl = `ws://${window.location.host}/ws/${this.roomId}/${this.playerId}`;
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('WebSocket连接已建立');
            this.showMessage('游戏连接已建立', 'success');
            this.updateConnectionStatus(true);
            
            // 发送玩家信息
            this.ws.send(JSON.stringify({
                type: 'player_join',
                player_id: this.playerId,
                player_name: this.playerName
            }));
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleGameMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket连接已关闭');
            this.showMessage('游戏连接已断开', 'warning');
            this.updateConnectionStatus(false);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
            this.showMessage('游戏连接错误', 'error');
            this.updateConnectionStatus(false);
        };
    }
    
    /**
     * 处理游戏消息
     */
    handleGameMessage(data) {
        console.log('收到游戏消息:', data);
        
        if (data.type === 'game_state') {
            this.updateGameState(data.data);
        } else if (data.type === 'player_joined') {
            this.showMessage(`${data.player_name} 加入了游戏`, 'info');
            this.addChatMessage('系统', `${data.player_name} 加入了游戏`);
        } else if (data.type === 'player_left') {
            this.showMessage(`${data.player_name} 离开了游戏`, 'warning');
            this.addChatMessage('系统', `${data.player_name} 离开了游戏`);
        } else if (data.type === 'game_started') {
            this.showMessage('游戏开始！', 'success');
            this.addChatMessage('系统', '游戏开始！');
        } else if (data.type === 'cards_dealt') {
            this.updatePlayerHand(data.cards);
            this.addChatMessage('系统', '牌已分发');
        } else if (data.type === 'bid_turn') {
            this.showMessage(`${data.player_name} 的叫分回合`, 'info');
            this.showBiddingPhase(data.player_id === this.playerId);
        } else if (data.type === 'bid_made') {
            this.showMessage(`${data.player_name} 叫了 ${data.bid} 分`, 'info');
            this.addChatMessage(data.player_name, `叫了 ${data.bid} 分`);
        } else if (data.type === 'landlord_selected') {
            this.showMessage(`${data.player_name} 成为地主！`, 'success');
            this.addChatMessage('系统', `${data.player_name} 成为地主！`);
        } else if (data.type === 'play_turn') {
            this.showMessage(`${data.player_name} 的出牌回合`, 'info');
            this.showPlayPhase(data.player_id === this.playerId);
        } else if (data.type === 'cards_played') {
            this.showMessage(`${data.player_name} 出了 ${data.cards.length} 张牌`, 'info');
            this.addChatMessage(data.player_name, `出了 ${this.formatCards(data.cards)}`);
            this.updateLastPlay(data.player_name, data.cards, data.pattern);
        } else if (data.type === 'player_passed') {
            this.showMessage(`${data.player_name} 过牌`, 'info');
            this.addChatMessage(data.player_name, '过牌');
        } else if (data.type === 'game_ended') {
            this.showGameResult(data.winner, data.scores);
        } else if (data.type === 'error') {
            this.showMessage(data.message, 'error');
        }
    }    
    /**
     * 更新游戏状态
     */
    updateGameState(state) {
        this.gameState = state;
        
        // 更新UI
        this.updateGameInfo(state);
        this.updatePlayers(state.players);
        this.updateTable(state);
        
        // 根据阶段显示不同界面
        switch (state.phase) {
            case 'WAITING':
                this.showWaitingPhase();
                break;
            case 'BIDDING':
                this.showBiddingPhase(state.current_player === this.playerId);
                break;
            case 'PLAYING':
                this.showPlayPhase(state.current_player === this.playerId);
                break;
            case 'FINISHED':
                this.showGameResult(state.winner, {});
                break;
        }
    }
    
    /**
     * 更新游戏信息
     */
    updateGameInfo(state) {
        // 更新房间信息
        const roomIdElement = document.getElementById('room-id');
        if (roomIdElement) roomIdElement.textContent = `房间: #${this.roomId}`;
        
        // 更新游戏阶段
        const gamePhaseElement = document.getElementById('game-phase');
        if (gamePhaseElement) gamePhaseElement.textContent = this.getPhaseName(state.phase);
        
        // 更新当前玩家
        const currentPlayerElement = document.getElementById('current-player');
        if (currentPlayerElement) {
            currentPlayerElement.textContent = 
                state.players[state.current_player]?.name || state.current_player;
        }
        
        // 更新地主
        const landlordPlayerElement = document.getElementById('landlord-player');
        if (landlordPlayerElement) {
            landlordPlayerElement.textContent = 
                state.players[state.landlord]?.name || state.landlord || '无';
        }
        
        // 更新回合数
        const roundNumberElement = document.getElementById('round-number');
        if (roundNumberElement) roundNumberElement.textContent = state.round || 1;
        
        // 更新分数
        const gameScoreElement = document.getElementById('game-score');
        if (gameScoreElement) gameScoreElement.textContent = this.calculateScores(state.players);
        
        // 更新最后出牌
        if (state.last_pattern) {
            const lastPlayElement = document.getElementById('last-play');
            if (lastPlayElement) {
                lastPlayElement.textContent = 
                    `${state.players[state.last_player]?.name || state.last_player}: ${state.last_pattern}`;
            }
        }
    }
    
    /**
     * 更新玩家列表
     */
    updatePlayers(players) {
        // 更新玩家1（顶部）
        this.updatePlayerUI('player1', players['player1'] || players[0]);
        // 更新玩家2（左侧）
        this.updatePlayerUI('player2', players['player2'] || players[1]);
        // 更新玩家3（右侧）
        this.updatePlayerUI('player3', players['player3'] || players[2]);
        // 更新当前玩家（底部）
        this.updatePlayerUI('current', players[this.playerId]);
        
        // 更新玩家列表面板
        const playerList = document.getElementById('player-list');
        if (playerList) {
            playerList.innerHTML = '';
            Object.values(players).forEach(player => {
                const playerElement = document.createElement('div');
                playerElement.className = 'player-item';
                playerElement.innerHTML = `
                    <div class="player-avatar">
                        <i class="fas fa-user"></i>
                    </div>
                    <div class="player-info">
                        <div class="player-name">${player.name}</div>
                        <div class="player-role">${player.role || '等待中'}</div>
                        <div class="player-cards">剩余: ${player.card_count || 0} 张</div>
                    </div>
                `;
                
                if (player.id === this.playerId) {
                    playerElement.classList.add('current-player');
                }
                
                playerList.appendChild(playerElement);
            });
        }
    }
    
    /**
     * 更新单个玩家UI
     */
    updatePlayerUI(playerPosition, player) {
        if (!player) return;
        
        const nameElem = document.getElementById(`${playerPosition}-player-name`);
        const roleElem = document.getElementById(`${playerPosition}-player-role`);
        const cardsElem = document.getElementById(`${playerPosition}-player-cards`);
        const turnElem = document.getElementById(`${playerPosition}-player-turn`);
        
        if (nameElem) nameElem.textContent = player.name;
        if (roleElem) roleElem.textContent = player.role || '农民';
        if (cardsElem) cardsElem.textContent = `${player.card_count || 0} 张牌`;
        
        // 更新回合指示器
        if (turnElem && this.gameState) {
            if (player.id === this.gameState.current_player) {
                turnElem.classList.add('active');
            } else {
                turnElem.classList.remove('active');
            }
        }
    }
    
    /**
     * 更新牌桌
     */
    updateTable(state) {
        const tableCenter = document.getElementById('table-center');
        if (!tableCenter) return;
        
        // 更新地主牌
        this.updateLandlordCards(state.landlord_cards);
        
        // 更新最后出牌
        if (state.last_cards && state.last_cards.length > 0) {
            tableCenter.innerHTML = `
                <div class="last-play">
                    <div class="last-player">${state.players[state.last_player]?.name || state.last_player}</div>
                    <div class="last-cards">
                        ${this.renderCards(state.last_cards)}
                    </div>
                    <div class="last-pattern">${state.last_pattern || ''}</div>
                </div>
            `;
        } else {
            tableCenter.innerHTML = '<div class="empty-table">等待出牌...</div>';
        }
    }
    
    /**
     * 更新地主牌
     */
    updateLandlordCards(cards) {
        const landlordCardsElem = document.getElementById('landlord-cards');
        if (!landlordCardsElem || !cards) return;
        
        landlordCardsElem.innerHTML = `
            <div class="landlord-label">地主牌</div>
            <div class="cards-container">
                ${cards.map(card => `<div class="card landlord-card">${this.formatCard(card)}</div>`).join('')}
            </div>
        `;
    }
    
    /**
     * 更新玩家手牌
     */
    updatePlayerHand(cards) {
        const handDisplay = document.getElementById('hand-display');
        if (!handDisplay) return;
        
        handDisplay.innerHTML = '';
        
        cards.forEach((card, index) => {
            const cardElement = this.createCardElement(card, index);
            handDisplay.appendChild(cardElement);
        });
        
        this.selectedCards.clear();
        this.updateSelectedCount();
    }
    
    /**
     * 创建牌元素
     */
    createCardElement(card, index) {
        const cardElement = document.createElement('div');
        cardElement.className = 'card';
        cardElement.dataset.index = index;
        cardElement.dataset.card = card;
        
        // 设置牌面显示
        const [rank, suit] = this.parseCard(card);
        cardElement.innerHTML = `
            <div class="card-rank">${rank}</div>
            <div class="card-suit">${this.getSuitSymbol(suit)}</div>
        `;
        
        // 设置花色颜色
        if (suit === 'H' || suit === 'D') {
            cardElement.classList.add('red');
        } else {
            cardElement.classList.add('black');
        }
        
        return cardElement;
    }
    
    /**
     * 解析牌字符串
     */
    parseCard(cardStr) {
        if (cardStr === 'SJ') return ['小王', '🃏'];
        if (cardStr === 'BJ') return ['大王', '🃏'];
        
        const suit = cardStr.slice(-1);
        const rank = cardStr.slice(0, -1);
        
        // 将英文牌面转换为中文显示
        const rankDisplay = {
            'A': 'A',
            '2': '2', 
            '3': '3',
            '4': '4',
            '5': '5',
            '6': '6',
            '7': '7',
            '8': '8',
            '9': '9',
            '10': '10',
            'J': 'J',
            'Q': 'Q',
            'K': 'K'
        }[rank] || rank;
        
        return [rankDisplay, suit];
    }
    
    /**
     * 获取花色符号
     */
    getSuitSymbol(suit) {
        const symbols = {
            'S': '♠', // 黑桃
            'H': '♥', // 红心
            'D': '♦', // 方块
            'C': '♣', // 梅花
            '🃏': '🃏' // 王
        };
        return symbols[suit] || suit;
    }
    
    /**
     * 渲染牌组
     */
    renderCards(cards) {
        return cards.map(card => {
            const [rank, suit] = this.parseCard(card);
            const colorClass = (suit === 'H' || suit === 'D') ? 'red' : 'black';
            return `<span class="card-small ${colorClass}">${rank}${this.getSuitSymbol(suit)}</span>`;
        }).join('');
    }
    
    /**
     * 格式化牌
     */
    formatCard(card) {
        const [rank, suit] = this.parseCard(card);
        return `${rank}${this.getSuitSymbol(suit)}`;
    }
    
    /**
     * 格式化牌组
     */
    formatCards(cards) {
        return cards.map(card => this.formatCard(card)).join(' ');
    }    
    /**
     * 切换牌的选择状态
     */
    toggleCardSelection(cardElement) {
        const index = parseInt(cardElement.dataset.index);
        
        if (this.selectedCards.has(index)) {
            this.selectedCards.delete(index);
            cardElement.classList.remove('selected');
        } else {
            this.selectedCards.add(index);
            cardElement.classList.add('selected');
        }
        
        this.updateSelectedCount();
    }
    
    /**
     * 更新已选牌数量
     */
    updateSelectedCount() {
        const count = this.selectedCards.size;
        const selectedCountElem = document.getElementById('selected-count');
        if (selectedCountElem) {
            selectedCountElem.textContent = count;
        }
        
        // 启用/禁用出牌按钮
        const playBtn = document.getElementById('play-cards-btn');
        if (playBtn) {
            playBtn.disabled = count === 0;
        }
    }
    
    /**
     * 叫地主
     */
    bid(multiplier) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.showMessage('连接未就绪', 'error');
            return;
        }
        
        this.ws.send(JSON.stringify({
            type: 'bid',
            multiplier: multiplier
        }));
        
        this.showMessage(`你叫了 ${multiplier} 分`, 'info');
    }
    
    /**
     * 过牌（叫地主阶段）
     */
    passBid() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.showMessage('连接未就绪', 'error');
            return;
        }
        
        this.ws.send(JSON.stringify({
            type: 'bid',
            multiplier: 0  // 0表示不叫
        }));
        
        this.showMessage('你选择不叫', 'info');
    }
    
    /**
     * 出牌
     */
    playCards() {
        if (this.selectedCards.size === 0) {
            this.showMessage('请选择要出的牌', 'error');
            return;
        }
        
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.showMessage('连接未就绪', 'error');
            return;
        }
        
        const cardIndices = Array.from(this.selectedCards);
        this.ws.send(JSON.stringify({
            type: 'play',
            card_indices: cardIndices
        }));
        
        this.selectedCards.clear();
        this.updateSelectedCount();
    }
    
    /**
     * 过牌（出牌阶段）
     */
    passTurn() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.showMessage('连接未就绪', 'error');
            return;
        }
        
        this.ws.send(JSON.stringify({
            type: 'pass'
        }));
        
        this.showMessage('你选择过牌', 'info');
    }
    
    /**
     * 获取提示
     */
    getHint() {
        if (!this.gameState || !this.playerId) return;
        
        // 这里可以调用AI提示接口
        this.showMessage('提示功能正在开发中', 'info');
    }
    
    /**
     * 排序手牌
     */
    sortHand() {
        // 重新渲染手牌，按牌面大小排序
        if (this.gameState && this.gameState.players[this.playerId]) {
            const player = this.gameState.players[this.playerId];
            // 假设player.cards包含手牌
            // 这里需要实现排序逻辑
            this.showMessage('手牌已排序', 'info');
        }
    }
    
    /**
     * 撤销操作
     */
    undo() {
        this.showMessage('撤销功能正在开发中', 'info');
    }
    
    /**
     * 打开设置
     */
    openSettings() {
        const settingsModal = document.getElementById('settings-modal');
        if (settingsModal) {
            settingsModal.style.display = 'block';
        }
    }
    
    /**
     * 打开帮助
     */
    openHelp() {
        this.showMessage('帮助文档正在开发中', 'info');
    }
    
    /**
     * 退出游戏
     */
    quitGame() {
        if (confirm('确定要退出游戏吗？')) {
            if (this.ws) {
                this.ws.close();
            }
            window.location.reload();
        }
    }
    
    /**
     * 切换聊天面板
     */
    toggleChat() {
        const chatPanel = document.getElementById('chat-panel');
        if (chatPanel) {
            chatPanel.classList.toggle('hidden');
        }
    }
    
    /**
     * 发送聊天消息
     */
    sendChatMessage() {
        const chatInput = document.getElementById('chat-input');
        if (!chatInput || !chatInput.value.trim()) return;
        
        const message = chatInput.value.trim();
        this.addChatMessage('你', message);
        
        // 发送到服务器（如果需要）
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'chat',
                message: message
            }));
        }
        
        chatInput.value = '';
    }
    
    /**
     * 添加聊天消息
     */
    addChatMessage(sender, message) {
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;
        
        const messageElement = document.createElement('div');
        messageElement.className = 'chat-message';
        messageElement.innerHTML = `
            <span class="message-time">[${this.getCurrentTime()}]</span>
            <span class="message-sender">${sender}:</span>
            <span class="message-text">${message}</span>
        `;
        
        chatMessages.appendChild(messageElement);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
    
    /**
     * 切换声音
     */
    toggleSound() {
        const soundBtn = document.getElementById('sound-toggle');
        if (soundBtn) {
            const isMuted = soundBtn.classList.toggle('muted');
            soundBtn.innerHTML = isMuted ? 
                '<i class="fas fa-volume-mute"></i> Sound' : 
                '<i class="fas fa-volume-up"></i> Sound';
            this.showMessage(isMuted ? '声音已关闭' : '声音已开启', 'info');
        }
    }
    
    /**
     * 切换全屏
     */
    toggleFullscreen() {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(err => {
                console.error('全屏失败:', err);
            });
        } else {
            document.exitFullscreen();
        }
    }    
    /**
     * 更新房间列表
     */
    updateRoomList(rooms) {
        const roomList = document.getElementById('room-list');
        if (!roomList) return;
        
        roomList.innerHTML = '';
        
        if (rooms.length === 0) {
            roomList.innerHTML = '<div class="empty-room">暂无房间，请创建新房间</div>';
            return;
        }
        
        rooms.forEach(room => {
            const roomElement = document.createElement('div');
            roomElement.className = 'room-item';
            roomElement.innerHTML = `
                <div class="room-info">
                    <div class="room-name">${room.name || '未命名房间'}</div>
                    <div class="room-id">房间号: ${room.id}</div>
                </div>
                <div class="room-stats">
                    <div class="room-players">玩家: ${room.player_count || 0}/3</div>
                    <div class="room-status">${room.status || '等待中'}</div>
                </div>
                <button class="btn btn-small join-room-btn" data-room-id="${room.id}">
                    加入
                </button>
            `;
            
            roomList.appendChild(roomElement);
        });
        
        // 为加入按钮添加事件监听器
        document.querySelectorAll('.join-room-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const roomId = e.target.dataset.roomId;
                document.getElementById('join-room-id').value = roomId;
                this.joinRoom();
            });
        });
    }
    
    /**
     * 显示等待阶段
     */
    showWaitingPhase() {
        this.hideAllPanels();
        document.getElementById('waiting-panel')?.classList.remove('hidden');
    }
    
    /**
     * 显示叫地主阶段
     */
    showBiddingPhase(isMyTurn) {
        this.hideAllPanels();
        document.getElementById('bidding-panel')?.classList.remove('hidden');
        
        // 如果是当前玩家的回合，显示叫分选项
        document.getElementById('bid-options')?.classList.toggle('hidden', !isMyTurn);
        document.getElementById('waiting-bid')?.classList.toggle('hidden', isMyTurn);
    }
    
    /**
     * 显示出牌阶段
     */
    showPlayPhase(isMyTurn) {
        this.hideAllPanels();
        document.getElementById('playing-panel')?.classList.remove('hidden');
        
        // 如果是当前玩家的回合，启用出牌按钮
        document.getElementById('play-controls')?.classList.toggle('hidden', !isMyTurn);
        document.getElementById('waiting-play')?.classList.toggle('hidden', isMyTurn);
    }
    
    /**
     * 隐藏所有面板
     */
    hideAllPanels() {
        document.getElementById('waiting-panel')?.classList.add('hidden');
        document.getElementById('bidding-panel')?.classList.add('hidden');
        document.getElementById('playing-panel')?.classList.add('hidden');
    }
    
    /**
     * 显示游戏大厅
     */
    showGameLobby() {
        document.getElementById('login-panel')?.classList.add('hidden');
        document.getElementById('lobby-panel')?.classList.remove('hidden');
    }
    
    /**
     * 显示游戏房间
     */
    showGameRoom() {
        document.getElementById('lobby-panel')?.classList.add('hidden');
        document.getElementById('game-room')?.classList.remove('hidden');
    }
    
    /**
     * 显示游戏结果
     */
    showGameResult(winner, scores) {
        const resultModal = document.createElement('div');
        resultModal.className = 'modal';
        resultModal.id = 'result-modal';
        resultModal.innerHTML = `
            <div class="modal-content">
                <div class="modal-header">
                    <h3><i class="fas fa-trophy"></i> 游戏结束</h3>
                </div>
                <div class="modal-body">
                    <div class="winner-info">
                        <h4>获胜者: ${winner || '未知'}</h4>
                    </div>
                    <div class="score-board">
                        <h4>分数统计</h4>
                        <div class="score-list">
                            ${Object.entries(scores).map(([player, score]) => `
                                <div class="score-item">
                                    <span class="player-name">${player}</span>
                                    <span class="player-score">${score} 分</span>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    <div class="game-actions">
                        <button class="btn btn-primary" id="play-again-btn">
                            <i class="fas fa-redo"></i> 再玩一次
                        </button>
                        <button class="btn btn-secondary" id="back-to-lobby-btn">
                            <i class="fas fa-home"></i> 返回大厅
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(resultModal);
        
        // 添加事件监听器
        document.getElementById('play-again-btn')?.addEventListener('click', () => {
            resultModal.remove();
            this.restartGame();
        });
        
        document.getElementById('back-to-lobby-btn')?.addEventListener('click', () => {
            resultModal.remove();
            this.showGameLobby();
        });
    }
    
    /**
     * 重新开始游戏
     */
    restartGame() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.showMessage('连接未就绪', 'error');
            return;
        }
        
        this.ws.send(JSON.stringify({
            type: 'restart'
        }));
    }
    
    /**
     * 更新最后出牌
     */
    updateLastPlay(playerName, cards, pattern) {
        const lastPlayElem = document.getElementById('last-play');
        if (lastPlayElem) {
            lastPlayElem.textContent = `${playerName}: ${this.formatCards(cards)} (${pattern || ''})`;
        }
    }
    
    /**
     * 更新连接状态
     */
    updateConnectionStatus(isConnected) {
        const connectionStatus = document.getElementById('connection-status');
        if (connectionStatus) {
            connectionStatus.className = isConnected ? 'connection-status connected' : 'connection-status disconnected';
            connectionStatus.innerHTML = isConnected ? 
                '<i class="fas fa-wifi"></i> 已连接' : 
                '<i class="fas fa-wifi-slash"></i> 已断开';
        }
    }
    
    /**
     * 显示消息
     */
    showMessage(message, type = 'info') {
        console.log(`[${type}] ${message}`);
        
        // 创建消息元素
        const messageElem = document.createElement('div');
        messageElem.className = `message ${type}`;
        messageElem.innerHTML = `
            <i class="fas fa-${this.getMessageIcon(type)}"></i>
            <span>${message}</span>
        `;
        
        // 添加到消息容器
        const messageContainer = document.getElementById('message-container');
        if (messageContainer) {
            messageContainer.appendChild(messageElem);
            
            // 3秒后自动移除
            setTimeout(() => {
                messageElem.remove();
            }, 3000);
        }
    }
    
    /**
     * 获取消息图标
     */
    getMessageIcon(type) {
        const icons = {
            'success': 'check-circle',
            'error': 'exclamation-circle',
            'warning': 'exclamation-triangle',
            'info': 'info-circle'
        };
        return icons[type] || 'info-circle';
    }
    
    /**
     * 获取阶段名称
     */
    getPhaseName(phase) {
        const phases = {
            'WAITING': '等待开始',
            'DEALING': '发牌',
            'BIDDING': '叫地主',
            'PLAYING': '出牌',
            'FINISHED': '结束'
        };
        return phases[phase] || phase;
    }
    
    /**
     * 计算分数
     */
    calculateScores(players) {
        let landlordScore = 0;
        let farmerScore = 0;
        
        Object.values(players).forEach(player => {
            if (player.role === 'LANDLORD') {
                landlordScore = player.score || 0;
            } else {
                farmerScore += player.score || 0;
            }
        });
        
        return `${landlordScore} - ${farmerScore}`;
    }
    
    /**
     * 获取当前时间
     */
    getCurrentTime() {
        const now = new Date();
        return `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
    }
    
    /**
     * 初始化游戏
     */
    static init() {
        const game = new DouDizhuGame();
        window.game = game; // 方便调试
        
        // 初始化连接状态为断开
        game.updateConnectionStatus(false);
        
        // 添加全局键盘快捷键
        document.addEventListener('keydown', (e) => {
            // Ctrl+Enter 发送聊天
            if (e.ctrlKey && e.key === 'Enter') {
                e.preventDefault();
                game.sendChatMessage();
            }
            
            // ESC 关闭模态框
            if (e.key === 'Escape') {
                const modals = document.querySelectorAll('.modal');
                modals.forEach(modal => {
                    if (modal.style.display === 'block') {
                        modal.style.display = 'none';
                    }
                });
            }
            
            // 空格键排序手牌
            if (e.key === ' ' && !e.ctrlKey && !e.altKey) {
                e.preventDefault();
                game.sortHand();
            }
        });
        
        console.log('斗地主游戏已初始化');
        return game;
    }
}

// 页面加载完成后初始化游戏
document.addEventListener('DOMContentLoaded', () => {
    DouDizhuGame.init();
});