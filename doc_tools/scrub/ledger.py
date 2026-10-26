"""The scrub ledger: schema, redaction, and the invariants a ledger must hold.

The design this implements was placed for review on 2026-10-22
(``invincible-agent/sessions/2026-10-22-design-from-7f-batch-fixture-scrubber-for-chris-review.md``,
§4 "The ledger — the part to review first"). The architect's overnight item 4
says *"Batch fixture: scrubber → schema PR, continue the chain."* This is that
schema.

WHY THE SCHEMA COMES BEFORE THE SCRUBBER
----------------------------------------
Four rulings still block the tokeniser and the allowlist — whether the
manufacturer name is allowlisted, whether dates are, whether the unredacted
mapping may be kept, and whether a scrubbed fixture enters the SCORED corpus.
None of them block the ledger, because **the ledger does not choose; it records
which answer the scrub ran under** (``Policy``). A fixture built under an assumed
answer is then visible in its own ledger instead of silent, and a later ruling
invalidates exactly the fixtures whose policy block disagrees with it.

THE ONE RULE THE WHOLE FILE EXISTS TO ENFORCE
---------------------------------------------
**A committed ledger carries no original value.** Every original appears as
``len=N sha256:XXXXXXXX`` — this repo's standing convention, and the reason for
it applies exactly here: a ledger that lists the originals re-identifies the
document it exists to make committable, and a transcript is not editable. A
drift script in this repo once printed three live credentials into one.

So ``Redacted`` is a validated type, not a formatting convention. A model
carrying a raw value in an ``original`` field **raises at construction**, which
is the only place the rule can be enforced for every future caller:
``ScrubLedger.model_validate(json)`` is the single door, and a ledger that was
hand-edited to paste a value back in fails to load.

MEASURED, NOT ASSERTED
----------------------
``Verification`` requires **every** check in ``CheckName`` to be present. A
missing check is a rejected ledger, not a default pass — because the failure this
guards against is a scrub that was *performed* and then described. ``NOT_RUN`` is
a legal result and makes the ledger non-committable; it is not a silent pass.
"""
from __future__ import annotations

import hashlib
import re
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional

from pydantic import (BaseModel, ConfigDict, Field, StringConstraints,
                      field_validator, model_validator)

LEDGER_VERSION = 1

#: ``len=N sha256:XXXXXXXX`` -- first 8 hex of the digest, lowercase.
REDACTION_RE = re.compile(r"^len=(0|[1-9][0-9]*) sha256:[0-9a-f]{8}$")

Redacted = Annotated[str, StringConstraints(pattern=REDACTION_RE.pattern)]

#: The shape alphabet (design §2.1): uppercase -> A, lowercase -> a,
#: digit -> 9, anything else kept literally.
_SHAPE_CLASSES = ((str.isupper, "A"), (str.islower, "a"), (str.isdigit, "9"))


def redact(value: str | bytes, *, encoding: str = "utf-8") -> str:
    """``value`` as ``len=N sha256:XXXXXXXX`` — never the value itself.

    ``len`` is the length in **bytes** of the encoded value, so a ledger entry
    for a multi-byte original is not quietly shorter than the original. The
    digest is over the same bytes, so two ledgers agree on an original without
    either naming it.
    """
    raw = value.encode(encoding) if isinstance(value, str) else value
    return f"len={len(raw)} sha256:{hashlib.sha256(raw).hexdigest()[:8]}"


def is_redacted(text: str) -> bool:
    return bool(REDACTION_RE.match(text))


def shape_of(text: str) -> str:
    """The string reduced to its shape (design §2.1).

    Punctuation, spaces and symbols are kept **literally**, which is deliberate:
    ``SOT-23`` and ``PCN24-029`` are told apart by where the hyphen sits, and the
    extractor's shape tests read exactly that.
    """
    out: List[str] = []
    for ch in text:
        for predicate, symbol in _SHAPE_CLASSES:
            if predicate(ch):
                out.append(symbol)
                break
        else:
            out.append(ch)
    return "".join(out)


def shapes_equal(original_shape: str, replacement: str) -> bool:
    """Shape-equal, not merely length-equal (design §2.2b)."""
    return shape_of(replacement) == original_shape


