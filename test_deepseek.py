#!/usr/bin/env python3
"""测试 DeepSeek API 连接"""
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from isrc101_agent.llm import LLMAdapter
from isrc101_agent.config import Config

def test_deepseek(model_name: str, api_key: str = None):
    """测试 DeepSeek 模型"""
    print(f"\n{'=' * 60}")
    print(f"  测试 DeepSeek 模型: {model_name}")
    print('=' * 60 + "\n")
    
    # 清除环境变量，强制使用配置文件中的密钥
    os.environ.pop('DEEPSEEK_API_KEY', None)
    
    # 加载配置
    config = Config.load(".")
    preset = config.models.get(model_name)
    
    if not preset:
        print(f"✗ 错误: 模型 '{model_name}' 不存在")
        return False
    
    # 从配置中获取 API 密钥
    if api_key:
        os.environ['DEEPSEEK_API_KEY'] = api_key
        print(f"✓ API 密钥已设置: {api_key[:8]}...{api_key[-4:]}")
    else:
        # 从配置文件中获取密钥
        api_key = preset.resolve_api_key()
        if api_key:
            print(f"✓ API 密钥已从配置加载: {api_key[:8]}...{api_key[-4:]}")
        else:
            print("✗ 错误: 未找到 API 密钥")
            print("  请在 .agent.conf.yml 中配置 api-key")
            return False
    
    try:
        # preset 已经在上面获取了
        if not preset:
            print(f"✗ 错误: 模型 '{model_name}' 不存在")
            return False
        
        print(f"✓ 模型配置加载成功")
        print(f"  Provider: {preset.provider}")
        print(f"  Model: {preset.model}")
        print(f"  API Base: {preset.api_base}")
        
        # 创建 LLM 适配器
        llm = LLMAdapter(
            model=preset.model,
            temperature=preset.temperature,
            max_tokens=preset.max_tokens,
            api_base=preset.api_base
        )
        
        print(f"\n正在测试连接...")
        
        # 发送测试消息
        messages = [
            {"role": "system", "content": "你是一个有用的 AI 助手。"},
            {"role": "user", "content": "你好，请回复 'DeepSeek API 工作正常'"}
        ]
        
        response = llm.chat(messages=messages)
        
        if response.content:
            print(f"\n✓ 成功收到响应:")
            print(f"  {response.content}")
            
            if response.usage:
                print(f"\n  Token 使用:")
                print(f"    - Prompt: {response.usage.get('prompt_tokens', 0)}")
                print(f"    - Completion: {response.usage.get('completion_tokens', 0)}")
                print(f"    - Total: {response.usage.get('total_tokens', 0)}")
            
            print(f"\n{'=' * 60}")
            print(f"  ✅ DeepSeek {model_name} 测试通过！")
            print('=' * 60 + "\n")
            
            return True
        else:
            print(f"\n✗ 错误: 未收到响应内容")
            return False
            
    except Exception as e:
        error_msg = str(e)
        print(f"\n✗ 错误: {type(e).__name__}")
        print(f"  {error_msg}")
        
        # 提供详细的错误提示
        if "Authentication" in error_msg or "invalid" in error_msg.lower():
            print(f"\n  建议:")
            print(f"    1. 检查 API 密钥是否正确")
            print(f"    2. 确认 API 密钥是否有访问权限")
            print(f"    3. 检查 DeepSeek 服务是否正常")
        elif "Connection" in error_msg or "connect" in error_msg.lower():
            print(f"\n  建议:")
            print(f"    1. 检查网络连接")
            print(f"    2. 检查 API Base 地址是否正确")
            print(f"    3. 尝试使用代理")
        
        print(f"\n{'=' * 60}\n")
        return False


# Keep as manual integration script; avoid pytest auto-collect.
test_deepseek.__test__ = False

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='测试 DeepSeek API 连接')
    parser.add_argument('--model', '-m', default='deepseek-chat',
                       choices=['deepseek-chat', 'deepseek-reasoner'],
                       help='要测试的模型 (默认: deepseek-chat)')
    parser.add_argument('--api-key', '-k', default=None,
                       help='DeepSeek API 密钥 (可选，不指定则使用环境变量)')
    
    args = parser.parse_args()
    
    success = test_deepseek(args.model, args.api_key)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
