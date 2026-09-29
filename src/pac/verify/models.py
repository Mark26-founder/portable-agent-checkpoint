"""Data models for PAC Verification Engine."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from pac.checkpoint import Checkpoint, Evidence


@dataclass
class EvidenceVerification:
    claim: str
    source: str
    status: str  # VERIFIED, OBSERVED, AGENT_REPORTED, UNKNOWN, STALE
    detail: Optional[str] = None
    verification_basis: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "claim": self.claim,
            "source": self.source,
            "status": self.status,
        }
        if self.detail:
            d["detail"] = self.detail
        if self.verification_basis:
            d["verification_basis"] = self.verification_basis
        return d


@dataclass
class VerificationResult:
    checkpoint_path: str
    checkpoint: Checkpoint
    current_git_commit: str
    current_git_dirty: bool
    is_git_repo: bool
    is_stale: bool
    overall_status: str  # FULLY_VERIFIED, PARTIALLY_VERIFIED, STALE, UNVERIFIED
    evidence_results: List[EvidenceVerification] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_path": self.checkpoint_path,
            "checkpoint_version": self.checkpoint.version,
            "project_name": self.checkpoint.project.name,
            "current_git_commit": self.current_git_commit,
            "current_git_dirty": self.current_git_dirty,
            "is_git_repo": self.is_git_repo,
            "is_stale": self.is_stale,
            "overall_status": self.overall_status,
            "evidence_results": [e.to_dict() for e in self.evidence_results],
            "errors": self.errors,
        }
