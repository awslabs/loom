"""AgentCore artifact bundler — packages agent source as a zip and uploads to S3.

This module contains the logic previously in deployment.py:build_agent_artifact(),
migrated into the ArtifactBundler abstraction with no behavioral changes.
"""

import logging
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone

from app.services.platforms.base import ArtifactBundler, ArtifactResult, BundleConfig

logger = logging.getLogger(__name__)


# Console scripts whose shebangs need rewriting for Linux deployment.
_KNOWN_CONSOLE_SCRIPTS: dict[str, tuple[str, str]] = {
    "opentelemetry-instrument": (
        "opentelemetry.instrumentation.auto_instrumentation",
        "run",
    ),
    "opentelemetry-bootstrap": (
        "opentelemetry.instrumentation.bootstrap",
        "run",
    ),
}


def _fix_console_script_shebangs(target_dir: str) -> None:
    """Rewrite known console scripts with a portable shebang.

    ``pip install --target`` generates scripts whose shebang points to the
    local Python interpreter (e.g. ``#!/usr/local/bin/python3.12``).  On a
    Linux-based AgentCore Runtime container this path does not exist, so the
    script fails to execute.  This function regenerates the known OTEL
    console scripts with ``#!/usr/bin/env python3``.
    """
    bin_dir = os.path.join(target_dir, "bin")
    if not os.path.isdir(bin_dir):
        return

    for script_name, (module_path, func_name) in _KNOWN_CONSOLE_SCRIPTS.items():
        script_path = os.path.join(bin_dir, script_name)
        if not os.path.exists(script_path):
            continue

        content = (
            "#!/usr/bin/env python3\n"
            "# -*- coding: utf-8 -*-\n"
            "import re\n"
            "import sys\n"
            f"from {module_path} import {func_name}\n"
            "if __name__ == '__main__':\n"
            "    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])\n"
            f"    sys.exit({func_name}())\n"
        )
        with open(script_path, "w") as f:
            f.write(content)
        os.chmod(script_path, 0o755)
        logger.info("Fixed shebang for %s", script_name)


class AgentCoreBundler(ArtifactBundler):
    """Bundles agent source into a zip artifact and uploads to S3.

    This preserves the exact behavior of the original build_agent_artifact():
    - Copies source directory
    - pip-installs requirements targeting the configured platform/python version
    - Fixes OTEL console script shebangs
    - Zips the result (excluding .pyc / __pycache__)
    - Uploads to the LOOM_ARTIFACT_BUCKET in S3
    """

    @property
    def provider_name(self) -> str:
        return "agentcore"

    def build_artifact(self, config: BundleConfig) -> ArtifactResult:
        """Build a zip artifact and upload to S3.

        Args:
            config: BundleConfig with region, source_dir, requirements, and
                    optionally python_version/target_platform overrides.

        Returns:
            ArtifactResult with location={"bucket": ..., "key": ...}

        Raises:
            ValueError: LOOM_ARTIFACT_BUCKET env var is not set.
            FileNotFoundError: source_dir or requirements path does not exist.
            RuntimeError: pip install or S3 upload failed.
        """
        import boto3

        bucket = os.environ.get("LOOM_ARTIFACT_BUCKET")
        if not bucket:
            raise ValueError("LOOM_ARTIFACT_BUCKET environment variable is not set")

        if not config.source_dir.is_dir():
            raise FileNotFoundError(f"Agent source directory not found: {config.source_dir}")
        if not config.requirements.is_file():
            raise FileNotFoundError(f"Requirements file not found: {config.requirements}")

        tmp_dir = tempfile.mkdtemp(prefix="loom-build-")
        try:
            # Copy source
            shutil.copytree(str(config.source_dir), os.path.join(tmp_dir, "src"))

            # Install dependencies targeting the configured platform
            subprocess.run(
                [
                    "pip", "install",
                    "-r", str(config.requirements),
                    "-t", tmp_dir,
                    "--quiet",
                    "--platform", config.target_platform,
                    "--only-binary=:all:",
                    "--python-version", config.python_version,
                    "--implementation", "cp",
                ],
                check=True,
                capture_output=True,
            )

            # Fix console script shebangs for Linux deployment
            _fix_console_script_shebangs(tmp_dir)

            # Create zip
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            zip_path = os.path.join(tmp_dir, "agent.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _dirs, files in os.walk(tmp_dir):
                    for fname in files:
                        if fname == "agent.zip":
                            continue
                        full_path = os.path.join(root, fname)
                        arcname = os.path.relpath(full_path, tmp_dir)
                        if arcname.endswith(".pyc") or "__pycache__" in arcname:
                            continue
                        zf.write(full_path, arcname)

            # Upload to S3
            s3_key = f"loom-artifacts/strands_agent/{timestamp}/agent.zip"
            s3 = boto3.client("s3", region_name=config.region)
            s3.upload_file(zip_path, bucket, s3_key)
            logger.info("Uploaded artifact to s3://%s/%s", bucket, s3_key)

            return ArtifactResult(
                provider=self.provider_name,
                location={"bucket": bucket, "key": s3_key},
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
