# =============================================================================
# brake_controller.py
# =============================================================================
# The main decision-making state machine for the airbrake system.
#
# WHAT THIS MODULE DOES:
#   This is the brain of the system. Every loop cycle it looks at the
#   current flight phase, the latest telemetry, and the ML prediction,
#   and decides what to do next. It issues a ControllerCommand that
#   main.py passes to the Actuator.
#
# THE STATE MACHINE:
#   The controller moves through these phases in order:
#
#   IDLE
#     └─ launch detected ──────────────────────────────► ASCENDING
#
#   ASCENDING  (motor burn lockout — brakes cannot deploy)
#     └─ burnout detected ─────────────────────────────► ARMED
#
#   ARMED  (prediction running, brakes may deploy)
#     ├─ predicted apogee > target ────────────────────► BRAKING
#     └─ retract condition met ────────────────────────► DESCENDING
#
#   BRAKING  (brakes deployed)
#     ├─ predicted apogee <= target ───────────────────► ARMED
#     └─ retract condition met ────────────────────────► DESCENDING
#
#   DESCENDING  (past apogee, brakes retracted)
#     └─ always stays here until shutdown ─────────────► SAFE
#
#   SAFE
#     └─ terminal state, everything off
#
# RETRACT CONDITIONS (checked in ARMED and BRAKING):
#   1. Vertical velocity has been negative for 3 uninterrupted seconds.
#      This means we are definitely past apogee and descending.
#   2. A sudden vertical velocity shift exceeding the threshold in one
#      cycle. This catches unexpected events (chute deployment, anomaly).
#
# DEPLOYMENT LOGIC:
#   Brakes deploy when:
#     - Phase is ARMED
#     - A valid ML prediction exists
#     - Predicted apogee > target apogee (we are going too high)
#
#   Brakes retract (back to ARMED) when:
#     - Phase is BRAKING
#     - Predicted apogee <= target apogee (correction achieved)
#     - AND no retract condition is active
#
#   This means the brakes can cycle open/closed multiple times during
#   ascent as the prediction updates. This is intentional — it allows
#   fine-grained altitude control rather than a single binary deploy.
#
# WHAT THIS MODULE DOES NOT DO:
#   - It does not read sensors directly.
#   - It does not move the motor directly.
#   - It does not write to the SD card.
#   Those responsibilities belong to SensorReader, Actuator, DataLogger.
# =============================================================================

from typing import Optional

from telemetry_types import (
    TelemetrySample,
    DerivedState,
    ControllerCommand,
    FlightPhase,
)
import config


