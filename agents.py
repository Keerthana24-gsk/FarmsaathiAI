"""Small, explicit agent modules for FarmSaathi's deterministic advisory workflow.
Each agent owns one analysis responsibility and returns a structured result.
These are local rule/ML agents, not autonomous LLM agents.
"""
from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class AgentResult:
    name: str
    status: str
    summary: str
    data: Any = None

class BaseAgent:
    name = "Agent"
    def __init__(self, task: Callable[[], Any], summary: Callable[[Any], str]):
        self.task, self.summary = task, summary
    def run(self):
        value = self.task()
        return AgentResult(self.name, "completed", self.summary(value), value)

class CropPlanningAgent(BaseAgent): name = "Crop Planning Agent"
class WeatherIntelligenceAgent(BaseAgent): name = "Weather Intelligence Agent"
class IrrigationAgent(BaseAgent): name = "Irrigation Agent"
class SoilFertilizerAgent(BaseAgent): name = "Soil & Fertilizer Agent"
class CropHealthAgent(BaseAgent): name = "Crop Health Agent"
class ProfitabilityAgent(BaseAgent): name = "Profitability Agent"
class MultilingualAgent(BaseAgent): name = "Multilingual Communication Agent"

class MasterCoordinatorAgent:
    """Runs specialist agents in sequence and produces a single auditable trace."""
    name = "Master Coordinator Agent"
    def coordinate(self, agents, language):
        results = [agent.run() for agent in agents]
        return {
            "coordinator": self.name,
            "language": language,
            "agents_completed": len(results),
            "agents": [{"name": r.name, "status": r.status, "summary": r.summary} for r in results],
            "decision": "Specialist outputs combined into one farm advisory."
        }
