"""Custom exceptions for update-flake-inputs."""


class UpdateFlakeInputsError(Exception):
    """Base exception for update-flake-inputs."""


class FlakeServiceError(UpdateFlakeInputsError):
    """Exception raised by FlakeService operations."""


class GiteaServiceError(UpdateFlakeInputsError):
    """Exception raised by GiteaService operations."""


class APIError(GiteaServiceError):
    """Exception raised when Gitea API requests fail."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize APIError.

        Args:
            message: Error message
            status_code: HTTP status code if applicable

        """
        super().__init__(message)
        self.status_code = status_code
