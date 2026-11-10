import pytest

from rpaoias.examples import example_source
from rpaoias.web.model import Session


def test_run_to_halt_executes_cpu_and_retains_every_assignment_step():
    session = Session()
    session.assemble(example_source("dot_product"))

    session.run_to_halt()

    state = session.state()
    assert state["cpu"]["halted"] is True
    assert state["cpu"]["steps"] == 141
    assert state["result"]["value"] == 2_947_418_113
    assert len(state["history"]) == 141
    assert state["history"][-1]["instruction"]["asm"] == "HALT"


def test_run_to_halt_limit_keeps_real_partial_execution_and_history():
    session = Session()

    with pytest.raises(ValueError, match="предел 1 инструкций"):
        session.run_to_halt(limit=1)

    state = session.state()
    assert state["cpu"]["steps"] == 1
    assert state["cpu"]["halted"] is False
    assert len(state["history"]) == 1
