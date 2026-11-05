"""
src/production/profile.py - Target Environment & Production Profiler.

Phase 11.8: Production Readiness Intelligence.
Discovers and configures the target deployment profile:
- Scales production standards appropriately (LOCAL_DEV / DEMO vs STANDARD_PROD / ENTERPRISE_PROD).
- Establishes profile-specific requirements for security, database, backups, and observability.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    EnvironmentProfile,
    TargetEnvironmentConfig,
)

log = logging.getLogger("crusor.production.profile")


class EnvironmentProfiler:
    """
    Determines and manages target environment deployment profiles.
    """

    PROFILE_REQUIREMENTS: Dict[EnvironmentProfile, Dict[str, Any]] = {
        EnvironmentProfile.LOCAL_DEV: {
            "require_https": False,
            "require_auth_rotation": False,
            "require_backups": False,
            "require_tested_restore": False,
            "require_structured_logs": False,
            "require_cicd_pipeline": False,
            "require_rate_limiting": False,
            "allow_mock_dependencies": True,
            "max_tolerated_severity": "HIGH",
        },
        EnvironmentProfile.INTERNAL_TEST: {
            "require_https": False,
            "require_auth_rotation": False,
            "require_backups": False,
            "require_tested_restore": False,
            "require_structured_logs": True,
            "require_cicd_pipeline": True,
            "require_rate_limiting": False,
            "allow_mock_dependencies": True,
            "max_tolerated_severity": "MEDIUM",
        },
        EnvironmentProfile.DEMO: {
            "require_https": True,
            "require_auth_rotation": False,
            "require_backups": False,
            "require_tested_restore": False,
            "require_structured_logs": True,
            "require_cicd_pipeline": False,
            "require_rate_limiting": True,
            "allow_mock_dependencies": False,
            "max_tolerated_severity": "HIGH",
        },
        EnvironmentProfile.STAGING: {
            "require_https": True,
            "require_auth_rotation": True,
            "require_backups": True,
            "require_tested_restore": False,
            "require_structured_logs": True,
            "require_cicd_pipeline": True,
            "require_rate_limiting": True,
            "allow_mock_dependencies": False,
            "max_tolerated_severity": "LOW",
        },
        EnvironmentProfile.SMALL_PROD: {
            "require_https": True,
            "require_auth_rotation": False,
            "require_backups": True,
            "require_tested_restore": False,
            "require_structured_logs": True,
            "require_cicd_pipeline": True,
            "require_rate_limiting": True,
            "allow_mock_dependencies": False,
            "max_tolerated_severity": "LOW",
        },
        EnvironmentProfile.STANDARD_PROD: {
            "require_https": True,
            "require_auth_rotation": True,
            "require_backups": True,
            "require_tested_restore": True,
            "require_structured_logs": True,
            "require_cicd_pipeline": True,
            "require_rate_limiting": True,
            "allow_mock_dependencies": False,
            "max_tolerated_severity": "INFORMATIONAL",
        },
        EnvironmentProfile.ENTERPRISE_PROD: {
            "require_https": True,
            "require_auth_rotation": True,
            "require_backups": True,
            "require_tested_restore": True,
            "require_structured_logs": True,
            "require_cicd_pipeline": True,
            "require_rate_limiting": True,
            "allow_mock_dependencies": False,
            "max_tolerated_severity": "INFORMATIONAL",
            "require_multi_region": True,
            "require_soc2_audits": True,
        },
        EnvironmentProfile.REGULATED_PROD: {
            "require_https": True,
            "require_auth_rotation": True,
            "require_backups": True,
            "require_tested_restore": True,
            "require_structured_logs": True,
            "require_cicd_pipeline": True,
            "require_rate_limiting": True,
            "allow_mock_dependencies": False,
            "max_tolerated_severity": "INFORMATIONAL",
            "require_encryption_at_rest": True,
            "require_pii_tokenization": True,
        },
    }

    def infer_profile_from_context(
        self,
        task_prompt: str,
        specification: Optional[Any] = None,
        blueprint: Optional[Any] = None,
    ) -> TargetEnvironmentConfig:
        """
        Infers the most appropriate target environment configuration from user prompt and specifications.
        """
        text = task_prompt.lower()
        if specification and hasattr(specification, "intent"):
            text += " " + str(specification.intent).lower()
        if specification and hasattr(specification, "description"):
            text += " " + str(specification.description).lower()

        # Check explicit keywords
        if "enterprise" in text or "compliance" in text or "soc2" in text or "hipaa" in text:
            profile = EnvironmentProfile.ENTERPRISE_PROD
            users = 50000
            concurrent = 5000
            rpm = 25000
            sla = 99.99
            budget = 1500.0
        elif "regulated" in text or "financial" in text or "banking" in text:
            profile = EnvironmentProfile.REGULATED_PROD
            users = 20000
            concurrent = 2000
            rpm = 10000
            sla = 99.99
            budget = 1200.0
        elif "prototype" in text or "local" in text or "experiment" in text or "toy" in text:
            profile = EnvironmentProfile.LOCAL_DEV
            users = 1
            concurrent = 1
            rpm = 10
            sla = 90.0
            budget = 0.0
        elif "demo" in text or "showcase" in text or "presentation" in text:
            profile = EnvironmentProfile.DEMO
            users = 50
            concurrent = 10
            rpm = 50
            sla = 95.0
            budget = 20.0
        elif "staging" in text or "testnet" in text:
            profile = EnvironmentProfile.STAGING
            users = 500
            concurrent = 50
            rpm = 300
            sla = 99.0
            budget = 100.0
        elif "small" in text or "mvp" in text or "startup" in text:
            profile = EnvironmentProfile.SMALL_PROD
            users = 1000
            concurrent = 100
            rpm = 500
            sla = 99.5
            budget = 150.0
        else:
            profile = EnvironmentProfile.STANDARD_PROD
            users = 5000
            concurrent = 500
            rpm = 2500
            sla = 99.9
            budget = 350.0

        return TargetEnvironmentConfig(
            profile=profile,
            expected_users=users,
            concurrent_users=concurrent,
            request_volume_rpm=rpm,
            availability_sla_pct=sla,
            budget_monthly_usd=budget,
        )

    def get_profile_rules(self, profile: EnvironmentProfile) -> Dict[str, Any]:
        """Returns the specific requirement rules for a profile."""
        return self.PROFILE_REQUIREMENTS.get(profile, self.PROFILE_REQUIREMENTS[EnvironmentProfile.STANDARD_PROD])

