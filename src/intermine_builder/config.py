"""Configuration management for AGR InterMine Builder.

This module provides centralized configuration for all components of the
InterMine build system, including database connections, AWS resources,
and build parameters.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
import json
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv()


@dataclass
class DatabaseConfig:
    """PostgreSQL database configuration."""

    user: str = "postgres"
    password: str = "postgres"
    host: str = "postgres"
    port: int = 5432
    database: str = "intermine"

    def connection_string(self, database: Optional[str] = None) -> str:
        """Generate PostgreSQL connection string."""
        db = database or self.database
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{db}"


@dataclass
class RDSConfig:
    """AWS RDS configuration."""

    identifier: str = "agr-intermine-cluster"
    region: str = "us-east-1"
    parameter_group: str = "intermine-pg13"
    security_group: Optional[str] = None
    subnet_group: Optional[str] = None

    # Storage
    storage_gb: int = 100
    storage_type: str = "gp3"
    iops: int = 3000

    # Instance sizing
    normal_size: str = "db.t4g.medium"
    build_size: str = "db.r6g.large"
    heavy_build_size: str = "db.r6g.xlarge"

    # Backup
    backup_retention_days: int = 7
    backup_window: str = "03:00-04:00"
    maintenance_window: str = "sun:04:00-sun:05:00"

    # Multi-AZ
    multi_az: bool = False

    # Cost tracking
    hourly_rate_normal: float = 0.072  # t4g.medium
    hourly_rate_build: float = 0.144   # r6g.large
    hourly_rate_heavy: float = 0.288   # r6g.xlarge


@dataclass
class DockerConfig:
    """Docker and container configuration."""

    registry: str = "local"
    image_tag: str = "stage"
    network: str = "intermine"

    # ECR registry (if using AWS)
    ecr_registry: Optional[str] = None  # e.g., "100225593120.dkr.ecr.us-east-1.amazonaws.com"

    # Resource limits
    postgres_memory: str = "4g"
    postgres_cpu: int = 2
    builder_memory: str = "8g"
    builder_cpu: int = 4
    solr_memory: str = "4g"
    solr_cpu: int = 2
    tomcat_memory: str = "4g"
    tomcat_cpu: int = 2


@dataclass
class EC2BuildConfig:
    """EC2 builder instance configuration for Step Functions."""

    # Instance sizing
    instance_type: str = "r6i.2xlarge"  # 8 vCPU, 64 GB RAM
    storage_gb: int = 500
    iops: int = 10000
    throughput_mbps: int = 500

    # Memory allocation (64GB total)
    gradle_heap_gb: int = 32
    postgres_shared_buffers_gb: int = 16
    file_cache_gb: int = 12
    os_overhead_gb: int = 4

    # AMI
    ami_id: Optional[str] = None  # Custom AMI with dependencies
    ami_name: str = "agr-intermine-builder-v1"

    # Lifecycle
    auto_terminate: bool = True
    max_build_hours: int = 10  # Safety timeout

    # Cost optimization
    use_spot_instances: bool = False
    spot_max_price: float = 0.30  # 60% of on-demand (~$0.504/hr)


@dataclass
class InterMineConfig:
    """InterMine build configuration."""

    # Repository URLs
    intermine_repo_url: str = "https://github.com/intermine/intermine"
    intermine_branch: str = "master"

    mine_repo_url: str = "https://github.com/alliance-genome/alliancemine"
    mine_branch: str = "master"
    mine_name: str = "alliancemine"

    biosources_repo_url: Optional[str] = None
    biosources_branch: str = "master"

    # Build settings
    data_dir: str = "/data"
    build_dir: str = "/root"

    # Tomcat
    tomcat_host: str = "tomcat"
    tomcat_port: int = 8080
    tomcat_user: str = "tomcat"
    tomcat_password: str = "tomcat"

    # Solr
    solr_host: str = "solr"
    solr_port: int = 8983


@dataclass
class AllianceConfig:
    """Alliance of Genome Resources specific configuration."""

    release_version: str = "8.2.0"

    # S3 bucket for data and builds
    s3_bucket: str = "agr-intermine-builds"
    s3_path: str = "releases"

    # Solr endpoints
    stage_solr: str = "stage-intermine-solr.alliancegenome.org"
    prod_solr: str = "intermine-solr.alliancegenome.org"


@dataclass
class Config:
    """Main configuration class for AGR InterMine Builder.

    This class aggregates all configuration sections and provides
    convenience methods for loading from various sources.

    Example:
        # Load from environment variables
        config = Config.from_env()

        # Access configuration
        print(config.database.connection_string())
        print(config.rds.identifier)

        # Override specific values
        config = Config.from_env(
            rds_identifier="custom-instance"
        )
    """

    # Configuration sections
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    rds: RDSConfig = field(default_factory=RDSConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    ec2_build: EC2BuildConfig = field(default_factory=EC2BuildConfig)
    intermine: InterMineConfig = field(default_factory=InterMineConfig)
    alliance: AllianceConfig = field(default_factory=AllianceConfig)

    # General settings
    environment: str = "stage"  # stage, production, development
    log_level: str = "INFO"
    debug: bool = False

    # Paths
    project_root: Path = field(default_factory=lambda: Path.cwd())

    @classmethod
    def from_env(cls, **overrides) -> "Config":
        """Load configuration from environment variables.

        Environment variables override default values. The naming convention is:
        - DATABASE_USER, DATABASE_PASSWORD, DATABASE_HOST, etc.
        - RDS_IDENTIFIER, RDS_REGION, RDS_STORAGE_GB, etc.
        - DOCKER_REGISTRY, DOCKER_IMAGE_TAG, etc.

        Args:
            **overrides: Additional overrides to apply after loading from env

        Returns:
            Config instance with values from environment

        Example:
            config = Config.from_env(environment="production")
        """
        # Database config - prioritize RDS_* env vars, fall back to POSTGRES_* or DB_*
        database = DatabaseConfig(
            user=os.getenv("RDS_USER", os.getenv("POSTGRES_USER", "postgres")),
            password=os.getenv("RDS_PASSWORD", os.getenv("POSTGRES_PASSWORD", "postgres")),
            host=os.getenv("RDS_HOST", os.getenv("POSTGRES_HOST", os.getenv("DB_HOST", "postgres"))),
            port=int(os.getenv("RDS_PORT", os.getenv("POSTGRES_PORT", os.getenv("DB_PORT", "5432")))),
            database=os.getenv("POSTGRES_DB", "intermine"),
        )

        # RDS config
        rds = RDSConfig(
            identifier=os.getenv("RDS_IDENTIFIER", "agr-intermine-cluster"),
            region=os.getenv("AWS_REGION", os.getenv("RDS_REGION", "us-east-1")),
            parameter_group=os.getenv("RDS_PARAMETER_GROUP", "intermine-pg13"),
            security_group=os.getenv("RDS_SECURITY_GROUP"),
            subnet_group=os.getenv("RDS_SUBNET_GROUP"),
            storage_gb=int(os.getenv("RDS_STORAGE_GB", "100")),
            normal_size=os.getenv("RDS_NORMAL_SIZE", "db.t4g.medium"),
            build_size=os.getenv("RDS_BUILD_SIZE", "db.r6g.large"),
        )

        # Docker config
        docker = DockerConfig(
            registry=os.getenv("DOCKER_REGISTRY", "local"),
            image_tag=os.getenv("IMAGE_TAG", "stage"),
            network=os.getenv("DOCKER_NETWORK", "intermine"),
            ecr_registry=os.getenv("ECR_REGISTRY"),
            postgres_memory=os.getenv("POSTGRES_MEMORY", "4g"),
            postgres_cpu=int(os.getenv("POSTGRES_CPU", "2")),
            builder_memory=os.getenv("BUILDER_MEMORY", "8g"),
            builder_cpu=int(os.getenv("BUILDER_CPU", "4")),
            solr_memory=os.getenv("SOLR_MEMORY", "4g"),
            solr_cpu=int(os.getenv("SOLR_CPU", "2")),
            tomcat_memory=os.getenv("TOMCAT_MEMORY", "4g"),
            tomcat_cpu=int(os.getenv("TOMCAT_CPU", "2")),
        )

        # InterMine config
        intermine = InterMineConfig(
            intermine_repo_url=os.getenv("IM_REPO_URL", "https://github.com/intermine/intermine"),
            intermine_branch=os.getenv("IM_REPO_BRANCH", "master"),
            mine_repo_url=os.getenv("MINE_REPO_URL", "https://github.com/alliance-genome/alliancemine"),
            mine_branch=os.getenv("MINE_BRANCH", "master"),
            mine_name=os.getenv("MINE_NAME", "alliancemine"),
            biosources_repo_url=os.getenv("BIOSOURCES_REPO_URL"),
            biosources_branch=os.getenv("BIOSOURCES_BRANCH", "master"),
            data_dir=os.getenv("IM_DATA_DIR", "/data"),
            tomcat_host=os.getenv("TOMCAT_HOST", "tomcat"),
            tomcat_port=int(os.getenv("TOMCAT_PORT", "8080")),
            tomcat_user=os.getenv("TOMCAT_USER", "tomcat"),
            tomcat_password=os.getenv("TOMCAT_PWD", "tomcat"),
            solr_host=os.getenv("SOLR_HOST", "solr"),
        )

        # Alliance config
        alliance = AllianceConfig(
            release_version=os.getenv("ALLIANCE_RELEASE", "8.2.0"),
            s3_bucket=os.getenv("S3_BUCKET", "agr-intermine-builds"),
            s3_path=os.getenv("S3_PATH", "releases"),
        )

        # General settings
        environment = os.getenv("ENVIRONMENT", "stage")
        log_level = os.getenv("LOG_LEVEL", "INFO")
        debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

        # Create config instance
        config = cls(
            database=database,
            rds=rds,
            docker=docker,
            intermine=intermine,
            alliance=alliance,
            environment=environment,
            log_level=log_level,
            debug=debug,
        )

        # Apply overrides
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)
            else:
                # Try to set nested attributes (e.g., rds_identifier -> config.rds.identifier)
                parts = key.split('_', 1)
                if len(parts) == 2 and hasattr(config, parts[0]):
                    section = getattr(config, parts[0])
                    if hasattr(section, parts[1]):
                        setattr(section, parts[1], value)

        return config

    @classmethod
    def from_file(cls, filepath: Path) -> "Config":
        """Load configuration from a JSON or Python file.

        Args:
            filepath: Path to configuration file (.json or .py)

        Returns:
            Config instance loaded from file
        """
        filepath = Path(filepath)

        if filepath.suffix == '.json':
            with open(filepath) as f:
                data = json.load(f)
                return cls.from_dict(data)
        else:
            raise ValueError(f"Unsupported config file format: {filepath.suffix}")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Create Config from dictionary.

        Args:
            data: Dictionary with configuration values

        Returns:
            Config instance
        """
        # Extract nested configs
        database = DatabaseConfig(**data.get('database', {}))
        rds = RDSConfig(**data.get('rds', {}))
        docker = DockerConfig(**data.get('docker', {}))
        ec2_build = EC2BuildConfig(**data.get('ec2_build', {}))
        intermine = InterMineConfig(**data.get('intermine', {}))
        alliance = AllianceConfig(**data.get('alliance', {}))

        return cls(
            database=database,
            rds=rds,
            docker=docker,
            ec2_build=ec2_build,
            intermine=intermine,
            alliance=alliance,
            environment=data.get('environment', 'stage'),
            log_level=data.get('log_level', 'INFO'),
            debug=data.get('debug', False),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary.

        Returns:
            Dictionary representation of configuration
        """
        return {
            'database': {
                'user': self.database.user,
                'password': '***',  # Masked
                'host': self.database.host,
                'port': self.database.port,
                'database': self.database.database,
            },
            'rds': {
                'identifier': self.rds.identifier,
                'region': self.rds.region,
                'storage_gb': self.rds.storage_gb,
                'normal_size': self.rds.normal_size,
                'build_size': self.rds.build_size,
            },
            'docker': {
                'registry': self.docker.registry,
                'image_tag': self.docker.image_tag,
                'network': self.docker.network,
            },
            'intermine': {
                'mine_name': self.intermine.mine_name,
                'mine_repo_url': self.intermine.mine_repo_url,
                'tomcat_host': self.intermine.tomcat_host,
                'solr_host': self.intermine.solr_host,
            },
            'alliance': {
                'release_version': self.alliance.release_version,
                's3_bucket': self.alliance.s3_bucket,
            },
            'environment': self.environment,
            'log_level': self.log_level,
            'debug': self.debug,
        }

    def validate(self) -> tuple[bool, list[str]]:
        """Validate configuration.

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        # Validate database config
        if not self.database.password or self.database.password == "":
            errors.append("Database password is required")

        # Validate RDS config
        if self.rds.storage_gb < 20:
            errors.append("RDS storage must be at least 20 GB")

        # Validate paths
        if not self.intermine.mine_repo_url:
            errors.append("Mine repository URL is required")

        return len(errors) == 0, errors

    def __str__(self) -> str:
        """String representation (safe, no passwords)."""
        return f"""Config(
    environment={self.environment}
    database={self.database.host}:{self.database.port}
    rds={self.rds.identifier} ({self.rds.region})
    mine={self.intermine.mine_name}
    release={self.alliance.release_version}
)"""


# Convenience function for quick access
def load_config(**overrides) -> Config:
    """Load configuration from environment with optional overrides.

    This is a convenience function that wraps Config.from_env().

    Args:
        **overrides: Configuration overrides

    Returns:
        Config instance

    Example:
        from src.intermine_builder.config import load_config

        config = load_config(environment="production")
    """
    return Config.from_env(**overrides)
