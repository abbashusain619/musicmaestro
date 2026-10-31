from setuptools import setup, find_packages

setup(
    name="musicmaestro",
    version="1.0.0",
    py_modules=["main"],
    packages=find_packages(),
    install_requires=[
        "mutagen",
        "rich",
        "shazamio",
        "spotdl",
    ],
    entry_points={
        "console_scripts": [
            "maestro=main:main",
        ],
    },
)