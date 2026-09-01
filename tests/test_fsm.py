import threading
import time
from enum import Enum
import pytest
from simple_sm import StateMachine, transition, MachineError, step


class DummyState(Enum):
    READY = 1
    STAGING = 2
    SERVOING = 3
    COMPLETED = 4


class DummyController:
    def __init__(self):
        self.machine = StateMachine(states=DummyState, initial=DummyState.READY, model=self)
        self.log = []

    @transition(source=DummyState.READY, dest=DummyState.STAGING)
    def configure(self, param: str):
        self.log.append(f"configured_{param}")

    @transition(source=DummyState.STAGING, dest=DummyState.SERVOING)
    def start_servo(self):
        self.log.append("servo_started")

    @transition(source=DummyState.SERVOING, dest=DummyState.COMPLETED)
    def finish(self):
        self.log.append("finished")

    @transition(source=DummyState.STAGING, dest=DummyState.READY)
    def abort(self):
        self.log.append("aborted")

    @transition(source="*", dest=DummyState.READY, trigger="reset")
    def force_reset(self):
        self.log.append("reset")

    @transition(source=[DummyState.STAGING, DummyState.SERVOING], dest=DummyState.COMPLETED, trigger="emergency_stop")
    def stop(self):
        self.log.append("stopped")

    @transition(source=DummyState.READY, dest=DummyState.STAGING)
    def fail_transition(self):
        self.log.append("will_fail")
        raise RuntimeError("simulated_error")


def test_basic_transitions():
    ctrl = DummyController()
    assert ctrl.machine.state == DummyState.READY

    # Trigger first transition
    ctrl.configure("test")
    assert ctrl.machine.state == DummyState.STAGING
    assert ctrl.log == ["configured_test"]

    # Trigger second transition
    ctrl.start_servo()
    assert ctrl.machine.state == DummyState.SERVOING
    assert ctrl.log == ["configured_test", "servo_started"]

    # Trigger third transition
    ctrl.finish()
    assert ctrl.machine.state == DummyState.COMPLETED
    assert ctrl.log == ["configured_test", "servo_started", "finished"]


def test_invalid_transition_throws_machine_error():
    ctrl = DummyController()
    assert ctrl.machine.state == DummyState.READY

    with pytest.raises(MachineError) as exc_info:
        ctrl.start_servo()
    assert "Can't trigger transition 'start_servo' from state 'READY'!" in str(exc_info.value)
    assert ctrl.machine.state == DummyState.READY


def test_exception_prevents_state_transition():
    ctrl = DummyController()
    assert ctrl.machine.state == DummyState.READY

    with pytest.raises(RuntimeError) as exc_info:
        ctrl.fail_transition()
    assert "simulated_error" in str(exc_info.value)
    # The state should NOT have transitioned because the method threw an error!
    assert ctrl.machine.state == DummyState.READY
    assert ctrl.log == ["will_fail"]


def test_wildcard_source():
    ctrl = DummyController()
    assert ctrl.machine.state == DummyState.READY

    # Transition to staging
    ctrl.configure("wildcard")
    assert ctrl.machine.state == DummyState.STAGING

    # Reset from staging
    ctrl.force_reset()
    assert ctrl.machine.state == DummyState.READY
    assert ctrl.log == ["configured_wildcard", "reset"]


def test_list_of_sources():
    ctrl = DummyController()
    ctrl.configure("list")
    assert ctrl.machine.state == DummyState.STAGING

    # Stop from staging (which is in allowed list)
    ctrl.stop()
    assert ctrl.machine.state == DummyState.COMPLETED
    assert ctrl.log == ["configured_list", "stopped"]


def test_mermaid_generation():
    ctrl = DummyController()
    mermaid = ctrl.machine.to_mermaid()
    assert "stateDiagram-v2" in mermaid
    assert "READY --> STAGING : configure" in mermaid
    assert "STAGING --> SERVOING : start_servo" in mermaid
    assert "SERVOING --> COMPLETED : finish" in mermaid
    assert "STAGING --> READY : abort" in mermaid


def test_png_rendering():
    ctrl = DummyController()
    png_bytes = ctrl.machine.draw(None)
    assert isinstance(png_bytes, bytes)
    assert png_bytes.startswith(b"\x89PNG")



def test_thread_safety():
    ctrl = DummyController()
    errors = []

    def run_worker():
        try:
            # Each worker attempts to transition to STAGING
            # Only one should succeed, others must raise MachineError
            ctrl.configure("thread")
        except MachineError:
            pass
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=run_worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert ctrl.machine.state == DummyState.STAGING


class CustomStepError(Exception):
    pass


class StepController:
    def __init__(self):
        self.machine = StateMachine(states=DummyState, initial=DummyState.READY, model=self)
        self.counter = 0
        self.log = []

    @transition(source=DummyState.READY, dest=DummyState.STAGING)
    def start(self):
        self.log.append("started")

    @transition(source=DummyState.STAGING, dest=DummyState.SERVOING)
    def proceed(self):
        self.log.append("proceeded")

    @step(DummyState.STAGING)
    def step_staging(self):
        self.counter += 1
        if self.counter >= 3:
            self.proceed()

    @step(DummyState.SERVOING)
    def step_servoing(self):
        raise CustomStepError("custom_step_error")


def test_stepping():
    ctrl = StepController()
    assert ctrl.machine.state == DummyState.READY

    # Safe to call step on READY (no-op because no step function is registered)
    res = ctrl.machine.step()
    assert res == []
    assert ctrl.machine.state == DummyState.READY

    # Trigger transition to STAGING
    ctrl.start()
    assert ctrl.machine.state == DummyState.STAGING

    # Step 1: counter goes to 1, state is still STAGING
    ctrl.machine.step()
    assert ctrl.counter == 1
    assert ctrl.machine.state == DummyState.STAGING

    # Step 2: counter goes to 2, state is still STAGING
    ctrl.machine.step()
    assert ctrl.counter == 2
    assert ctrl.machine.state == DummyState.STAGING

    # Step 3: counter goes to 3, triggers proceed() inside step_staging()!
    # State transitions to SERVOING
    ctrl.machine.step()
    assert ctrl.counter == 3
    assert ctrl.machine.state == DummyState.SERVOING
    assert ctrl.log == ["started", "proceeded"]

    # Step 4: state is SERVOING, step_servoing() runs and raises CustomStepError!
    with pytest.raises(CustomStepError) as exc_info:
        ctrl.machine.step()
    assert "custom_step_error" in str(exc_info.value)

