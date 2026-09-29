# Absolute handoff

status: stopped
stop_reason: uncovered_outputs
run: C:\Users\alanpeng\Desktop\Self-envolve_agent\AbsoluteV1.0\runs\Absolute_2026-09-28_02
source_package: C:\Users\alanpeng\Desktop\Self-envolve_agent\pps_v3.4_ros\src
package_copy: C:\Users\alanpeng\Desktop\Self-envolve_agent\AbsoluteV1.0\runs\Absolute_2026-09-28_02\package\src
baseline: {"dimension_error_m": 3.0, "latency_ms": 60.495935, "pose_error_m": 0.001999999999999993, "scenario_error": 4.752, "selection_error": 1.75}
best: {"dimension_error_m": 3.0, "latency_ms": 46.914066, "pose_error_m": 0.001999999999999993, "scenario_error": 3.002, "selection_error": 0.0}
cycles: 3 keeps: 1

attempts:
- attempts/001.patch
- attempts/002.patch
- attempts/003.patch
- attempts/004.patch
- attempts/005.patch
- attempts/006.patch
- attempts/007.patch
- attempts/008.patch
- attempts/009.patch
- attempts/010.patch
- attempts/011.patch
- attempts/012.patch
- attempts/013.patch
- attempts/014.patch
- attempts/015.patch
- attempts/016.patch
- attempts/017.patch
- attempts/018.patch

journal_tail:
{"admit_sha": "be7cbf2eb71ebe6ec3b88d1bd6816e6847923e1c", "at": "2026-09-28T14:18:52+00:00", "cycle": 2, "error": "protected metric latency_ms regressed", "feature_id": "sent_deferred_roster", "hypothesis": "on_pair already holds every class-matched candidate and drops the ones select_detection does not choose before publish_pose, so the controller's pose names neither the sent index nor the deferred indices of this pair; writing those indices onto PalletPoseStamped, and onto the failure diagnostic when no pose is published, is the sent-versus-deferred split for this synchronized capture.", "metrics": {"dimension_error_m": 3.0, "latency_ms": 76.793167, "pose_error_m": 0.001999999999999993, "scenario_error": 4.752, "selection_error": 1.75}, "outcome": "revert", "patch": "attempts/014.patch", "stage": "feature_edit"}
{"admit_sha": "be7cbf2eb71ebe6ec3b88d1bd6816e6847923e1c", "at": "2026-09-28T14:36:52+00:00", "cycle": 2, "error": "latency-only", "feature_id": "sent_deferred_roster", "hypothesis": "on_pair already holds every class-matched candidate and drops the ones select_detection does not choose before publish_pose, so the controller's pose names neither the sent index nor the deferred indices of this pair; writing those indices onto PalletPoseStamped, and onto the failure diagnostic when no pose is published, is the sent-versus-deferred split for this synchronized capture.", "metrics": {"dimension_error_m": 3.0, "latency_ms": 48.025387, "pose_error_m": 0.001999999999999993, "scenario_error": 4.752, "selection_error": 1.75}, "outcome": "revert", "patch": "attempts/015.patch", "stage": "feature_edit"}
{"admit_sha": "be7cbf2eb71ebe6ec3b88d1bd6816e6847923e1c", "at": "2026-09-28T14:47:08+00:00", "cycle": 2, "error": "protected metric latency_ms regressed", "feature_id": "sent_deferred_roster", "hypothesis": "lower measured latency", "metrics": {"dimension_error_m": 3.0, "latency_ms": 67.024488, "pose_error_m": 0.001999999999999993, "scenario_error": 4.752, "selection_error": 1.75}, "outcome": "revert", "patch": "attempts/016.patch", "stage": "inference_edit"}
{"admit_sha": "be7cbf2eb71ebe6ec3b88d1bd6816e6847923e1c", "at": "2026-09-28T16:47:05+00:00", "commit": "5a1c2955d94c0b6fa9a9951e259dfc2c217fba68", "cycle": 3, "error": "", "feature_id": "published_admission_split", "hypothesis": "on_pair already holds every class-matched candidate and select_detection returns only the one pallet stage 2 estimates, so the controller's pose names neither the sent index nor the deferred indices of this capture. select_stage2_subset returns both vectors with that same ranking, and writing those indices onto PalletPoseStamped, and onto the failure diagnostic when no pose is published, is the sent-versus-deferred split for this synchronized capture.", "metrics": {"dimension_error_m": 3.0, "latency_ms": 46.914066, "pose_error_m": 0.001999999999999993, "scenario_error": 3.002, "selection_error": 0.0}, "outcome": "keep", "patch": "attempts/017.patch", "stage": "feature_edit"}
{"admit_sha": "5a1c2955d94c0b6fa9a9951e259dfc2c217fba68", "at": "2026-09-28T16:57:19+00:00", "cycle": 3, "error": "latency-only", "feature_id": "published_admission_split", "hypothesis": "lower measured latency", "metrics": {"dimension_error_m": 3.0, "latency_ms": 41.831838, "pose_error_m": 0.001999999999999993, "scenario_error": 3.002, "selection_error": 0.0}, "outcome": "revert", "patch": "attempts/018.patch", "stage": "inference_edit"}

limitations:
- feature_edit: revert latency-only
- feature_edit: revert latency-only
- feature_edit: revert latency-only
- feature_edit: bad_edit error: git diff header lacks filename information when removing 1 leading pathname component (line 181)
- feature_edit: revert protected metric latency_ms regressed
- feature_edit: revert latency-only
- feature_edit: revert protected metric latency_ms regressed
- feature_edit: revert latency-only
- inference_edit: revert protected metric latency_ms regressed
- inference_edit: revert latency-only

immutable_hashes: {}
robot_validated: false

This run stopped because a required output is still off target after the proposal rounds were exhausted. This is not a state-of-the-art claim. robot_validated: false. Do not open a new run.
