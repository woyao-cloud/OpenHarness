"""CLI entry point: python -m mini_src "your prompt"

Environment variables:
  ANTHROPIC_API_KEY  — API key for Anthropic (default provider)
  OPENAI_API_KEY     — API key for OpenAI-compatible providers
  DEEPSEEK_API_KEY   — API key for DeepSeek (auto-configures base URL & model)
  OPENHARNESS_MODEL  — Model name (default: claude-sonnet-4-6)
  OPENHARNESS_BASE_URL — Custom API base URL (optional)
  OPENHARNESS_MAX_TOKENS — Max tokens per request (default: 4096)
  OPENHARNESS_MAX_TURNS — Max agentic turns (default: 200)

Examples:
  # Anthropic
  export ANTHROPIC_API_KEY=sk-ant-...
  python -m mini_src "hello"

  # DeepSeek V4 Flash / DeepSeek Chat
  export DEEPSEEK_API_KEY=sk-...
  export OPENHARNESS_MODEL=deepseek-chat
  python -m mini_src "hello"

  # OpenAI
  export OPENAI_API_KEY=sk-...
  python -m mini_src "hello"

  # Any OpenAI-compatible provider
  export OPENAI_API_KEY=...
  export OPENHARNESS_BASE_URL=https://your-proxy.com/v1
  export OPENHARNESS_MODEL=your-model
  python -m mini_src "hello"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from mini_src.api.client import AnthropicApiClient, OpenAICompatibleClient
from mini_src.config import get_api_key, get_api_provider, get_base_url, get_max_tokens, get_max_turns, get_model, get_provider_base_url
from mini_src.core.engine import QueryEngine
from mini_src.core.events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ErrorEvent,
    StatusEvent,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)
from mini_src.tools.base import ToolRegistry
from mini_src.tools.builtin import create_default_tool_registry

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful AI assistant with access to tools.
You can read and write files, execute shell commands, search code, and more.
Be concise and helpful. Use the tools available to you to accomplish tasks."""


def build_api_client():
    """Build the appropriate API client based on environment variables."""
    provider = get_api_provider()
    api_key = get_api_key(provider)
    if not api_key:
        print(f"Error: No API key found for provider '{provider}'.")
        print("Set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, DEEPSEEK_API_KEY")
        print("Or set OPENHARNESS_PROVIDER=openai with OPENAI_API_KEY=...")
        sys.exit(1)

    base_url = get_base_url()

    if provider in ("openai", "deepseek"):
        url = base_url or get_provider_base_url(provider)
        model = get_model()
        log.debug("Config: provider=%s model=%s base_url=%s max_tokens=%d max_turns=%d",
                   provider, model, url, get_max_tokens(), get_max_turns())
        return OpenAICompatibleClient(api_key, base_url=url)

    model = get_model()
    log.debug("Config: provider=%s model=%s base_url=%s max_tokens=%d max_turns=%d",
               provider, model, base_url or "default", get_max_tokens(), get_max_turns())
    return AnthropicApiClient(api_key, base_url=base_url)


async def run_interactive(engine: QueryEngine) -> None:
    """Run in interactive REPL mode."""
    print("Mini OpenHarness — type your prompt, or /quit to exit.")
    print()

    while True:
        try:
            prompt = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not prompt:
            continue
        if prompt == "/quit":
            break
        if prompt == "/clear":
            engine.clear()
            print("(conversation cleared)")
            continue

        await run_prompt(engine, prompt)


async def run_prompt(engine: QueryEngine, prompt: str) -> None:
    """Run a single prompt through the engine and display events."""
    async for event in engine.submit_message(prompt):
        if isinstance(event, AssistantTextDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, AssistantTurnComplete):
            print()
        elif isinstance(event, ToolExecutionStarted):
            print(f"\n  ▶ {event.tool_name}({event.tool_input})")
        elif isinstance(event, ToolExecutionCompleted):
            preview = event.output[:200].replace("\n", " ").strip()
            if event.is_error:
                print(f"  ✗ {preview}")
            else:
                print(f"  ✓ {preview}")
        elif isinstance(event, StatusEvent):
            print(f"\n  ℹ {event.message}")
        elif isinstance(event, ErrorEvent):
            print(f"\n  ✗ Error: {event.message}")
    print()


async def run_once(prompt: str) -> None:
    """Run a single prompt and exit."""
    api_client = build_api_client()
    model = get_model()

    registry = ToolRegistry()
    for tool in create_default_tool_registry():
        registry.register(tool)

    engine = QueryEngine(
        api_client=api_client,
        tool_registry=registry,
        cwd=Path.cwd(),
        model=model,
        system_prompt=SYSTEM_PROMPT,
        max_tokens=get_max_tokens(),
        max_turns=get_max_turns(),
    )
    log.debug("单次运行prompt: %s", prompt)
    await run_prompt(engine, prompt)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mini OpenHarness — minimal AI coding assistant")
    parser.add_argument("prompt", nargs="*", help="Prompt to run (omit for interactive mode)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.prompt:
        prompt = " ".join(args.prompt)
        asyncio.run(run_once(prompt))
    else:
        api_client = build_api_client()
        model = get_model()

        registry = ToolRegistry()
        for tool in create_default_tool_registry():
            registry.register(tool)

        engine = QueryEngine(
            api_client=api_client,
            tool_registry=registry,
            cwd=Path.cwd(),
            model=model,
            system_prompt=SYSTEM_PROMPT,
            max_tokens=get_max_tokens(),
            max_turns=get_max_turns(),
        )
        asyncio.run(run_interactive(engine))


if __name__ == "__main__":
    main()
