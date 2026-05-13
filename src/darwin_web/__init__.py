"""Isolated web navigation agent with LLM-guided exploration and YAML recipe replay."""

from darwin_web.executor import execute_recipe_yaml, replay_playbook, replay_step
from darwin_web.playbook import Playbook, PlaybookStep

__all__ = [
    "__version__",
    "Playbook",
    "PlaybookStep",
    "execute_recipe_yaml",
    "replay_playbook",
    "replay_step",
]

__version__ = "0.1.0"
