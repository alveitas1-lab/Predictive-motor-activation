# =============================================================================
# actuator.py
# =============================================================================
# Controls the stepper motor that deploys and retracts the airbrakes.
#
# WHAT THIS MODULE DOES:
#   1. Initializes the stepper driver GPIO pins at startup.
#   2. Provides deploy() and retract() methods that rotate the motor
#      exactly 90 degrees in the correct direction.
#   3. Tracks commanded position in ActuatorStatus.
#   4. Provides an emergency_retract() method that retracts regardless
#      of current state — used by the safety watchdog.
#
# HOW A STEPPER MOTOR WORKS (brief):
#   A stepper motor moves in discrete steps rather than spinning freely.
#   Each time you pulse the STEP pin, the motor advances one step.
#   The DIR pin controls which direction it steps.
#   The EN (enable) pin activates the driver — on most drivers (A4988,
#   DRV8825) pulling EN LOW enables the motor, HIGH disables it.
#
#   For a 200-step/rev motor:
#     Full revolution = 200 steps
#     90 degrees      = 200 / 4 = 50 steps
#
#   STEPPER_STEPS_FOR_90_DEG in config.py handles this automatically.
#
# IMPORTANT HARDWARE NOTE:
#   The stepper motor must NOT be powered from the Pico's 3.3V or 5V
#   pins. Use the PowerBoost 1000 output for motor power. The Pico
#   only provides signal-level GPIO — the driver board takes those
#   signals and switches the motor's higher-voltage supply.
#
# HOLDING TORQUE — CRITICAL FOR THIS DESIGN:
#   This system has no mechanical latch, detent, or spring to hold the
#   airbrake leaves in the retracted position. It relies entirely on
#   the motor's holding torque to keep the leaves closed against
#   aerodynamic pressure and vibration during flight.
#
#   A de-energized stepper only produces detent torque (~5-10% of full
#   holding torque) from its permanent magnets. This is NOT sufficient
#   to hold the leaves reliably in a high-G, high-vibration environment.
#
#   SOLUTION — Active holding:
#   After a retract move, the motor driver is kept ENABLED so the coils
#   remain energized and full holding torque is maintained.
#   After a deploy move, the driver is disabled since aerodynamic drag
#   assists in keeping the leaves open.
#
#   HEAT MANAGEMENT:
#   Holding the motor energized continuously draws current and generates
#   heat inside the avionics bay. If your driver supports it (DRV8825
#   recommended), set the current limit to ~60-70% of rated motor current
#   for holding. This is done via the driver's onboard trim potentiometer
#   — not in software. Full current is only needed during the actual move.
#
#   DRIVER RECOMMENDATION:
#   Use a DRV8825 over an A4988 for this application. The DRV8825 has
#   better current control and lower heat at holding current.
#
# CONFIGURING FOR YOUR DRIVER:
#   This code is written to work with any standard STEP/DIR driver
#   (A4988, DRV8825, TMC2208, etc.). When you choose your driver:
#     1. Set STEPPER_STEPS_PER_REV in config.py for your motor + microstepping
#     2. Check whether your driver's EN pin is active LOW or active HIGH
#        (most are active LOW — EN=0 means enabled)
#     3. If your deploy direction is wrong on first test, flip
#        STEPPER_DEPLOY_DIR_HIGH in config.py
#
# NO POSITION FEEDBACK:
#   This system has no encoder or limit switch. The motor's position
#   is assumed based on commands sent. If the motor misses steps
#   (stall, too fast, insufficient current), the assumed position
#   will drift from reality. Watch for this in post-flight logs —
#   if brakes_deployed is True but the predicted apogee keeps rising,
#   the brakes may not have physically deployed.
#
#   RECOMMENDATION: Before flight, bench-test deploy() and retract()
#   with the actual motor and mechanism to confirm 90° of travel.
# =============================================================================

import time
import board
import digitalio

from telemetry_types import ActuatorStatus
import config


