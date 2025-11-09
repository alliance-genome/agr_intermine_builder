## Project Overview

This project is a Python-based orchestration system for building and managing InterMine instances. InterMine is an open-source data warehouse system for biological data. This project uses Docker to create reproducible build environments and can be configured to work with AWS RDS for database management.

The project is structured as a Python application with a command-line interface (CLI) for interacting with the build system. The core logic is encapsulated in the `src/intermine_builder` package, which contains modules for managing Docker, executing build steps, and handling configuration.

### Key Technologies

*   **Python 3.9+:** The core language for the orchestration logic.
*   **Docker:** Used to create isolated and reproducible build environments for the InterMine instances.
*   **Docker Compose:** Used to define and run multi-container Docker applications.
*   **AWS RDS (optional):** Can be used to provision and manage the PostgreSQL databases required by InterMine.
*   **Boto3:** The AWS SDK for Python, used for interacting with AWS services like RDS.
*   **PostgreSQL:** The database used by InterMine.

### Architecture

The application is designed around a central `MineBuilder` class that orchestrates the entire build process. This class uses a `DockerManager` to handle Docker-related operations (building images, creating containers) and a `BuildExecutor` to run the build commands inside the Docker containers.

The configuration is managed by a `Config` class that loads settings from environment variables or a configuration file. This allows for flexible configuration for different environments (e.g., development, staging, production).

The project also includes a CLI (`build-mines`) that provides a user-friendly way to initiate builds, check status, and manage the InterMine instances.

## Building and Running

The project uses a `pyproject.toml` file to manage dependencies and define project scripts. The following commands are used to build and run the project:

*   **Install dependencies:**
    ```bash
    pip install -e .
    ```

*   **Run the build CLI:**
    ```bash
    python -m src.cli.build_mines --help
    ```

*   **Build a specific mine:**
    ```bash
    python -m src.cli.build_mines build --mine alliancemine
    ```

*   **Build all mines:**
    ```bash
    python -m src.cli.build_mines build-all
    ```

*   **Run tests:**
    ```bash
    pytest
    ```

## Development Conventions

*   **Code Style:** The project uses `black` for code formatting and `ruff` for linting. The configuration for these tools can be found in the `pyproject.toml` file.
*   **Typing:** The project uses type hints, and `mypy` is used for static type checking.
*   **Testing:** The project uses `pytest` for testing. Tests are located in the `tests` directory.
*   **Dependency Management:** The project uses `uv` to manage dependencies, with the `uv.lock` file tracking the exact versions of the dependencies.
