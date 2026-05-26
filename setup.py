from setuptools import find_packages, setup

setup(
    name="SyncZik",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "spotipy",
        "deezer-python",
        "python-dotenv",
        "setuptools",
        "textual",
    ],
    entry_points={"console_scripts": ["syncZik=SyncZik.SyncZik:main"]},
)
