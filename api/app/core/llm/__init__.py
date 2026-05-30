"""LLM provider 适配层。

四个 provider（openai/qwen/doubao/deepseek）均兼容 OpenAI 接口，
差异主要在 base_url 与默认模型，连接测试统一走 OpenAI 兼容协议。
"""
