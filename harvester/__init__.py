"""apidoc-harvester: a config-driven, self-improving API-doc extraction pipeline.

Stages: fetch -> convert (markdown) -> extract (api model) -> build_openapi -> checks.
Everything site-specific lives in a YAML config; the code here is generic.
"""
__version__ = "0.3.0"
