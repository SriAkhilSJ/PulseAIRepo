"""Platform detection and build/test/e2e recipes for non-web project types."""
from src.platforms.detect import (  # noqa: F401
    PLATFORMS, PlatformProject, Recipe, detect_platforms, recipe_for,
    missing_requirements, exit_code_of,
)
