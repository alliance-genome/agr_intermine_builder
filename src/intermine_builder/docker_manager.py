"""
Docker Manager Module

Manages Docker container lifecycle for InterMine builds:
- Building Docker images
- Starting/stopping containers
- Executing commands inside containers
- Monitoring container status
- Managing volumes and networks
"""

import docker
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from docker.models.containers import Container
from docker.models.images import Image

from .mine_config import MineConfig, MineType

logger = logging.getLogger(__name__)


class DockerManager:
    """Manages Docker operations for InterMine builds."""

    def __init__(self, base_dir: Path):
        """
        Initialize Docker manager.

        Args:
            base_dir: Base directory for docker contexts
        """
        self.base_dir = base_dir
        self.client = docker.from_env()
        self.containers: Dict[MineType, Container] = {}
        self.images: Dict[MineType, Image] = {}

    def build_image(
        self,
        mine_config: MineConfig,
        force_rebuild: bool = False,
        build_args: Optional[Dict[str, str]] = None
    ) -> Image:
        """
        Build Docker image for a mine.

        Args:
            mine_config: Mine configuration
            force_rebuild: Force rebuild even if image exists
            build_args: Additional build arguments

        Returns:
            Built Docker image
        """
        mine_type = mine_config.mine_type
        image_tag = mine_config.docker_image

        # Check if image already exists
        if not force_rebuild:
            try:
                existing_image = self.client.images.get(image_tag)
                logger.info(f"Image {image_tag} already exists")
                self.images[mine_type] = existing_image
                return existing_image
            except docker.errors.ImageNotFound:
                pass

        logger.info(f"Building Docker image: {image_tag}")

        # Prepare build context
        context_path = self.base_dir / mine_config.docker_context
        if not context_path.exists():
            raise FileNotFoundError(f"Docker context not found: {context_path}")

        # Prepare build arguments
        default_build_args = {
            f"{mine_type.value.upper()}_BRANCH": mine_config.repo_branch,
            "BIO_SOURCES_BRANCH": mine_config.bio_sources_branch,
        }
        if build_args:
            default_build_args.update(build_args)

        # Build image
        try:
            image, build_logs = self.client.images.build(
                path=str(context_path),
                tag=image_tag,
                buildargs=default_build_args,
                rm=True,
                forcerm=True,
            )

            # Log build output
            for log in build_logs:
                if 'stream' in log:
                    logger.debug(log['stream'].strip())
                elif 'error' in log:
                    logger.error(log['error'])

            logger.info(f"Successfully built image: {image_tag}")
            self.images[mine_type] = image
            return image

        except docker.errors.BuildError as e:
            logger.error(f"Failed to build image {image_tag}: {e}")
            raise

    def create_container(
        self,
        mine_config: MineConfig,
        rds_host: str,
        rds_port: int,
        rds_user: str,
        rds_password: str,
        environment: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None
    ) -> Container:
        """
        Create container for a mine.

        Args:
            mine_config: Mine configuration
            rds_host: RDS host address
            rds_port: RDS port
            rds_user: RDS username
            rds_password: RDS password
            environment: Additional environment variables
            volumes: Additional volume mounts

        Returns:
            Created container
        """
        mine_type = mine_config.mine_type
        image_tag = mine_config.docker_image

        # Prepare environment variables
        env_vars = {
            "RDS_HOST": rds_host,
            "RDS_PORT": str(rds_port),
            "RDS_USER": rds_user,
            "RDS_PASSWORD": rds_password,
            "RDS_DB_NAME": mine_config.db_name,
            "RDS_PROFILE_DB_NAME": mine_config.profile_db_name,
            "GRADLE_OPTS": f"-Xmx{mine_config.resources.gradle_heap_gb}g "
                          f"-Xms{mine_config.resources.heap_size_gb}g "
                          f"-Dorg.gradle.daemon=false",
        }

        # Add release version
        if mine_type == MineType.ALLIANCEMINE:
            env_vars["ALLIANCE_RELEASE"] = mine_config.release_version
        elif mine_type == MineType.WORMMINE:
            env_vars["WORMBASE_RELEASE"] = mine_config.release_version

        # Merge with additional environment variables
        if environment:
            env_vars.update(environment)

        # Prepare volume mounts
        volume_mounts = {
            f"{mine_type.value}_data": {"bind": "/root/data", "mode": "rw"},
            f"{mine_type.value}_logs": {"bind": "/tmp", "mode": "rw"},
        }

        # Add custom data directory for WormMine
        if mine_config.use_custom_data and mine_config.custom_data_dir:
            volume_mounts[mine_config.custom_data_dir] = {
                "bind": "/root/custom_data",
                "mode": "ro"
            }

        # Merge with additional volumes
        if volumes:
            volume_mounts.update(volumes)

        # Create container
        try:
            container = self.client.containers.create(
                image=image_tag,
                name=f"{mine_type.value}-builder",
                environment=env_vars,
                volumes=volume_mounts,
                network="intermine-network",
                stdin_open=True,
                tty=True,
                detach=True,
                mem_limit=f"{mine_config.resources.memory_gb}g",
                cpu_count=mine_config.resources.cpus,
            )

            logger.info(f"Created container: {container.name}")
            self.containers[mine_type] = container
            return container

        except docker.errors.APIError as e:
            logger.error(f"Failed to create container for {mine_type.value}: {e}")
            raise

    def start_container(self, mine_type: MineType) -> None:
        """Start a container."""
        if mine_type not in self.containers:
            raise ValueError(f"No container found for {mine_type.value}")

        container = self.containers[mine_type]
        logger.info(f"Starting container: {container.name}")
        container.start()

    def stop_container(self, mine_type: MineType, timeout: int = 30) -> None:
        """Stop a container."""
        if mine_type not in self.containers:
            logger.warning(f"No container found for {mine_type.value}")
            return

        container = self.containers[mine_type]
        logger.info(f"Stopping container: {container.name}")
        container.stop(timeout=timeout)

    def remove_container(self, mine_type: MineType, force: bool = False) -> None:
        """Remove a container."""
        if mine_type not in self.containers:
            logger.warning(f"No container found for {mine_type.value}")
            return

        container = self.containers[mine_type]
        logger.info(f"Removing container: {container.name}")
        container.remove(force=force)
        del self.containers[mine_type]

    def execute_command(
        self,
        mine_type: MineType,
        command: str,
        workdir: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        stream: bool = True
    ) -> tuple[int, str]:
        """
        Execute command inside container.

        Args:
            mine_type: Mine type
            command: Command to execute
            workdir: Working directory
            environment: Environment variables
            stream: Stream output

        Returns:
            Tuple of (exit_code, output)
        """
        if mine_type not in self.containers:
            raise ValueError(f"No container found for {mine_type.value}")

        container = self.containers[mine_type]
        logger.info(f"Executing in {container.name}: {command}")

        exec_result = container.exec_run(
            cmd=command,
            workdir=workdir,
            environment=environment,
            stream=stream,
            demux=True
        )

        if stream:
            output_lines = []
            for stdout, stderr in exec_result.output:
                if stdout:
                    line = stdout.decode('utf-8')
                    logger.info(line.rstrip())
                    output_lines.append(line)
                if stderr:
                    line = stderr.decode('utf-8')
                    logger.error(line.rstrip())
                    output_lines.append(line)
            output = ''.join(output_lines)
        else:
            output = exec_result.output.decode('utf-8')
            logger.info(output)

        return exec_result.exit_code, output

    def get_container_status(self, mine_type: MineType) -> str:
        """Get container status."""
        if mine_type not in self.containers:
            return "not_created"

        container = self.containers[mine_type]
        container.reload()
        return container.status

    def get_container_logs(
        self,
        mine_type: MineType,
        tail: int = 100,
        follow: bool = False
    ) -> str:
        """Get container logs."""
        if mine_type not in self.containers:
            raise ValueError(f"No container found for {mine_type.value}")

        container = self.containers[mine_type]
        logs = container.logs(tail=tail, follow=follow, stream=follow)

        if follow:
            for line in logs:
                logger.info(line.decode('utf-8').rstrip())
            return ""
        else:
            return logs.decode('utf-8')

    def cleanup(self, mine_type: Optional[MineType] = None) -> None:
        """
        Cleanup containers and resources.

        Args:
            mine_type: Specific mine to cleanup, or None for all
        """
        if mine_type:
            mines_to_cleanup = [mine_type]
        else:
            mines_to_cleanup = list(self.containers.keys())

        for mt in mines_to_cleanup:
            try:
                self.stop_container(mt)
                self.remove_container(mt, force=True)
            except Exception as e:
                logger.warning(f"Error cleaning up {mt.value}: {e}")

    def create_network(self, network_name: str = "intermine-network") -> None:
        """Create Docker network if it doesn't exist."""
        try:
            self.client.networks.get(network_name)
            logger.info(f"Network {network_name} already exists")
        except docker.errors.NotFound:
            logger.info(f"Creating network: {network_name}")
            self.client.networks.create(network_name, driver="bridge")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources."""
        self.cleanup()
