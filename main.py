from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import load_dotenv

from app.nl.assistant import ask_bgp_question, create_bgp_chat_agent
from app.models.device import DeviceConfig
from app.parsers.cisco_ios_myversion import parse_bgp, parse_hostname, parse_interfaces


def print_banner() -> None:
    print(
        r"""
============================================================
 AI Config Validator Chat
 Ask questions about one or more parsed Cisco configs.
============================================================
"""
    )


def print_llm_error(error: Exception) -> None:
    print("Could not talk to the LLM.")
    print("Check your internet connection and OPENAI_API_KEY in your .env file.")
    print(f"Details: {error}")


def load_config_files(config_paths: list[str]) -> list[dict]:
    loaded_devices = []

    for config_path in config_paths:
        path = Path(config_path)
        config_text = path.read_text()
        device = DeviceConfig(
            hostname=parse_hostname(config_text),
            interfaces=parse_interfaces(config_text),
            bgp_processes=parse_bgp(config_text),
        )
        loaded_devices.append(
            {
                "source": str(path),
                "config": device,
            }
        )

    return loaded_devices


def print_loaded_configs(loaded_devices: list[dict]) -> None:
    print("Loaded configs:")

    for index, loaded in enumerate(loaded_devices, start=1):
        device = loaded["config"]
        hostname = device.hostname or "unknown-hostname"
        neighbor_count = len(device.all_bgp_neighbors())
        interface_count = len(device.interfaces)
        print(
            f"  {index}. {hostname} | {loaded['source']} | "
            f"{neighbor_count} BGP neighbors | {interface_count} L3 interfaces"
        )


def run_chat(loaded_devices: list[dict]) -> None:
    agent = create_bgp_chat_agent(loaded_devices)
    messages = []

    print()
    print("Chat ready. Type 'exit' or 'quit' to stop.")
    print("Tip: ask things like 'which config has Telstra BGP?' or 'compare BGP neighbors'.")

    while True:
        try:
            question = input("\nyou> ").strip()
        except EOFError:
            print()
            break

        if not question:
            continue

        if question.lower() in {"exit", "quit"}:
            break

        try:
            result = agent.invoke(
                {
                    "messages": [
                        *messages,
                        {"role": "user", "content": question},
                    ]
                }
            )
        except Exception as error:
            print_llm_error(error)
            continue

        messages = result["messages"]
        print(f"assistant> {messages[-1].content}")


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Ask BGP questions about a Cisco IOS config.")
    parser.add_argument(
        "question",
        nargs="?",
        default=None,
        help="Question to ask the BGP assistant.",
    )
    parser.add_argument(
        "--chat",
        action="store_true",
        help="Start an interactive BGP assistant chat.",
    )
    parser.add_argument(
        "--config",
        nargs="+",
        default=[
            "app/config_files/iosxe-rtr01-full.txt",
            "app/config_files/iosxe-rtr02-full.txt",
        ],
        help="Path to one or more Cisco IOS show running-config files.",
    )
    args = parser.parse_args()

    loaded_devices = load_config_files(args.config)
    print_banner()
    print_loaded_configs(loaded_devices)

    if args.chat or args.question is None:
        run_chat(loaded_devices)
        return

    try:
        answer = ask_bgp_question(loaded_devices, args.question)
    except Exception as error:
        print_llm_error(error)
        return

    print(answer)


if __name__ == "__main__":
    main()
