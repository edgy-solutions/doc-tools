from setuptools import find_packages, setup

setup(
    name="doc_tools",
    packages=find_packages(exclude=["doc_tools_tests"]),
    install_requires=[
        "dagster",
        "dagster-cloud"
    ],
    extras_require={"dev": ["dagster-webserver", "pytest"]},
)
