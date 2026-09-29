from setuptools import find_packages, setup

package_name = "pps_rtdetr_detector"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test", "test.*"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools", "numpy"],
    zip_safe=True,
    maintainer="PPS",
    maintainer_email="todo@example.com",
    description=(
        "RT-DETRv2 stage-1 detector ROS2 wrapper with pluggable TensorRT/Mock backends; "
        "publishes vision_msgs/Detection2DArray for the stage-2 chamfer estimator."
    ),
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "rtdetr_detector_node = pps_rtdetr_detector.node:main",
        ]
    },
)
