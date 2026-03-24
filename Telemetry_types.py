from dataclasses import dataclass
from typing import Optional


# =========================
# TELEMETRY (RAW FROM READER)
# =========================

@dataclass
class TelemetrySample:
    """
    Standardized telemetry sample used throughout the program.

    This is created from AltimeterReader.get_state()
    and then passed to downstream modules.
    """
    pi_time: float
    altitude_ft: float
    vertical_velocity_ft_s: float

    telemetry_valid: bool
    last_valid_update_time: float

    raw_line: Optional[str] = None


# =========================
# DERIVED STATE (COMPUTED)
# =========================

@dataclass
class DerivedState:
    """
    Values computed from telemetry history and controller context.
    """
    vertical_acceleration_ft_s2: float
    time_since_launch_s: float

    altitude_error_ft: float

    avg_velocity_ft_s: float
    avg_acceleration_ft_s2: float


# =========================
# CONTROL / DECISION OUTPUT
# =========================

@dataclass
class ControllerCommand:
    """
    High-level command issued by controller logic.
    """
    deploy: bool = False
    retract: bool = False
    shutdown: bool = False


# =========================
# ACTUATOR STATUS
# =========================

@dataclass
class ActuatorStatus:
    """
    Represents actuator state.

    Since there is currently no position feedback,
    this reflects commanded/assumed state, not measured position.
    """
    is_deployed: bool
    is_moving: bool = False


# =========================
# ADAPTER FROM ALTIMETER READER
# =========================

def telemetry_from_dict(state: dict) -> TelemetrySample:
    """
    Convert the dictionary returned by AltimeterReader.get_state()
    into the standardized TelemetrySample object used by the
    rest of the program.
    """
    return TelemetrySample(
        pi_time=state["pi_time"],
        altitude_ft=state["altitude_ft"],
        vertical_velocity_ft_s=state["vertical_velocity_ft_s"],
        telemetry_valid=state["telemetry_valid"],
        last_valid_update_time=state["last_valid_update_time"],
        raw_line=state.get("last_raw_line")
    )
