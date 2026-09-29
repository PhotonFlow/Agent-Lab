import os
from glob import glob

from setuptools import find_packages, setup

package_name = "pps_dataset_replay"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "test.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "scripts"), glob("scripts/*.sh")),
    ],
    install_requires=["setuptools", "numpy", "opencv-python", "pandas", "matplotlib", "PyYAML"],
    zip_safe=True,
    maintainer="PPS",
    maintainer_email="todo@example.com",
    description=(
        "ROS2 dataset-replay debug tool: replays eval_dataset_combined through the live "
        "detector + pallet_pose_cpp_node graph via a rosbag2, joins results back to ground "
        "truth, and renders per-sample overlays."
    ),
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "build_bag = pps_dataset_replay.build_bag:main",
            "eval_recorder_node = pps_dataset_replay.eval_recorder_node:main",
        ]
    },
)