class Actuator:

    def __init__(self):
        """
        Initialize stepper driver GPIO pins.

        Sets up STEP, DIR, and EN pins as digital outputs.
        The motor is disabled (EN HIGH) at startup and only enabled
        during an active move to reduce heat and power consumption.

        Called once at startup in main.py.
        """
        # STEP pin — each LOW→HIGH transition moves the motor one step
        self._step_pin = digitalio.DigitalInOut(
            getattr(board, f"GP{config.STEPPER_STEP_PIN}")
        )
        self._step_pin.direction = digitalio.Direction.OUTPUT
        self._step_pin.value = False

        # DIR pin — HIGH or LOW sets the rotation direction
        self._dir_pin = digitalio.DigitalInOut(
            getattr(board, f"GP{config.STEPPER_DIR_PIN}")
        )
        self._dir_pin.direction = digitalio.Direction.OUTPUT
        self._dir_pin.value = False

        # EN pin — active LOW on most drivers.
        # We ENABLE the motor immediately at startup to hold the brake
        # leaves in the retracted position via active holding torque.
        # There is no mechanical latch — the energized coils are the
        # only thing keeping the leaves closed before and during flight.
        self._en_pin = digitalio.DigitalInOut(
            getattr(board, f"GP{config.STEPPER_ENABLE_PIN}")
        )
        self._en_pin.direction = digitalio.Direction.OUTPUT
        self._enable_motor()   # Hold retracted from the moment of power-on

        # Track commanded position
        # is_deployed = True means brakes are out (90° from home)
        # is_deployed = False means brakes are retracted (home position)
        self._status = ActuatorStatus(is_deployed=False, is_moving=False)

    # -------------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------------

    def deploy(self) -> bool:
        """
        Deploy the airbrakes by rotating the motor 90 degrees.

        Returns:
            True  if the move was executed.
            False if the brakes were already deployed (no move needed).

        WHAT HAPPENS PHYSICALLY:
          1. EN pin pulled LOW (motor energized)
          2. DIR pin set to deploy direction
          3. STEPPER_STEPS_FOR_90_DEG step pulses sent
          4. EN pin pulled HIGH (motor de-energized)
          5. ActuatorStatus updated to is_deployed=True
        """
        if self._status.is_deployed:
            return False   # Already deployed, nothing to do

        self._move(steps=config.STEPPER_STEPS_FOR_90_DEG, deploy=True)
        # Motor is disabled after deploy — aerodynamic drag holds leaves open.
        # See HOLDING TORQUE note at top of file.
        self._disable_motor()
        self._status = ActuatorStatus(is_deployed=True, is_moving=False)
        return True

    def retract(self) -> bool:
        """
        Retract the airbrakes by rotating the motor 90 degrees in reverse.

        Returns:
            True  if the move was executed.
            False if the brakes were already retracted (no move needed).
        """
        if not self._status.is_deployed:
            return False   # Already retracted, nothing to do

        self._move(steps=config.STEPPER_STEPS_FOR_90_DEG, deploy=False)
        # Motor stays ENABLED after retract to maintain holding torque.
        # No mechanical latch exists — the energized coils are the only
        # thing keeping the leaves closed against aero forces and vibration.
        # See HOLDING TORQUE note at top of file.
        self._status = ActuatorStatus(is_deployed=False, is_moving=False)
        return True

    def emergency_retract(self) -> None:
        """
        Retract the brakes unconditionally, ignoring current status.

        Used by the safety watchdog in brake_controller.py when a
        sudden velocity shift or 3-second negative velocity is detected.
        Unlike retract(), this does not check is_deployed — it always
        sends the full retract sequence to guarantee physical retraction
        even if the assumed position is wrong.

        This is the "just close them no matter what" command.
        """
        self._move(steps=config.STEPPER_STEPS_FOR_90_DEG, deploy=False)
        # Keep motor enabled — same active holding logic as retract().
        self._status = ActuatorStatus(is_deployed=False, is_moving=False)

    @property
    def status(self) -> ActuatorStatus:
        """Current commanded actuator state."""
        return self._status

    # -------------------------------------------------------------------------
    # Private motor control
    # -------------------------------------------------------------------------

    def _move(self, steps: int, deploy: bool) -> None:
        """
        Send a sequence of step pulses to the motor driver.

        Args:
            steps:  Number of steps to send.
            deploy: True = deploy direction, False = retract direction.

        HOW THE STEP PULSE WORKS:
          Most stepper drivers trigger on a rising edge (LOW → HIGH).
          We hold HIGH for STEPPER_STEP_DELAY_S / 2, then LOW for
          the same duration. This gives a square wave with a 50% duty
          cycle at the configured step rate.

          STEP_DELAY_S = 0.002 (2ms default) means:
            1ms HIGH + 1ms LOW = 2ms per step
            50 steps (90°) × 2ms = 100ms total move time
          That is fast enough to respond to flight events while being
          slow enough that the motor is unlikely to miss steps.
          If you need faster deployment, reduce STEPPER_STEP_DELAY_S
          carefully — test on the bench first.

        Args:
            steps:  Number of step pulses to send.
            deploy: Direction flag.
        """
        # Set direction
        if deploy:
            self._dir_pin.value = config.STEPPER_DEPLOY_DIR_HIGH
        else:
            self._dir_pin.value = not config.STEPPER_DEPLOY_DIR_HIGH

        # Mark as moving in status
        self._status = ActuatorStatus(
            is_deployed=self._status.is_deployed,
            is_moving=True
        )

        # Enable motor driver
        self._enable_motor()

        half_delay = config.STEPPER_STEP_DELAY_S / 2.0

        # Send step pulses
        for _ in range(steps):
            self._step_pin.value = True
            time.sleep(half_delay)
            self._step_pin.value = False
            time.sleep(half_delay)

        # Note: _enable_motor() / _disable_motor() is NOT called here.
        # The deploy() and retract() methods decide whether to hold or
        # release the motor after the move completes.
        # See HOLDING TORQUE note at top of file.

    def _enable_motor(self) -> None:
        """Pull EN pin LOW to activate the driver (active-LOW logic)."""
        self._en_pin.value = False

    def _disable_motor(self) -> None:
        """Pull EN pin HIGH to deactivate the driver."""
        self._en_pin.value = True
