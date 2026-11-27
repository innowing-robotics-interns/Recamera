"""Exceptions raised by the recamera package."""


class ReCameraError(Exception):
    """Base class for all recamera errors."""


class DeviceError(ReCameraError):
    """The camera could not be reached, or returned an error."""


class ManifestError(ReCameraError):
    """A bundled model folder is missing or inconsistent."""
