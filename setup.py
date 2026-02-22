from setuptools import find_packages, setup

setup(
    name="ez-watch-alert-relay",
    version="0.1.0",
    description="MVP computer vision alert relay for resort sensitive zones",
    packages=find_packages(include=["app", "app.*"]),
    python_requires=">=3.9",
    install_requires=[
        "fastapi>=0.115.0",
        "uvicorn[standard]>=0.30.0",
        "pydantic>=2.8.0",
        "pydantic-settings>=2.3.4",
        "eval_type_backport>=0.2.0; python_version < '3.10'",
        "httpx>=0.27.0",
        "PyYAML>=6.0.1",
        "prometheus-client>=0.20.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.2.0",
            "pytest-cov>=5.0.0",
            "respx>=0.21.1",
        ]
    },
)
