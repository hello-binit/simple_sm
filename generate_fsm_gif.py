import sys
import os
import time
from enum import Enum

# Insert simple_sm path so we use local package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

from simple_sm import StateMachine, transition, step, MachineError
from simple_sm.renderer import StateMachineRenderer


class AutodockState(Enum):
    READY = 1
    STAGING = 2
    STAGING_AND_SCANNING = 3
    SERVOING = 4
    BLIND_DOCKING = 5
    COMPLETED = 6


class DockRobotAction:
    def __init__(self, do_work=0.0):
        # Initialize StateMachine, binding 'self' as the model
        self.machine = StateMachine(
            states=AutodockState,
            initial=AutodockState.READY,
            model=self
        )
        self.do_work = do_work
        self.frames = []
        
        # Capture initial state frame
        self.capture_frame()

    def capture_frame(self):
        """Renders the current FSM state using our Pillow visualizer and saves it."""
        renderer = StateMachineRenderer(self.machine)
        img = renderer.render()
        self.frames.append(img)

    # --- Transitions ---
    @transition(source=AutodockState.READY, dest=AutodockState.STAGING)
    def start_navigating(self, goal: str):
        print(f"[Transition] Setting up navigation to: {goal}")
        self.capture_frame()

    @transition(source=AutodockState.READY, dest=AutodockState.SERVOING)
    def skip_to_servoing(self):
        print("[Transition] Skipping staging, resetting servo control.")
        self.capture_frame()

    @transition(source=AutodockState.STAGING, dest=AutodockState.STAGING_AND_SCANNING)
    def start_scanning(self):
        print("[Transition] Arrived near staging area, starting scan.")
        self.capture_frame()

    @transition(source=AutodockState.STAGING_AND_SCANNING, dest=AutodockState.SERVOING)
    def dock_found(self):
        print("[Transition] Dock detected! Starting servo control.")
        self.capture_frame()

    @transition(source=AutodockState.SERVOING, dest=AutodockState.BLIND_DOCKING)
    def se2_servo_done(self):
        print("[Transition] SE2 PID servo control done. Initiating blind docking.")
        self.capture_frame()

    @transition(source=AutodockState.BLIND_DOCKING, dest=AutodockState.COMPLETED)
    def bd_done(self):
        print("[Transition] Charging contacts established.")
        self.capture_frame()

    # --- Step Functions ---
    @step(AutodockState.STAGING)
    def step_staging(self):
        print("[Step] In staging state...")
        self.start_scanning()

    @step(AutodockState.STAGING_AND_SCANNING)
    def step_scanning(self):
        print("[Step] Scanning for dock...")
        self.dock_found()

    @step(AutodockState.SERVOING)
    def step_servoing(self):
        print("[Step] Servoing PID active...")
        self.se2_servo_done()

    @step(AutodockState.BLIND_DOCKING)
    def step_blind_docking(self):
        print("[Step] Running blind docking drive...")
        self.bd_done()

    # --- Catch-All Step Function ---
    @step("*")
    def simulate_work(self):
        print(f"[Catch-All Step] Simulating work in {self.machine.state.name}...")
        # Capture frame during the step work
        self.capture_frame()
        if self.do_work > 0:
            time.sleep(self.do_work)

    # --- Execution Loop ---
    def execute_docking(self, goal_pose: str, navigate: bool):
        print(f"\n--- Starting Autodock Sequence (navigate={navigate}) ---")
        
        try:
            if navigate:
                self.start_navigating(goal_pose)
                
                # Step through each of the states sequentially
                while self.machine.state != AutodockState.COMPLETED:
                    self.machine.step()
                    self.capture_frame()
            else:
                self.skip_to_servoing()
                while self.machine.state != AutodockState.COMPLETED:
                    self.machine.step()
                    self.capture_frame()

            print("Successfully docked!")

        except MachineError as e:
            print(f"Transition Blocked: {e}")
        finally:
            # Reached end, capture one final frame
            self.capture_frame()


def main():
    # Each step sleeps 0.1s
    action = DockRobotAction(do_work=0.1)
    
    # Run full trajectory (navigate=True)
    action.execute_docking("kitchen_dock", navigate=True)
    
    # Save animated GIF
    os.makedirs("imgs", exist_ok=True)
    gif_path = "imgs/fsm_traversal.gif"
    
    # Save the sequence of frames as an animated GIF
    if action.frames:
        action.frames[0].save(
            gif_path,
            save_all=True,
            append_images=action.frames[1:],
            duration=800,  # 800ms per frame
            loop=0
        )
        print(f"\nAnimated GIF successfully saved to: {os.path.abspath(gif_path)}")


if __name__ == "__main__":
    main()
