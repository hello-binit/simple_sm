import os
import functools
import threading
from enum import Enum
from .renderer import StateMachineRenderer
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

S = TypeVar("S", bound=Enum)


class MachineError(Exception):
    """Exception raised when an invalid FSM transition is attempted."""

    pass


def transition(
    source: Any,
    dest: Any,
    trigger: Optional[str] = None,
) -> Callable[..., Any]:
    """Decorator to declare a state machine transition on a method.

    The decorated method executes as the transition body, and the state
    transition is completed upon successful execution.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        # Track transitions attached to this method
        if not hasattr(func, "_fsm_transitions"):
            func._fsm_transitions = []  # type: ignore

        trig_name = trigger or func.__name__
        func._fsm_transitions.append(  # type: ignore
            {"source": source, "dest": dest, "trigger": trig_name}
        )

        @functools.wraps(func)
        def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            # Locate the StateMachine instance on the host object
            machine = getattr(self, "machine", None)
            if not machine:
                # Search attributes of 'self' for an instance of StateMachine
                for attr_val in self.__dict__.values():
                    if isinstance(attr_val, StateMachine):
                        machine = attr_val
                        break

            if not machine:
                raise RuntimeError(
                    "No StateMachine instance found on this object. "
                    "Please assign `self.machine = StateMachine(...)` in your __init__."
                )

            current_state = machine.state
            matching_transition = None

            # Retrieve transitions from wrapper metadata
            transitions_list = getattr(wrapper, "_fsm_transitions", [])
            for t in transitions_list:
                # Check if current state matches source
                src = t["source"]
                allowed_sources = []
                if src == "*":
                    allowed_sources = list(machine._states_enum)
                elif isinstance(src, list):
                    allowed_sources = src
                else:
                    allowed_sources = [src]

                if current_state in allowed_sources:
                    matching_transition = t
                    break

            if not matching_transition:
                raise MachineError(
                    f"Can't trigger transition '{trig_name}' from state '{current_state.name}'!"
                )

            # Execute the method body
            res = func(self, *args, **kwargs)

            # Perform the transition
            machine.set_state(matching_transition["dest"])
            machine._last_transition = {
                "trigger": matching_transition["trigger"],
                "source": current_state,
                "dest": matching_transition["dest"],
            }

            return res

        # Propagate transition metadata to the wrapper for discovery
        wrapper._fsm_transitions = func._fsm_transitions  # type: ignore
        return wrapper

    return decorator


def step(state: Any) -> Callable[..., Any]:
    """Decorator to declare a state machine step method for a specific state or states.

    The decorated method is automatically executed once per `machine.step()` call
    when the state machine is in the matching state.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func._fsm_step_state = state  # type: ignore
        return func

    return decorator


class StateMachine(Generic[S]):
    """A clean, lightweight, type-safe, and thread-safe Finite State Machine.
    """

    def __init__(
        self,
        states: Type[S],
        initial: Optional[S] = None,
        **kwargs: Any,
    ):
        self._states_enum = states
        self._state = initial if initial is not None else list(states)[0]

        # A reentrant lock is critical for safe transitions in multi-threaded ROS 2 nodes
        self._lock = threading.RLock()

        # Internal model representation
        self._model = kwargs.get("model")

        # Transition map: trigger_name -> source_state -> destination_state
        self._transitions: Dict[str, Dict[S, S]] = {}
        self._last_transition: Optional[Dict[str, Any]] = None

        # Step handler map: state -> list of callbacks (supports multiple, like a catch-all)
        self._step_handlers: Dict[S, List[Callable[..., Any]]] = {
            state: [] for state in list(states)
        }

        # Auto-discover decorator-based transitions and step loops on model
        if self._model:
            self._discover_decorators()

        # setup renderer
        self.renderer = StateMachineRenderer(self)

    @property
    def state(self) -> S:
        """Returns the current state in a thread-safe manner."""
        with self._lock:
            return self._state

    def set_state(self, new_state: Union[S, str]) -> None:
        """Forcibly overrides the current state, thread-safely."""
        with self._lock:
            if isinstance(new_state, str):
                for val in self._states_enum:
                    if val.name == new_state:
                        self._state = val
                        return
                raise ValueError(
                    f"'{new_state}' is not a valid state name for {self._states_enum.__name__}"
                )
            elif isinstance(new_state, self._states_enum):
                self._state = new_state
            else:
                raise ValueError(
                    f"State must be a string or instance of {self._states_enum.__name__}"
                )

    def add_transition(
        self,
        trigger: str,
        source: Union[S, List[S], str],
        dest: S,
    ) -> None:
        """Registers a transition trigger with its source states and destination."""
        with self._lock:
            sources: List[S] = []
            if source == "*":
                sources = list(self._states_enum)
            elif isinstance(source, list):
                sources = source
            else:
                sources = [source]

            if trigger not in self._transitions:
                self._transitions[trigger] = {}

            for src in sources:
                self._transitions[trigger][src] = dest

    def step(self, *args: Any, **kwargs: Any) -> List[Any]:
        """Executes all registered step methods corresponding to the current state once."""
        with self._lock:
            current = self._state
            handlers = list(self._step_handlers.get(current, []))

        results = []
        for handler in handlers:
            # Executed outside the lock to allow nested triggers and non-blocking operation
            results.append(handler(*args, **kwargs))
        return results

    def _discover_decorators(self) -> None:
        """Inspects the model instance to discover decorated transition and step methods."""
        for name in dir(self._model):
            try:
                attr = getattr(self._model, name, None)
            except Exception:
                continue

            if attr:
                # 1. Discover transitions
                if hasattr(attr, "_fsm_transitions"):
                    for t in attr._fsm_transitions:
                        self.add_transition(
                            trigger=t["trigger"],
                            source=t["source"],
                            dest=t["dest"],
                        )
                # 2. Discover step handlers
                if hasattr(attr, "_fsm_step_state"):
                    states = attr._fsm_step_state
                    allowed_states = []
                    if states == "*":
                        allowed_states = list(self._states_enum)
                    elif isinstance(states, list):
                        allowed_states = states
                    else:
                        allowed_states = [states]

                    for s in allowed_states:
                        if s not in self._step_handlers:
                            self._step_handlers[s] = []
                        self._step_handlers[s].append(attr)

    def draw(self, path: Optional[str], format: str = "png") -> bytes:
        """Renders the state machine graph to PNG/JPEG bytes."""

        img = self.renderer.render()

        if path:
            # Ensure the directory exists
            dirname = os.path.dirname(path) if path else ""
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname, exist_ok=True)
            img.save(path, format=format)

        import io
        buf = io.BytesIO()
        img.save(buf, format=format)
        return buf.getvalue()

    def to_mermaid(self) -> str:
        """Compiles the state machine into Mermaid.js format for clean markdown rendering."""
        lines = ["stateDiagram-v2"]
        current = self.state
        lines.append(f"    [*] --> {current.name} : start")

        for trigger, sources in self._transitions.items():
            for src, dest in sources.items():
                lines.append(f"    {src.name} --> {dest.name} : {trigger}")

        return "\n".join(lines)
