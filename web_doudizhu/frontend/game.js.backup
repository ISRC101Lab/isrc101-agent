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
        this.cardImages['BJ'] = 'BJ'; // 大王
        this.cardImages['RJ'] = 'RJ'; // 小王
    }
    
    /**
     * 连接到游戏服务器
     */
    async connectToGame() {
        const playerName = document.getElementById('player-name')?.value?.trim() || 'Player';
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