class BrakeController:

    def __init__(self, target_apogee_ft: float):
        """
        Initialize the brake controller.

        Args:
            target_apogee_ft: Loaded from config.TARGET_APOGEE_FT.
                              This is the altitude we are trying to hit.
        """
        self.target_apogee_ft = target_apogee_ft

        # Current flight phase — starts IDLE, advances through the
        # state machine as the flight progresses.
        self.phase: str = FlightPhase.IDLE

        # --- Retract watchdog state ---
        # We track how long velocity has been continuously negative.
        # The timer resets to None any time velocity goes positive again.
        self._negative_velocity_start_s: Optional[float] = None

        # Previous vertical velocity — used to detect sudden shifts.
        self._prev_velocity_ft_s: Optional[float] = None

    # -------------------------------------------------------------------------
    # Public interface — called every loop cycle from main.py
    # -------------------------------------------------------------------------

    def update(
        self,
        sample: TelemetrySample,
        derived: Optional[DerivedState],
        launched: bool,
        burnt_out: bool,
    ) -> ControllerCommand:
        """
        Evaluate current flight state and return a ControllerCommand.

        This is called once per loop cycle. It advances the state machine
        if conditions are met, runs the retract watchdog, and returns
        a command telling main.py what to do this cycle.

        Args:
            sample:    Latest TelemetrySample from SensorReader.
            derived:   Latest DerivedState (may be None if buffer not
                       yet filled — typically only the first 1-2 cycles).
            launched:  True once LaunchDetector confirms launch.
            burnt_out: True once LaunchDetector confirms burnout.

        Returns:
            A ControllerCommand with deploy/retract/shutdown flags
            and the current flight phase.
        """

        # --- Advance state machine ---
        self._advance_phase(launched, burnt_out)

        # --- Run retract watchdog ---
        # This runs in ARMED and BRAKING phases only.
        # It monitors for the descent conditions that force retraction.
        retract_triggered = False
        if self.phase in (FlightPhase.ARMED, FlightPhase.BRAKING):
            if derived is not None:
                retract_triggered = self._check_retract_conditions(
                    sample=sample,
                    derived=derived
                )

        # --- Build command based on current phase ---

        if self.phase == FlightPhase.IDLE:
            return ControllerCommand(phase=FlightPhase.IDLE)

        elif self.phase == FlightPhase.ASCENDING:
            # Motor burn lockout — log only, no brake action.
            return ControllerCommand(phase=FlightPhase.ASCENDING)

        elif self.phase == FlightPhase.ARMED:
            if retract_triggered:
                # Watchdog fired — we are past apogee.
                self.phase = FlightPhase.DESCENDING
                return ControllerCommand(
                    retract=True,
                    phase=FlightPhase.DESCENDING
                )

            # Check whether to deploy brakes.
            if derived is not None and derived.predicted_apogee_ft is not None:
                if derived.predicted_apogee_ft > self.target_apogee_ft:
                    self.phase = FlightPhase.BRAKING
                    return ControllerCommand(
                        deploy=True,
                        phase=FlightPhase.BRAKING
                    )

            # No action needed this cycle.
            return ControllerCommand(phase=FlightPhase.ARMED)

        elif self.phase == FlightPhase.BRAKING:
            if retract_triggered:
                # Watchdog fired — retract and move to DESCENDING.
                self.phase = FlightPhase.DESCENDING
                return ControllerCommand(
                    retract=True,
                    phase=FlightPhase.DESCENDING
                )

            # Check whether the prediction says we can retract brakes.
            # If the predicted apogee has dropped to at or below target,
            # retract and return to ARMED so we can redeploy if needed.
            if derived is not None and derived.predicted_apogee_ft is not None:
                if derived.predicted_apogee_ft <= self.target_apogee_ft:
                    self.phase = FlightPhase.ARMED
                    return ControllerCommand(
                        retract=True,
                        phase=FlightPhase.ARMED
                    )

            # Brakes stay deployed this cycle.
            return ControllerCommand(phase=FlightPhase.BRAKING)

        elif self.phase == FlightPhase.DESCENDING:
            # Past apogee. Brakes are retracted. Just log.
            # Transition to SAFE is handled by shutdown logic in main.py
            # (e.g. after a set time, or when altitude drops near ground).
            return ControllerCommand(phase=FlightPhase.DESCENDING)

        elif self.phase == FlightPhase.SAFE:
            return ControllerCommand(
                shutdown=True,
                phase=FlightPhase.SAFE
            )

        # Fallback — should never reach here.
        return ControllerCommand(phase=self.phase)

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _advance_phase(self, launched: bool, burnt_out: bool) -> None:
        """
        Move the state machine forward based on LaunchDetector outputs.

        This only ever moves FORWARD through the phase sequence.
        Phases never go backward — once launched, we never return to IDLE.
        Once burnt out, we never return to ASCENDING.

        Args:
            launched:  LaunchDetector.launched property.
            burnt_out: LaunchDetector.burnt_out property.
        """
        if self.phase == FlightPhase.IDLE and launched:
            self.phase = FlightPhase.ASCENDING

        elif self.phase == FlightPhase.ASCENDING and burnt_out:
            self.phase = FlightPhase.ARMED
            # Reset watchdog state cleanly when entering ARMED.
            # Any velocity history from the burn phase is irrelevant.
            self._negative_velocity_start_s = None
            self._prev_velocity_ft_s = None

    def _check_retract_conditions(
        self,
        sample: TelemetrySample,
        derived: DerivedState,
    ) -> bool:
        """
        Check whether a retract condition has been triggered.

        Called every cycle while in ARMED or BRAKING phase.
        Returns True if brakes should be retracted immediately.

        TWO CONDITIONS — either one triggers retraction:

        CONDITION 1 — Sustained negative velocity (3 seconds):
          Vertical velocity has been negative (descending) without
          interruption for RETRACT_NEGATIVE_VELOCITY_DURATION_S.
          This is the primary post-apogee detection mechanism.

          HOW THE TIMER WORKS:
            - First cycle with negative velocity: timer starts.
            - Every subsequent cycle with negative velocity: timer runs.
            - Any cycle with positive velocity: timer resets to None.
            - Timer reaches threshold: retract triggered.

          WHY 3 SECONDS?
            Near apogee, vertical velocity naturally passes through zero
            and may briefly oscillate around it due to sensor noise. A
            3-second requirement ensures we are in genuine sustained
            descent before retracting, not reacting to a noise spike.

        CONDITION 2 — Sudden velocity shift:
          The absolute change in vertical velocity between the previous
          sample and this one exceeds RETRACT_SUDDEN_SHIFT_FT_S2.
          This catches unexpected events like parachute deployment,
          a structural anomaly, or a drogue firing.

          WHY THIS MATTERS:
            If a drogue chute deploys, velocity can change by hundreds
            of ft/s in a fraction of a second. We want the brakes
            retracted before that happens to avoid mechanical damage.

        Args:
            sample:  Latest TelemetrySample (for pi_time).
            derived: Latest DerivedState (for velocity).

        Returns:
            True if retraction should be triggered, False otherwise.
        """
        current_velocity = derived.avg_velocity_ft_s
        current_time = sample.pi_time

        # --- Condition 2: Sudden velocity shift ---
        # Check this first since it's instantaneous.
        if self._prev_velocity_ft_s is not None:
            velocity_shift = abs(current_velocity - self._prev_velocity_ft_s)
            if velocity_shift > config.RETRACT_SUDDEN_SHIFT_FT_S2:
                # Reset timer and prev velocity for a clean state
                self._negative_velocity_start_s = None
                self._prev_velocity_ft_s = current_velocity
                return True

        # --- Condition 1: Sustained negative velocity ---
        if current_velocity < 0.0:
            if self._negative_velocity_start_s is None:
                # Velocity just went negative — start the timer
                self._negative_velocity_start_s = current_time
            else:
                # Velocity is still negative — check elapsed time
                elapsed = current_time - self._negative_velocity_start_s
                if elapsed >= config.RETRACT_NEGATIVE_VELOCITY_DURATION_S:
                    self._prev_velocity_ft_s = current_velocity
                    return True
        else:
            # Velocity is positive — reset the negative velocity timer
            # Any interruption starts the 3-second count over.
            self._negative_velocity_start_s = None

        # Update previous velocity for next cycle's shift check
        self._prev_velocity_ft_s = current_velocity
        return False
