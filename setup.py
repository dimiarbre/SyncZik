from setuptools import find_packages, setup

setup(
    name="SyncZik",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.12",
    license="MIT",
    license_files=["LICENSE"],
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Environment :: Console",
    ],
    install_requires=[
        "spotipy",
        "deezer-python",
        "httpx",
        "python-dotenv",
        "setuptools",
        "textual",
    ],
    extras_require={"dev": ["pytest", "mypy"]},
    entry_points={"console_scripts": ["syncZik=SyncZik.SyncZik:main"]},
)