class SubstitutionClass(str, Enum):
    """What a substituted string WAS. Not a guess: the scrubber knows which
    column or block it took the value from, and a reviewer auditing a fixture
    needs to know whether an affected part or a customer name was replaced."""

    MPN_AFFECTED = "mpn_affected"
    MPN_REPLACEMENT = "mpn_replacement"
    MPN_ALIAS = "mpn_alias"
    CUSTOMER_NAME = "customer_name"
    CUSTOMER_PART_NUMBER = "customer_part_number"
    CONTACT_NAME = "contact_name"
    CONTACT_EMAIL = "contact_email"
    CONTACT_PHONE = "contact_phone"
    ADDRESS = "address"
    SITE_NAME = "site_name"
    INTERNAL_REFERENCE = "internal_reference"
    DISTRIBUTION_BLOCK = "distribution_block"


class AllowlistRule(str, Enum):
    """Why a string survived verbatim (design §3.1).

    ``MANUFACTURER_NAME`` and ``DATE`` are declared here although rulings 1 and 2
    have not landed: the enum says the rule EXISTS, the allowlist file says
    whether it is in force, and ``Policy`` records which way a given scrub ran.
    """

    HEADER_VOCABULARY = "header_vocabulary"
    CAPTION = "caption"
    DATE = "date"
    NOTICE_TYPE_OR_STATUS = "notice_type_or_status"
    UNIT_PACKAGE_OR_STANDARD = "unit_package_or_standard"
    MANUFACTURER_NAME = "manufacturer_name"


class CheckName(str, Enum):
    """The verification checks (design §4.3). **All of them are required.**"""

    LEAK_TEST = "leak_test"
    SHAPE_EQUALITY = "shape_equality"
    ALLOWLIST_INTEGRITY = "allowlist_integrity"
    STRUCTURE_INVARIANCE = "structure_invariance"
    EQUIVALENCE_SEAL = "equivalence_seal"
    COLLISION_CHECK = "collision_check"


class CheckResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    #: Ran, and the thing it checks could not be read at all -- the leak test on
    #: a page whose text layer is below threshold. Fails CLOSED: a ledger with a
    #: REFUSED check is not committable.
    REFUSED = "refused"
    #: Not run. Legal to record, and never a silent pass.
    NOT_RUN = "not_run"


class PolicyAnswer(str, Enum):
    ALLOWLISTED = "allowlisted"
    SCRUBBED = "scrubbed"


class MappingPolicy(str, Enum):
    #: The unredacted mapping is kept (ruling 3, option "auditable for ever").
    RETAINED = "retained"
    #: The scrub is one-way. Safer, and makes the equivalence seal unrepeatable
    #: after the fact -- which the ledger therefore has to have recorded.
    ONE_WAY = "one_way"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True,
                              populate_by_name=True, use_enum_values=False)


class SourceRef(_Strict):
    """The document that was scrubbed, named by location and digest only."""

    bucket: str
    key: str
    #: The source's own digest, redacted like everything else: a fixture's source
    #: is itself a document whose length and hash are enough to identify it to
    #: someone who already has it, and nothing to someone who does not.
    sha256: Redacted
    pages: int = Field(ge=1)
    tables: int = Field(ge=0)


