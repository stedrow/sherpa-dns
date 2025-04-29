"""
Setup script for Sherpa-DNS.
"""

from setuptools import find_packages, setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = fh.read().splitlines()

setup(
    name="sherpa-dns",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="A Python application to create and manage DNS records for Docker Compose services",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/sherpa-dns",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.12",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "sherpa-dns=sherpa_dns.__main__:main",
        ],
    },
    include_package_data=True,
)
