#!/usr/bin/env python3
"""检查配置文件和 API 密钥状态"""
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from isrc101_agent.config import Config

def check_config():
    """检查配置"""
    print("\n" + "=" * 60)
    print("  配置检查")
    print("=" * 60 + "\n")
    
    try:
        config = Config.load(".")
        
        print(f"✓ 配置文件加载成功")
        print(f"  源文件: {config._config_source}")
        print(f"  项目目录: {config.project_root}")
        print(f"  当前模型: {config.active_model}")
        print(f"  Web 开关: {'ON' if config.web_enabled else 'OFF'}")
        print(f"  Web 显示: {config.web_display}")
        print(f"  回答风格: {config.answer_style}")
        print(f"  已启用技能: {', '.join(config.enabled_skills) if config.enabled_skills else '(none)'}")
        print()
        
        # 检查模型配置
        print("模型配置:")
        print("-" * 60)
        
        for name, preset in config.models.items():
            key_status = "✓" if preset.resolve_api_key() else "✗"
            key_preview = "not set" if not preset.resolve_api_key() else f"{preset.resolve_api_key()[:8]}...{preset.resolve_api_key()[-4:]}"
            
            print(f"\n{name}:")
            print(f"  Provider: {preset.provider}")
            print(f"  Model: {preset.model}")
            print(f"  API Base: {preset.api_base}")
            print(f"  API Key: {key_status} {key_preview}")
            print(f"  Description: {preset.description}")
            
            if preset.provider == "deepseek" and not preset.resolve_api_key():
                print(f"  ⚠️  警告: DeepSeek 模型需要配置 API 密钥")
                print(f"      请设置环境变量: export DEEPSEEK_API_KEY='your-key'")
        
        print("\n" + "=" * 60)
        
        print("\n" + "=" * 60 + "\n")
        
    except Exception as e:
        print(f"✗ 配置检查失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(check_config())
