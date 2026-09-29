#!/bin/bash
# Driver for the pps_dataset_replay dataset-replay tool.
#
# Launches rtdetr_detector_node + pallet_pose_cpp_node + eval_recorder_node
# (dataset_replay.launch.py) in the background, plays the pre-built bag
# into their topics via `ros2 bag play` (foreground, blocks until done),
# waits a drain margin for the last sample's in-flight Stage-2 latency to
# finish, then SIGINTs the launch so eval_recorder_node's `finally:` block
# writes per_sample_errors.csv/report.md/overlays before the nodes tear
# down. No `--clock`/`use_sim_time` is needed: message_filters::
# ApproximateTime and this tool's own stamp-based join both match on each
# message's own `header.stamp`, not wall time.
#
# Usage:
#   run_replay.sh <bag_dir> <dataset_root> <output_dir> [drain_s] [extra ros2-launch args...]
#
# Example:
#   run_replay.sh /tmp/dataset_bag /data/eval_dataset_combined /tmp/replay_report 5 \
#       detector_params:=/path/to/detector.yaml
#
# <bag_dir> and its stamp_map.json/bag_meta.json sidecars are produced by:
#   ros2 run pps_dataset_replay build_bag --dataset-root /data/eval_dataset_combined \
#       --out /tmp/dataset_bag --pace-hz 1.0
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: $0 <bag_dir> <dataset_root> <output_dir> [drain_s] [extra ros2-launch args...]" >&2
  exit 1
fi

BAG_DIR="$1"; shift
DATASET_ROOT="$1"; shift
OUTPUT_DIR="$1"; shift

DRAIN_S="5"
if [ "$#" -gt 0 ] && [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  DRAIN_S="$1"
  shift
fi

echo "==> Launching detector + pose + recorder nodes"
# Backgrounding a command in a non-interactive script (no job control) makes
# bash set that child's SIGINT/SIGQUIT disposition to SIG_IGN before exec --
# and Python never overrides an inherited SIG_IGN (see CPython's `signal`
# docs). Without the `trap - INT TERM` below, that ignored disposition
# propagates from `ros2 launch` down into every ROS2 node it spawns, so the
# `kill -INT "$LAUNCH_PID"` at the bottom of this script would silently do
# nothing and eval_recorder_node would never receive the KeyboardInterrupt/
# ExternalShutdownException it needs to run finalize() and write the report.
(
  trap - INT TERM
  exec ros2 launch pps_dataset_replay dataset_replay.launch.py \
      dataset_root:="$DATASET_ROOT" \
      replay_meta_dir:="$BAG_DIR" \
      output_dir:="$OUTPUT_DIR" \
      "$@"
) &
LAUNCH_PID=$!
# set -e means any failure between here and the explicit `kill -INT` below
# (e.g. `ros2 bag play` erroring because $BAG_DIR doesn't exist) would exit
# this script immediately -- without this trap that leaves the launch tree
# (and its detector/pose nodes) orphaned in the background, silently
# duplicating nodes on the next invocation of this script.
cleanup() {
  if kill -0 "$LAUNCH_PID" 2>/dev/null; then
    kill -INT "$LAUNCH_PID" 2>/dev/null || true
    wait "$LAUNCH_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Give the nodes a moment to come up before the bag starts publishing.
sleep 3

echo "==> Playing bag: $BAG_DIR"
ros2 bag play "$BAG_DIR"

echo "==> Bag playback finished; draining in-flight samples for ${DRAIN_S}s"
sleep "$DRAIN_S"

echo "==> Stopping launch (SIGINT -- eval_recorder_node finalizes its report on this signal)"
cleanup

echo "==> Done. Report written to: $OUTPUT_DIR"
