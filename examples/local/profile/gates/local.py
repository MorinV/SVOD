"""The installed generic implementation; this profile only opts in."""
from svod.local_workflow import CurrentProcessGate

GATES = {CurrentProcessGate.name: CurrentProcessGate}
