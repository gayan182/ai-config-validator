from langchain.agents import create_agent
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from app.langchain_tools.bgp_tools import (
    get_device_config,
    set_device,
    set_devices,
    validate_bgp_update_sources,
)
from app.models.device import DeviceConfig



SYSTEM_PROMPT = """
You are a BGP configuration assistant.
Answer only using the loaded parsed Cisco config data.
Use get_device_config when exact config facts are needed.
Reason over the returned parsed device models to answer questions.
When multiple configs are loaded, include the hostname or config source when it matters.
If the answer is not available, say you cannot determine it from the config.
If multiple neighbors look equally likely, say that and list the possible peer IPs.
Keep answers concise.
Use validate_bgp_update_sources when the user asks to validate, check, audit, or verify iBGP update-source configuration.
"""


def create_bgp_chat_agent(device: DeviceConfig | list[dict]) -> Runnable:
    """Create a BGP assistant agent for the loaded device config data."""
    if isinstance(device, list):
        set_devices(device)
    else:
        set_device(device)

    tools = [get_device_config, validate_bgp_update_sources]

    model = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
    )

    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
    )


def ask_bgp_question(device: DeviceConfig | list[dict], question: str) -> str:
    agent = create_bgp_chat_agent(device)

    result = agent.invoke(
        {
            "messages": [
                {"role": "user", "content": question},
            ]
        }
    )

    return str(result["messages"][-1].content)
