"""Rated copper current density and specific electric loading for round-wire stators."""
from math import isfinite, pi


def phase_resistance_20c(*, series_turns_per_path, mean_half_turn_mm, copper_area_mm2,
                        parallel_paths, rho20_ohm_mm2_m=1/58):
    """DC resistance of identical parallel paths, excluding leads and contacts."""
    for count in (series_turns_per_path, parallel_paths):
        if type(count) is not int or count <= 0:
            raise ValueError("Positive integer series turns and parallel paths required")
    if not all(isfinite(x) and x > 0 for x in (mean_half_turn_mm, copper_area_mm2, rho20_ohm_mm2_m)):
        raise ValueError("Positive finite mean half-turn length, copper area and resistivity required")
    path_length_m = series_turns_per_path * 2 * mean_half_turn_mm / 1000
    path_R = rho20_ohm_mm2_m * path_length_m / copper_area_mm2
    return dict(series_turns_per_path=series_turns_per_path, mean_half_turn_mm=mean_half_turn_mm,
                path_length_m=path_length_m, rho20_ohm_mm2_m=rho20_ohm_mm2_m,
                path_R20_ohm=path_R, phase_R20_ohm=path_R / parallel_paths)


def round_wire_loading(*, phase_rms_A, parallel_paths, wires, slots, conductors_per_slot, bore_mm):
    """Each wire is (parallel strands, bare diameter in mm). Paths share current equally."""
    for n in (parallel_paths, slots, conductors_per_slot):
        if type(n) is not int or n <= 0:
            raise ValueError("Positive integer path, slot and conductor counts required")
    if not all(isfinite(x) and x > 0 for x in (phase_rms_A, bore_mm)):
        raise ValueError("Positive finite phase RMS current and stator bore required")
    copper_area = 0.0
    for strands, diameter in wires:
        if type(strands) is not int or strands < 0 or not isfinite(diameter) or diameter <= 0:
            raise ValueError("Invalid strand count or bare wire diameter")
        copper_area += strands * pi * diameter**2 / 4
    if not copper_area:
        raise ValueError("At least one active strand required")
    branch_current = phase_rms_A / parallel_paths
    density = branch_current / copper_area
    linear = slots * conductors_per_slot * branch_current / (pi * bore_mm / 10)
    return dict(copper_area_mm2=copper_area, branch_rms_A=branch_current,
                J_A_mm2=density, linear_A_cm=linear, AJ_A2_cm_mm2=linear*density)
