"""Custom exceptions for InterMine builder."""


class BuilderException(Exception):
    """Base exception for all builder errors."""
    pass


class GitOperationError(BuilderException):
    """Git operation failed."""
    pass


class GradleBuildError(BuilderException):
    """Gradle build failed."""
    pass


class DataIntegrationError(BuilderException):
    """Data integration failed."""
    pass


class DeploymentError(BuilderException):
    """Webapp deployment failed."""
    pass


class HealthCheckError(BuilderException):
    """Service health check failed."""
    pass


class ConfigurationError(BuilderException):
    """Configuration is invalid or missing."""
    pass


class TimeoutError(BuilderException):
    """Operation timed out."""
    pass
