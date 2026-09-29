# Absolute handoff

status: paused
stop_reason: error: can only concatenate str (not "NoneType") to str
success: False
uncovered_behaviors:
- The pps source is the pallet perception stack on an AGV. The user is the vehicle's dynamic handling process: it needs a pallet pose while the scene can still change. The outputs that matter are the pallet pose, the pallet width, height, and depth in metres, and which detected pallets are sent through stage 2 versus marked deferred.
- The user is the vehicle's dynamic handling process: it needs a pallet pose while the scene can still change.
- output: dimensions dimension_error_m minimize 0.001 0
- output: selection selection_error minimize 0.001 0
- output: scenario scenario_error minimize 0.001 0
run: C:\Users\alanpeng\Desktop\Self-envolve_agent\AbsoluteV1.0\runs\Absolute_2026-09-29_01
source_package: C:\Users\alanpeng\Desktop\Self-envolve_agent\pps_v3.4_ros\src
package_copy: C:\Users\alanpeng\Desktop\Self-envolve_agent\AbsoluteV1.0\runs\Absolute_2026-09-29_01\package\src
baseline: {"latency_ms": 182.626425, "pose_error_m": 0.001999999999999993}
best: {"latency_ms": 173.294496, "pose_error_m": 0.0}
cycles: 2 keeps: 1

attempts:
- attempts/001.patch
- attempts/002.patch

journal_tail:
{"at": "2026-09-29T07:48:37+00:00", "cycle": 0, "hypothesis": "baseline", "metrics": {"latency_ms": 182.626425, "pose_error_m": 0.001999999999999993}, "outcome": "baseline"}
{"admit_sha": "63792ed1106664b3cd852ef3c9f7cb1848100ad1", "at": "2026-09-29T08:08:41+00:00", "attempt": 1, "commit": "cc4afdbb4077b9bde8012f16dfdaa2d5f1305106", "cycle": 1, "error": "", "feature_id": null, "hypothesis": "Depth-pixel clipping shifts the chamfer centre by 2 mm on the frontal pallet. That shift is inside the silhouette's half-pixel quantization radius, so the pose keeps the sub-pixel bbox-ray/plane centre instead.", "metrics": {"latency_ms": 173.294496, "pose_error_m": 0.0}, "outcome": "keep", "patch": "attempts/001.patch", "stage": "search_edit"}
{"admit_sha": "cc4afdbb4077b9bde8012f16dfdaa2d5f1305106", "at": "2026-09-29T08:38:44+00:00", "attempt": 2, "cycle": 2, "error": "optimize exceeded 1800s; see C:\\Users\\alanpeng\\Desktop\\Self-envolve_agent\\AbsoluteV1.0\\runs\\Absolute_2026-09-29_01\\workers\\cycle-000002\\optimize.log", "feature_id": null, "hypothesis": "local improvement: latency_ms", "metrics": null, "outcome": "worker_failed", "patch": "attempts/002.patch", "stage": "search_edit"}

limitations:
- none

immutable_hashes: {"geometry_core/test/test_backproject.cpp": "3ba6b23cf3f38f9f7c90fa9ed569acf09ca7b24cd314998563bfa366be59c37f", "geometry_core/test/test_camera_config.cpp": "6ba46ace349edeaf7b17fa4587f42de00080a56ed682f346f350ce8031c1cc30", "geometry_core/test/test_chamfer.cpp": "90f71012a4b1d2a309accfec2b7776a8a1919d0c451f28fbb7d6ee7f75f0bff1", "geometry_core/test/test_chamfer_prior.cpp": "13aea861f2a13142df8afd5d4dcde47f2898a8f104f46381f96db15c7ec1ba18", "geometry_core/test/test_face_mask.cpp": "13d7e4a4cbc8e6b3071570b248e468c07a8c4dfaa34aa11130c1a3fa5e268007", "geometry_core/test/test_pca_init.cpp": "496d48084a229ff4e1149eb506bbff4d525dc3755821b66301238fe8191d799a", "geometry_core/test/test_pipeline_v3_2.cpp": "85a68ee725fe8f400c0c60550c8ae8c1e4035d91d0135b1a608e7969f3401d1b", "geometry_core/test/test_plane_coords.cpp": "1f61729fb9d79141e394a6acfcf3ae73db1abb00125b409474cf78ab0fb8f0dd", "geometry_core/test/test_plane_fit.cpp": "d760c69a183507e39689a8bc363fb4d712322680035ff28ea3fe4eebbb306b17", "geometry_core/test/test_pose.cpp": "9f6d4162c0fcbecaafc2cc667cce3c408297a8325cfa649796aea6b3c24e024f", "geometry_core/test/test_prototype.cpp": "b4f628fe3ccd6e79bd5fb4f50352c365cc2c3ff7e86eea09e2953947fc9a2d62", "geometry_core/test/test_transforms.cpp": "0cf69dd0b7df0f3ef9dc9488289bf48515b526973b02a611e229bfc676dd2cc5", "geometry_core/test/test_version.cpp": "aee311cb0d80b0bdd792978f2fb298b217a92c1a4fdca9c2087364656eb51f0a", "pps_pallet_pose_cpp/test/test_depth_utils.cpp": "05f987e587f80a4e9d7e97c08f3716b5dd20ccc8c6ae35e756187b1f314f15fe", "pps_pallet_pose_cpp/test/test_detection_utils.cpp": "4287d10285310056cc44817bf1260afe3c291968082e5d6175ed9575b3d293ab", "pps_perception_bringup/test/test_full_pipeline_launch.py": "a239fe4f78438974d428502a4661a48681e2aa5c6caf1e74c639c2c5e9e01638", "pps_rtdetr_detector/test/test_detector_mock.py": "a01d20d5a46ef2ebb52e5a17c047f49df6d1842cdaf644e9d9db222dcf74462d", "pps_rtdetr_detector/test/test_postprocess.py": "5de688939f14a0f0dc724b404bf3e0812df9ee1c00fdecf406cebf6cc51431fa", "pps_rtdetr_detector/test/test_preprocess.py": "6ad9e7907db861599ec45378982f63c6df13f1ef1c807f22d4ae73c618502527"}
robot_validated: false

Continuous search: resume this folder with python -m absolute evolve --run <folder>. Recent attempts are summarized here; full history is in journal.jsonl. Targets and plateau do not imply SOTA. This is not a state-of-the-art claim. Do not mark a keep. robot_validated: false.
