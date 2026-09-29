import os
from glob import glob

from setuptools import find_packages, setup

package_name = "pps_perception_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "test.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob("config/*.yaml")),
    ],
    install_requires=["setuptools", "numpy", "PyYAML"],
    zip_safe=True,
    maintainer="PPS",
    maintainer_email="todo@example.com",
    description="Launch files, configs, and a synthetic scene for the dynamic_handling perception pipeline.",
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "synthetic_scene_publisher = pps_perception_bringup.scene_publisher:main",
        ]
    },
)
