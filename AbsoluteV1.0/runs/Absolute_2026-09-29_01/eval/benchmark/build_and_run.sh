#!/bin/bash
# Compile geometry_core from the candidate working tree and run the harness.
# Object files are content-addressed outside the candidate and the benchmark.
set -euo pipefail

GEOM="$1"
HARNESS="$2"
CACHE="$3"
HEADER_DIR="$4"

mkdir -p "$CACHE/objs" "$CACHE/bin"

read -r -a OCV_CFLAGS <<< "$(pkg-config --cflags opencv4)"
read -r -a OCV_LIBS <<< "$(pkg-config --libs opencv4)"

compile_one() {
  local src="$1"
  local extra="$2"
  local hash obj
  hash=$( (sha256sum "$src"; printf '%s\n' "$extra") | sha256sum | awk '{print $1}')
  obj="$CACHE/objs/${hash}.o"
  if [[ ! -f "$obj" ]]; then
    g++ -std=c++17 -O3 -fopenmp -Wall -Wextra \
      -I"$GEOM/include" -I"$GEOM/src" -I"$HEADER_DIR" -I/usr/include/eigen3 \
      "${OCV_CFLAGS[@]}" \
      -c "$src" -o "$obj"
  fi
  printf '%s\n' "$obj"
}

objs=()
sources=(
  version.cpp
  transforms.cpp
  pose.cpp
  plane_fit.cpp
  plane_coords.cpp
  face_mask.cpp
  camera_config.cpp
  prototype.cpp
  chamfer.cpp
  pca_init.cpp
  chamfer_prior.cpp
  backproject.cpp
  pipeline_v3_2.cpp
)
for name in "${sources[@]}"; do
  objs+=("$(compile_one "$GEOM/src/$name" "")")
done

header_hash=$(sha256sum "$HEADER_DIR/bench_scene.hpp" | awk '{print $1}')
objs+=("$(compile_one "$HARNESS" "$header_hash")")

link_key=$(printf '%s\n' "${objs[@]}" | sha256sum | awk '{print $1}')
bin="$CACHE/bin/$link_key"
if [[ ! -x "$bin" ]]; then
  g++ -fopenmp -o "$bin" "${objs[@]}" "${OCV_LIBS[@]}" -lyaml-cpp -pthread
fi

export OMP_NUM_THREADS=1
exec "$bin"
