import json

from agents import Agent, Runner

from .config import get_settings
from .schemas import WorkflowPlan


PLANNER_INSTRUCTIONS = """You are AURA's planning agent. Convert a business outcome into a finite,
auditable workflow using only tools listed by the caller. Never claim a tool is connected unless it
appears in the inventory. Reads are non-consequential. Sending, creating, updating, deleting,
posting, scheduling, or purchasing is consequential and must be marked consequential=true.
Arguments must contain concrete resource identifiers and payloads; if required information is
missing, create a non-consequential clarification step using tool_slug='human'."""


SPECIALISTS = {
    "data": Agent(name="Data specialist", instructions="Design exact read/transform steps. Never invent source records."),
    "communications": Agent(name="Communications specialist", instructions="Prepare precise messages and recipients. Sending is always consequential."),
    "operations": Agent(name="Operations specialist", instructions="Design deterministic cross-system operations with idempotent writes."),
    "risk": Agent(name="Risk specialist", instructions="Identify consequential actions, excessive permissions, missing identifiers, and unsafe assumptions."),
}


def build_orchestrator() -> Agent:
    tools = [agent.as_tool(tool_name=f"ask_{name}_specialist", tool_description=agent.instructions or "") for name, agent in SPECIALISTS.items()]
    return Agent(
        name="AURA orchestrator",
        model=get_settings().openai_model,
        instructions=PLANNER_INSTRUCTIONS,
        tools=tools,
        output_type=WorkflowPlan,
    )


async def create_plan(prompt: str, tool_inventory: list[dict]) -> WorkflowPlan:
    orchestrator = build_orchestrator()
    input_text = f"User outcome:\n{prompt}\n\nExecutable tool inventory:\n{json.dumps(tool_inventory, indent=2)}"
    result = await Runner.run(orchestrator, input_text, max_turns=12)
    if not isinstance(result.final_output, WorkflowPlan):
        return WorkflowPlan.model_validate(result.final_output)
    return result.final_output