class ScrubRun(_Strict):
    """How the scrub was run, so it can be reproduced or disbelieved."""

    tool_version: str
    run_at: str
    #: The NAME of the secret holding the batch salt. Never the salt.
    salt_ref: str
    allowlist_ref: str
    #: Where the unredacted mapping lives, or ``None`` for a one-way scrub. It
    #: never enters git either way.
    mapping_ref: Optional[str] = None

    @field_validator("salt_ref")
    @classmethod
    def _not_the_salt_itself(cls, v: str) -> str:
        """A salt pasted where its name belongs is the exact accident this
        repo's redaction convention exists for, and it would be committed."""
        if is_redacted(v):
            raise ValueError(
                "salt_ref is a secret NAME, not a value -- even redacted. Name "
                "the secret-manager key.")
        if re.fullmatch(r"[0-9a-fA-F]{16,}", v) or re.fullmatch(
                r"[A-Za-z0-9+/]{24,}={0,2}", v):
            raise ValueError(
                "salt_ref looks like raw entropy, not a key name. The salt must "
                "never reach the ledger.")
        return v

    @field_validator("run_at")
    @classmethod
    def _utc_instant(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", v):
            raise ValueError("run_at must be a UTC instant, e.g. "
                             "2026-10-24T13:02:11Z")
        return v


class Site(_Strict):
    """Where an occurrence was. A table cell is addressed, body text is not.

    The address matters because the same original appearing in a cell and in a
    paragraph is the case a naive per-occurrence scrub gets wrong, and it is
    also the replacement-pair case the fixture exists to test.
    """

    page: int = Field(ge=1)
    kind: str
    row: Optional[int] = Field(default=None, ge=0)
    col: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _cell_is_addressed(self) -> "Site":
        if self.kind == "table_cell" and (self.row is None or self.col is None):
            raise ValueError("a table_cell site must carry row and col")
        return self


class Substitution(_Strict):
    """One original -> replacement, with the original present only as a digest."""

    class_: SubstitutionClass = Field(alias="class")
    shape: str = Field(min_length=1)
    original: Redacted
    #: In the clear, because it is already in the fixture.
    replacement: str = Field(min_length=1)
    occurrences: int = Field(ge=1)
    sites: List[Site] = Field(min_length=1)
    #: Recorded per §2.4: the reserved space drawn from, and how many redraws a
    #: collision check forced. ``0`` is a measurement; absent is not.
    reserved_space: Optional[str] = None
    redraws: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _shape_equal_and_counted(self) -> "Substitution":
        if not shapes_equal(self.shape, self.replacement):
            raise ValueError(
                f"replacement does not have the declared shape: "
                f"declared {self.shape!r}, replacement shape "
                f"{shape_of(self.replacement)!r}. A shape-unequal replacement "
                f"means the fixture tests the scrubber, not the extractor.")
        if self.occurrences != len(self.sites):
            raise ValueError(
                f"occurrences={self.occurrences} but {len(self.sites)} sites "
                f"are listed; an uncounted occurrence is an unscrubbed one")
        return self

    def covers(self, candidate: str) -> bool:
        """True if ``candidate`` is the original this entry stands for.

        How a reviewer **with** the mapping checks a ledger that does not name
        the value. Comparing digests, never values.
        """
        return redact(candidate) == self.original


class Allowlisted(_Strict):
    """A string that survived verbatim, and the count that proves it.

    The count is the whole entry: ``Alternative Part Number`` present but
    appearing twice where the source had it three times means a header was
    scrubbed, which is the failure that makes a fixture test nothing.
    """

    text: str = Field(min_length=1)
    rule: AllowlistRule
    count: int = Field(ge=1)


class Check(_Strict):
    """One verification check with its measured result."""

    result: CheckResult
    #: What was measured. Free-form on purpose -- each check measures something
    #: different -- but it must say something: an empty detail on a PASS is an
    #: assertion wearing a measurement's clothes.
    detail: str = Field(min_length=1)
    #: Counts the check produced, e.g. ``{"pages_checked": 3, "hits": 0}``.
    measurements: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _not_run_explains_itself(self) -> "Check":
        if self.result is CheckResult.NOT_RUN and len(self.detail) < 12:
            raise ValueError(
                "a NOT_RUN check must say why it did not run; that is the whole "
                "value of recording it")
        return self


class Verification(_Strict):
    """Every check in ``CheckName``, each with a result. No defaults."""

    checks: Dict[CheckName, Check]

    @model_validator(mode="after")
    def _all_checks_present(self) -> "Verification":
        missing = [c.value for c in CheckName if c not in self.checks]
        if missing:
            raise ValueError(
                f"verification is missing {missing}. A missing check is not a "
                f"default pass -- record it as not_run with a reason.")
        return self

    @property
    def failed(self) -> List[str]:
        return [name.value for name, check in self.checks.items()
                if check.result is not CheckResult.PASS]


class Policy(_Strict):
    """Which answer to each open ruling this scrub ran under.

    This block is why the schema could land before the rulings. It does not
    decide them; it makes a fixture state its own assumptions, so a ruling that
    lands later invalidates exactly the fixtures that disagree with it — which is
    a query, not an audit.
    """

    #: Ruling 1. The sensitive party in a published PCN is the recipient, not the
    #: issuer, so the recommendation placed for review was ALLOWLISTED. Still a
    #: recommendation: the field records, it does not default.
    manufacturer_name: PolicyAnswer
    #: Ruling 2. Allowlisted keeps LTB extraction date-semantic; scrubbed means
    #: LTB scoring cannot come off this fixture at all.
    dates: PolicyAnswer
    #: Ruling 3.
    mapping: MappingPolicy
    #: Ruling 4. ``True`` moves the parts denominator, which is currently met
    #: exactly -- so a ``True`` fixture lands WITH a corpus measurement, never
    #: before one.
    enters_scored_corpus: bool
    #: The ruling text or packet this policy was taken from, so a fixture built
    #: on a recommendation is distinguishable from one built on a ruling.
    authority: str = Field(min_length=1)


class ScrubLedger(_Strict):
    """The committed ledger. One per fixture, beside it.

    ``ScrubLedger.model_validate(...)`` is the single door into this type, and
    every invariant below is enforced there rather than in the writer, because
    the reader is who has to be protected: a ledger hand-edited to paste an
    original back in must fail to LOAD.
    """

    ledger_version: int
    fixture_id: str = Field(min_length=1)
    source: SourceRef
    scrub: ScrubRun
    substitutions: List[Substitution]
    allowlisted: List[Allowlisted]
    verification: Verification
    policy: Policy

    @field_validator("ledger_version")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v != LEDGER_VERSION:
            raise ValueError(
                f"ledger_version {v} is not {LEDGER_VERSION}; a reader that "
                f"guesses at an unknown version is how a schema change becomes "
                f"a silent misread")
        return v

    @model_validator(mode="after")
    def _coherent(self) -> "ScrubLedger":
        # The mapping policy and the mapping reference must agree. A one-way
        # scrub that names a mapping either kept one or is lying about which.
        retained = self.policy.mapping is MappingPolicy.RETAINED
        if retained and not self.scrub.mapping_ref:
            raise ValueError(
                "policy.mapping is retained but scrub.mapping_ref is empty")
        if not retained and self.scrub.mapping_ref:
            raise ValueError(
                "policy.mapping is one_way but scrub.mapping_ref names a "
                "mapping; a one-way scrub keeps no re-identification key")

        # An original may stand for exactly one replacement, and a replacement
        # for exactly one original: the mapping is injective within a batch
        # (design §2.2a), and a ledger is where that is checkable.
        originals = [s.original for s in self.substitutions]
        if len(set(originals)) != len(originals):
            raise ValueError(
                "the same original appears in two substitutions; within a batch "
                "the mapping must be deterministic, so merge the sites instead")
        replacements = [s.replacement for s in self.substitutions]
        if len(set(replacements)) != len(replacements):
            raise ValueError(
                "two originals map to the same replacement; the mapping must be "
                "injective or the fixture conflates two parts into one")

        # A replacement that is literally an allowlisted string would scrub a
        # header into the parts column, or a part into a header.
        allowed = {a.text for a in self.allowlisted}
        collided = sorted(set(replacements) & allowed)
        if collided:
            raise ValueError(
                f"replacement(s) {collided} are allowlisted strings; the "
                f"allowlist wins over substitution (design §3.3), and a "
                f"replacement landing on one inverts that precedence")
        return self

    # ------------------------------------------------------------------
    @property
    def committable(self) -> bool:
        """Whether this ledger's fixture may be committed.

        **Every check must have PASSED.** A ``REFUSED`` leak test — the
        text-layer-below-threshold case — fails closed: the scrubber refuses a
        document it cannot read rather than shipping one it did not scrub. Image-
        borne text is the known hole, and a PDF whose parts live inside an image
        is precisely the document this property must say no to.
        """
        return not self.verification.failed

    def why_not_committable(self) -> str:
        failed = self.verification.failed
        if not failed:
            return ""
        return "verification not passed: " + ", ".join(sorted(failed))

    def substitution_for(self, original: str) -> Optional[Substitution]:
        """Look up by VALUE, for a reviewer who holds the mapping. Compares
        digests; the value never enters the ledger or its index."""
        target = redact(original)
        for sub in self.substitutions:
            if sub.original == target:
                return sub
        return None
