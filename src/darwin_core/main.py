from __future__ import annotations

import argparse

from dotenv import load_dotenv

from darwin_core.services.llm.openrouter import OpenRouterService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query OpenRouter from CLI.")
    parser.add_argument("prompt", help="User prompt sent to the model.")
    parser.add_argument(
        "--system",
        dest="system_prompt",
        default=None,
        help="Optional system prompt.",
    )
    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    service = OpenRouterService()
    result = service.chat(args.prompt, system_prompt=args.system_prompt)
    print(result)


if __name__ == "__main__":
    main()

