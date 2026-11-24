---
name: maxwell-pmsm
description: Build, run, inspect, or compare permanent-magnet synchronous motor simulations in Ansys Maxwell, with traceable inputs and validation. Use for Maxwell PMSM modeling, operating-point sweeps, losses, and simulation reviews; do not use for generic motor explanations without a simulation task.
---

# Maxwell 永磁同步电机仿真

Use this skill to carry a Maxwell PMSM case from source drawings and operating conditions to a reproducible result. On this workstation keep cases, solver outputs, reports and the MCP runtime under `D:\Maxwell项目\maxwell仿真`. The local 2023 R2 benchmark is a 75 kW no-load transient; the older 2021 R1 studies also cover load and losses. Preserve the version and backend for each result.

## Connect to Maxwell

Discover the installed AEDT release and the tools exposed in the current session. For the official PyAEDT-MCP bridge, follow [MCP connection and result checks](references/mcp-2023r2.md). Verify the connected desktop version, project path, active design, solution type and setup before modifying or solving. Use the [native batch workflow](references/local-toolchain.md) for a case with a validated runner or when the bridge is unavailable. After a timeout, inspect the existing job and results before retrying through either interface.

Maxwell can automatically export EMF in mV even when the earlier report used V. Preserve the raw CSV. Use `scripts/normalize_noload_emf.py` before passing it to older voltage or phase analysis scripts that assume ms and V. For a second export of the same solution, use `scripts/compare_noload_exports.py` to check every phase sample.

Open an older project first on a uniquely named case copy. Preserve the original project and its solution data together. If AEDT rewrites the copy, record its new hash and the archived input hash. For an upgrade comparison hold winding, geometry, materials, temperature, speed and time window fixed. For a material study record the supplier, grade, curve type, operating temperature and data source from the project material library.

## Establish the model

1. Preserve original drawings and source hashes; record rated operating point, units and source for dimensions, stack, poles/slots, winding, magnetization, B-H, loss data and temperature. Distinguish line/phase, peak/RMS, mechanical/electrical angle, shaft/electromagnetic output. Missing values are unknown, not zero. For exploratory work, use explicitly labeled plausible assumptions where appropriate and disclose their effect; never present them as supplied or validated facts.
2. Use dimensions and drawing intent, not an unverified picture scale. If geometry and dimensions conflict, inspect sources and apply the user's confirmed interpretation; otherwise flag the conflict. Convert CAD only with provenance and audit units, missing entities, closed regions and key dimensions. For imported/reconstructed geometry check air gap, magnet pockets/axes and windings. A full 2D model is the safe starting point; use a sector only after proving geometry, magnetic polarity and excitation symmetry, boundary parity and multiplier, ideally against a full model. Explicitly state straight-slot or axial segmentation approximations.
3. Prefer actual slot/layer/phase/polarity/branch/turns table. An ideal winding candidate and phasor balance are not proof of factory wiring. Check per-coil turns, slot occupancy, branch grouping, phase sequence and magnet orientations in the saved model. Aggregate current sources do not solve real parallel-branch circulating currents. Read [local toolchain](references/local-toolchain.md) for the restricted mixed-turn adapter; do not silently substitute uniform turns.

## Solve and calibrate

Create a new case directory for every geometry/condition; preserve inputs, configuration, source and script hashes, logs, solver output and raw waveforms. Reuse prior completed cases when their provenance and settings match. Check status before starting or retrying: launcher return is not solver completion. Confirm validation, normal solver completion, project save and close, expected finite CSV data with correct units and time coverage. If a case is active, do not launch it again. On failure, retain the failed evidence, identify the cause, and retry only with a distinct case; do not silently fall back to estimates or substitute default outputs. The optional `scripts/audit_case.py` is a read-only evidence check, not physical validation; use its `--help` and see [verification](references/verification.md).

Solve no-load first when needed, inspect EMF amplitude, phase sequence and waveform, then calibrate current against the modeled EMF. An A-phase time-zero sine angle is not a d/q angle or necessarily the design-sheet control angle. Convert phase RMS current to peak only where the API requires it; verify positive torque/power direction and current sequence. When the task calls for rated capability or maximum torque, scan feasible current angles coarse-to-fine at the specified current and constraints, then state the sampled range and whether a maximum is bracketed. A single chosen angle is a comparison point, not an optimum. The local mixed-turn adapter supports ABC/ACB; the generic load sweep and core-loss generator assume ABC unless adapted and verified.

## Check and report

For full-machine no-load and loaded operating points, include air-gap, stator-tooth and stator-yoke flux density. Plan field saves before solving. Use the [magnetic flux density workflow](references/flux-density.md) to verify point materials and report sampled peaks alongside RMS in tesla. Distinguish gap radial full-wave and fundamental RMS, tooth/yoke sampled-region RMS, and the highest fixed-point cycle RMS. State the time window and use the same sampling definitions across cases.

For an illustrated comparison or individual motor sheet, use the [single-page report and material costing workflow](references/illustrated-report.md). On individual sheets include a local stator/rotor assembly, the dimensioned stator slot, magnet pocket and magnet block, and waveforms from the selected motor. Show material grades, net masses and dated prices, and provide the detailed numerical exports alongside the sheet.

On the page itself show winding wire sizes and parallel strands, rated copper current density, specific electric loading, thermal loading, stator resistance and d/q inductances. Label design-sheet, derived, measured and Maxwell values by source, unit and operating point. Use the winding-panel fields and checks in the report workflow.
When wire area, mean turn length and branch topology are available, calculate the per-phase winding DC resistance at a stated temperature independently and show it alongside the design-sheet value. State which resistance feeds each copper-loss estimate.

Match the requested depth: a quick screening may use a coarse mesh and short window, but explicitly list unchecked convergence and missing outputs. For decisions requiring accuracy, compare same-physics independent cases with finer air-gap/bridge and PM meshes, smaller time steps and successive **mechanical** periods. Compare stable mean torque, relevant ripple, voltage and each loss in identical windows, document tolerances and both results. Two electrical cycles are not generally two mechanical turns. If iron loss is still changing, extend the run; never call it stable by assumption. See [verification](references/verification.md) for concrete gates and loss-specific cautions.

Report source/assumption, case settings, quantities and units, time windows and evidence links. Separate actual solved quantities from design-sheet values and algebraic estimates. Induced EMF is not complete terminal voltage; electromagnetic torque is not shaft torque; `SolidLoss` is not whole-machine loss. Do not infer final efficiency, temperature, irreversible demagnetization, life or acceptance without the required validated physics and inputs. Any unperformed solve or verification remains explicitly pending. If user explicitly asks for a quick subset, perform that subset and label the boundary rather than forcing unrelated work.
