"""
Mine Configuration Module

Defines configuration for each InterMine instance (AllianceMine, WormMine, MouseMine, FlyMine).
Includes build parameters, data sources, RDS connection details, and resource requirements.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class MineType(Enum):
    """Supported InterMine types."""
    ALLIANCEMINE = "alliancemine"
    WORMMINE = "wormmine"
    MOUSEMINE = "mousemine"
    FLYMINE = "flymine"


class BuildStage(Enum):
    """InterMine build stages in order."""
    BUILD_DB = "buildDB"
    EXTRACT_DATA = "extract_data"
    PROJECT_BUILD = "project_build"
    POST_PROCESS = "postprocess"
    BUILD_USER_DB = "buildUserDB"
    BUILD_WAR = "war"
    DEPLOY = "cargoRedeployRemote"


@dataclass
class DataSource:
    """Configuration for a data source."""
    name: str
    source_type: str  # e.g., "fms", "custom", "url"
    location: Optional[str] = None  # URL, file path, or FMS endpoint
    required: bool = True
    description: Optional[str] = None


@dataclass
class ResourceLimits:
    """Resource limits for mine build container."""
    memory_gb: int
    cpus: int
    heap_size_gb: int
    gradle_heap_gb: int
    postgres_connections: int = 20
    profile_connections: int = 5


@dataclass
class MineConfig:
    """Complete configuration for an InterMine instance."""

    # Basic identification
    mine_type: MineType
    display_name: str
    release_version: str

    # Repository information
    repo_url: str
    repo_branch: str = "master"
    bio_sources_url: Optional[str] = None
    bio_sources_branch: str = "master"

    # Database configuration
    db_name: str
    profile_db_name: str

    # Resource limits
    resources: ResourceLimits

    # Data sources
    data_sources: List[DataSource] = field(default_factory=list)

    # Build configuration
    build_stages: List[BuildStage] = field(default_factory=lambda: list(BuildStage))
    skip_stages: List[BuildStage] = field(default_factory=list)

    # Docker configuration
    docker_image: str = ""
    docker_context: str = ""
    tomcat_port: int = 8080

    # Custom data directory (for pre-provided data like WormMine)
    custom_data_dir: Optional[str] = None
    use_custom_data: bool = False

    def __post_init__(self):
        """Set derived values after initialization."""
        if not self.docker_image:
            self.docker_image = f"{self.mine_type.value}-rds:latest"
        if not self.docker_context:
            self.docker_context = f"./docker/multi_mine_rds/{self.mine_type.value}"


# Predefined configurations for each mine
ALLIANCEMINE_CONFIG = MineConfig(
    mine_type=MineType.ALLIANCEMINE,
    display_name="AllianceMine",
    release_version="8.2.0",
    repo_url="https://github.com/alliance-genome/alliancemine.git",
    repo_branch="master",
    bio_sources_url="https://github.com/alliance-genome/alliancemine-bio-sources.git",
    bio_sources_branch="master",
    db_name="alliancemine_db",
    profile_db_name="alliancemine_profiles_db",
    resources=ResourceLimits(
        memory_gb=32,
        cpus=8,
        heap_size_gb=16,
        gradle_heap_gb=16,
        postgres_connections=20,
        profile_connections=5
    ),
    data_sources=[
        DataSource(
            name="gene-basic",
            source_type="fms",
            location="https://fms.alliancegenome.org/api/datafile",
            description="Basic gene information"
        ),
        DataSource(
            name="allele",
            source_type="fms",
            location="https://fms.alliancegenome.org/api/datafile",
            description="Allele data"
        ),
        DataSource(
            name="disease",
            source_type="fms",
            location="https://fms.alliancegenome.org/api/datafile",
            description="Disease annotations"
        ),
        DataSource(
            name="phenotype",
            source_type="fms",
            location="https://fms.alliancegenome.org/api/datafile",
            description="Phenotype annotations"
        ),
        DataSource(
            name="orthology",
            source_type="fms",
            location="https://fms.alliancegenome.org/api/datafile",
            description="Orthology relationships"
        ),
        DataSource(
            name="go-annotation",
            source_type="fms",
            location="https://fms.alliancegenome.org/api/datafile",
            description="Gene Ontology annotations"
        ),
    ],
    tomcat_port=8080
)


WORMMINE_CONFIG = MineConfig(
    mine_type=MineType.WORMMINE,
    display_name="WormMine",
    release_version="WS290",
    repo_url="https://github.com/WormBase/wormmine.git",
    repo_branch="master",
    bio_sources_url="https://github.com/WormBase/wormmine-bio-sources.git",
    bio_sources_branch="master",
    db_name="wormmine_db",
    profile_db_name="wormmine_profiles_db",
    resources=ResourceLimits(
        memory_gb=24,
        cpus=6,
        heap_size_gb=12,
        gradle_heap_gb=12,
        postgres_connections=15,
        profile_connections=5
    ),
    data_sources=[
        DataSource(
            name="annotations",
            source_type="custom",
            description="C. elegans genome annotations (GFF3)"
        ),
        DataSource(
            name="gene_association",
            source_type="custom",
            description="GO annotations (GAF)"
        ),
        DataSource(
            name="orthologs",
            source_type="custom",
            description="Orthology data"
        ),
        DataSource(
            name="alleles",
            source_type="custom",
            description="Genetic variations"
        ),
        DataSource(
            name="rnai_phenotypes",
            source_type="custom",
            description="RNAi phenotypes"
        ),
        DataSource(
            name="interactions",
            source_type="custom",
            description="Protein interactions"
        ),
    ],
    tomcat_port=8081,
    use_custom_data=True,
    custom_data_dir="./wormmine/custom_data"
)


MOUSEMINE_CONFIG = MineConfig(
    mine_type=MineType.MOUSEMINE,
    display_name="MouseMine",
    release_version="1.10",
    repo_url="https://github.com/MGI-MouseMine/mousemine.git",
    repo_branch="master",
    bio_sources_url="https://github.com/MGI-MouseMine/mousemine-bio-sources.git",
    bio_sources_branch="master",
    db_name="mousemine_db",
    profile_db_name="mousemine_profiles_db",
    resources=ResourceLimits(
        memory_gb=28,
        cpus=7,
        heap_size_gb=14,
        gradle_heap_gb=14,
        postgres_connections=18,
        profile_connections=5
    ),
    data_sources=[
        DataSource(
            name="mgi-genes",
            source_type="url",
            location="http://www.informatics.jax.org/downloads/reports",
            description="MGI gene data"
        ),
        DataSource(
            name="mgi-phenotypes",
            source_type="url",
            location="http://www.informatics.jax.org/downloads/reports",
            description="MGI phenotype data"
        ),
        DataSource(
            name="go-annotation",
            source_type="url",
            location="http://current.geneontology.org/annotations",
            description="Mouse GO annotations"
        ),
    ],
    tomcat_port=8082
)


FLYMINE_CONFIG = MineConfig(
    mine_type=MineType.FLYMINE,
    display_name="FlyMine",
    release_version="2.0",
    repo_url="https://github.com/FlyMine/flymine.git",
    repo_branch="master",
    bio_sources_url="https://github.com/FlyMine/flymine-bio-sources.git",
    bio_sources_branch="master",
    db_name="flymine_db",
    profile_db_name="flymine_profiles_db",
    resources=ResourceLimits(
        memory_gb=26,
        cpus=6,
        heap_size_gb=13,
        gradle_heap_gb=13,
        postgres_connections=16,
        profile_connections=5
    ),
    data_sources=[
        DataSource(
            name="flybase-genes",
            source_type="url",
            location="ftp://ftp.flybase.net/releases",
            description="FlyBase gene data"
        ),
        DataSource(
            name="flybase-alleles",
            source_type="url",
            location="ftp://ftp.flybase.net/releases",
            description="FlyBase allele data"
        ),
        DataSource(
            name="go-annotation",
            source_type="url",
            location="http://current.geneontology.org/annotations",
            description="Drosophila GO annotations"
        ),
    ],
    tomcat_port=8083
)


# Registry of all mine configurations
MINE_CONFIGS: Dict[MineType, MineConfig] = {
    MineType.ALLIANCEMINE: ALLIANCEMINE_CONFIG,
    MineType.WORMMINE: WORMMINE_CONFIG,
    MineType.MOUSEMINE: MOUSEMINE_CONFIG,
    MineType.FLYMINE: FLYMINE_CONFIG,
}


def get_mine_config(mine_type: MineType) -> MineConfig:
    """Get configuration for a specific mine type."""
    return MINE_CONFIGS[mine_type]


def list_available_mines() -> List[str]:
    """List all available mine types."""
    return [mine.value for mine in MineType]
