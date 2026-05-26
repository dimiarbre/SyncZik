from setuptools import find_packages, setup

setup(
    name="SyncZik",
    version="0.1.0",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "spotipy",
        "deezer-python",
        "python-dotenv",
        "setuptools",
        "textual",
    ],
    extras_require={"dev": ["pytest"]},
    entry_points={"console_scripts": ["syncZik=SyncZik.SyncZik:main"]},
)
