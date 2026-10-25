import os
import re
from lxml import etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from doc_tools.parsers.dmc_canonicalizer import assemble_canonical_dmc
from doc_tools.parsers.mil_info_code_map import (
    DATA_MODULE_ROOT,
    classify_data_module,
)

# Characters kept in a URI-local fragment. Hyphen and dot are preserved on
# purpose, unlike the sibling parsers' `[^a-zA-Z0-9_]` scrub: in S1000D a part
# number's hyphens are significant (ODM-SE-0001 and ODMSE-0001 are different
# parts), and both characters are legal in a URI fragment, so stripping them
# only loses information. Everything else — spaces included, which would make
# the Turtle unserializable — is replaced.
_FRAGMENT_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
# NOTE: `doc_tools/utils/xml_chunks.py` keeps a COPY of this character class.
# It has to rebuild a planning section's key from the node's rdfs:label (the
# URI is mpsection-{scope}-{key} and a doc scope may itself contain hyphens,
# so the prefix cannot be stripped), and it must arrive at the same key or a
# chunk's `section` stops matching the graph anchor it cites. Copied rather
# than imported on purpose: that chunker is parser-agnostic by design and
# serves the IADS and 40051 builders too, so importing one parser's private
# helper into it would be the worse coupling. If this class changes, change
# it there as well -- the drift is caught, by the pinned local names in
# test_mrad_320a_planning_sections_carry_prose_and_the_interval and the
# pinned section strings in test_mrad_320a_chunks_the_planning_prose, but it
# is caught in two files at once and this is the note that explains why.

# Used when a builder is constructed with no doc_id (the bare
# `S1000dGraphBuilder()` form the unit tests use). Explicit, so an unscoped
# subject is READABLE AS unscoped in the graph rather than looking like a
# document called "". Nothing on the ingest path hits this: xml_ingestion.py
# always derives doc_id from the S3 key.
UNSCOPED_DOC_SLUG = "nodoc"


def _fragment(value: str) -> str:
    """Make `value` safe to splice into a URI local name."""
    return _FRAGMENT_UNSAFE.sub("_", value.strip())


_WHITESPACE_RUN = re.compile(r"\s+")


def _collapse_ws(value: str) -> str:
    """Collapse whitespace runs in element text.

    Needed, not cosmetic: S1000D authoring tools hard-wrap a <para> at the
    column and indent the continuation, so the raw text of a step in the MRAD
    corpus arrives as "Install the two mounting screws using the array module
    extraction tool,\n          ODM-SE-0001." A literal carrying that newline
    and run of spaces does not compare equal to the same sentence anywhere
    else, and a renderer shows the wrap.
    """
    return _WHITESPACE_RUN.sub(" ", value).strip()


class S1000dGraphBuilder:
    """
    Generic parser that ingests S1000D XML Data Modules and converts them
    into a formal RDF Knowledge Graph using a unified MIL ontology.
    """

    def __init__(self, bucket: str = "", doc_id: str = "", image_prefix: str = ""):
        self.graph = Graph()
        self.bucket = bucket
        self.doc_id = doc_id
        self.image_prefix = image_prefix
        # Define the unified MIL namespace (shared with DITA and IADS)
        self.MIL = Namespace('http://edgy-solutions.com/ontology/mil#')

        # Bind namespaces for prettier serialization
        self.graph.bind("mil", self.MIL)
        self.graph.bind("rdf", RDF)
        self.graph.bind("rdfs", RDFS)

        # Define core Predicates
        self.REQUIRES_TOOL = self.MIL.requiresTool
        self.HAS_PART = self.MIL.hasPart
        self.HAS_INFO_CODE = self.MIL.hasInfoCode
        self.HAS_SNS = self.MIL.hasSNS
        self.HAS_FIGURE = self.MIL.hasFigure
        self.HAS_PART_NUMBER = self.MIL.hasPartNumber
        self.REFERS_TO_DM = self.MIL.refersToDataModule
        self.HAS_FAULT_CODE = self.MIL.hasFaultCode
        self.HAS_PLANNING_INTERVAL = self.MIL.hasPlanningInterval
        self.HAS_CATALOG_ITEM = self.MIL.hasCatalogItem
        self.HAS_ICN = self.MIL.hasICN
        # Hotspot id on an IPD catalog item, read from
        # `hotspot/@applicationStructureIdent` (section 8). The six real
        # MRAD corpus modules contain ZERO <hotspot> elements, so this path
        # is exercised only by the authored fixture at
        # tests/fixtures/s1000d/hotspot/ — not by real S1000D markup.
        self.HAS_HOTSPOT_ID = self.MIL.hasHotspotId

        # The rdf:List-valued procedures property (section 9). Named in the
        # plural and pointing at a list HEAD, not at a step: a consumer that
        # reads it expecting one step gets a cell, which fails loudly rather
        # than rendering step 1 as the whole procedure.
        self.HAS_PROCEDURE_STEPS = self.MIL.hasProcedureSteps

    @property
    def doc_slug(self) -> str:
        """The document scope spliced into per-document subject URIs.

        Part, tool and figure subjects are scoped by this so two documents
        cannot coin the same subject. Before scoping, `mil:part-ODM-SE-0001`
        was coined by two of the six mock OpenDDIL modules and MERGED into one
        node carrying both modules' edges (measured 2026-10-02); an unlabelled
        `<figure>` coined `mil:fig-fig_0` — named after a loop index — which
        every other document with an unlabelled figure collides on. On a
        shared corpus that silently fuses unrelated documents' parts lists,
        and it also makes a doc_id-keyed rollback impossible: deleting one
        document's subjects would take another document's edges with them.
        (Same shape as the component-IRI finding on the PCN side: a
        delete-by-subject write must key on the per-document node.)
        """
        return _fragment(self.doc_id) or UNSCOPED_DOC_SLUG

    def _dmc_string_from_code(self, dm_code) -> str:
        """Assemble a canonical DMC string from a `<dmCode>` element.

        Shared by the module's own ident (parse_data_module) and by dmRef
        targets (below) — SAME CANONICALIZER BOTH SIDES, with the identical
        argument mapping and the identical `disassyCode`/`disasCode`
        fallback order in both calls. A target assembled any other way
        cannot connect to the referenced module's own subject and the
        cross-document walk silently returns nothing.
        """
        return assemble_canonical_dmc(
            mic=dm_code.get("modelIdentCode", ""),
            sdc=dm_code.get("systemDiffCode", ""),
            sysc=dm_code.get("systemCode", ""),
            ssc=dm_code.get("subSystemCode", ""),
            sssc=dm_code.get("subSubSystemCode", ""),
            asy=dm_code.get("assyCode", ""),
            dis=dm_code.get("disassyCode", "") or dm_code.get("disasCode", ""),
            dvar=(dm_code.get("disassyCodeVariant", "")
                  or dm_code.get("disasCodeVariant", "")),
            info=dm_code.get("infoCode", ""),
            ivar=dm_code.get("infoCodeVariant", ""),
            itemloc=dm_code.get("itemLocationCode", ""),
        )

    def _dmref_target(self, dmref_el, own_uri):
        """The target subject of a `<dmRef>`, or None.

        ONE derivation for the module-level cross-reference edges (1b) and
        the per-answer edges of the isolation tree (section 10): a second copy
        could drift, and a target assembled any other way cannot connect to
        the referenced module's own subject. None for a dmRef with no dmCode
        and for a self-reference (a self-reference is not a cross-reference).
        """
        ref_code_list = dmref_el.xpath(".//dmCode")
        if not ref_code_list:
            return None
        target_uri = self.MIL[f"dmc-{self._dmc_string_from_code(ref_code_list[0])}"]
        if target_uri == own_uri:
            return None
        return target_uri

    def _part_node(self, pn: str, scope: str) -> URIRef:
        """Mint (or reuse) the Part subject for `pn` in this document's scope.

        Shared by the reqSpares loop and the IPD catalog-item loop so a part
        cited in BOTH places (the normal case: a catalog item's part number
        is also the spare a procedure calls out) is ONE node, not two that
        happen to coin the same URI by accident of two separate call sites
        staying in sync.
        """
        part_uri = self.MIL[f"part-{scope}-{_fragment(pn)}"]
        self.graph.add((part_uri, RDF.type, self.MIL.Part))
        self.graph.add((part_uri, self.HAS_PART_NUMBER, Literal(pn)))
        self.graph.add((part_uri, RDFS.label, Literal(pn)))
        return part_uri

    def parse_data_module(self, xml_content: bytes) -> str:
        """
        Parses an S1000D XML Data Module and adds triples to the graph.
        Returns the DMC URI of the root node.
        """
        parser = etree.XMLParser(remove_blank_text=True, recover=True)
        root = etree.fromstring(xml_content, parser)

        # 1. Extract DMC (Data Module Code) using XPath.
        #
        # `//dmCode` ALSO matches `dmRef/dmRefIdent/dmCode` — every dmRef
        # (including a brexDmRef) carries one. Measured over the six mock
        # OpenDDIL modules: `//dmCode` returns 2-4 elements per file, and
        # `[0]` was correct only by document order (dmIdent happens to
        # precede dmStatus/brexDmRef in the mocks). A document where a
        # brexDmRef's dmCode is authored first would silently take the
        # WRONG module's own ident. The fallback chain below prefers the
        # authored dmIdent unambiguously, then any dmCode not under a
        # dmRef, and only then falls back to today's bare `//dmCode`.
        dm_code_list = (
            root.xpath("//dmIdent/dmCode")
            or root.xpath("//dmCode[not(ancestor::dmRef)]")
            or root.xpath("//dmCode")
        )
        if not dm_code_list:
            return "unknown-s1000d-dmc"

        dm_code = dm_code_list[0]

        # Build the DMC string via the SHARED canonicalizer. Do NOT
        # reimplement the join here — dmc_canonicalizer is the single source
        # of truth and s1000d_ingest.extract_facts assembles through the same
        # function, so the two parsers cannot drift. The inline join this
        # replaced produced a different ID from the same input (measured
        # 2026-10-02: it emitted subSystemCode and subSubSystemCode as
        # separate hyphen groups where the canonical form concatenates them,
        # dropped empty positions instead of preserving them, and did not
        # uppercase), so NO S1000D DMC URI this builder has ever written
        # matched its authored DMC.
        #
        # `disassyCode` / `disassyCodeVariant` are the S1000D 4.x spellings;
        # `disasCode` / `disasCodeVariant` are the short forms. Reading only
        # the short names silently dropped the whole disassembly position on
        # 4.x documents, which also made two modules differing ONLY in that
        # code collide on one URI. Same fallback order as
        # s1000d_ingest.py:113. (Factored into _dmc_string_from_code so the
        # dmRef targets below use the IDENTICAL mapping.)
        info_code = dm_code.get("infoCode", "")
        dmc_string = self._dmc_string_from_code(dm_code)
        dmc_uri = self.MIL[f"dmc-{dmc_string}"]

        # Add root triple. The data module is typed with its DETERMINISTIC
        # content kind (mil:DescriptiveDataModule, mil:ProcedureDataModule,
        # mil:FaultIsolationDataModule, mil:IllustratedPartsDataModule) as
        # well as the mil:DataModule root.
        #
        # Before this, the ONLY type emitted here was the bare root, so every
        # data module was indistinguishable downstream — a fault-isolation
        # module, a procedure and an IPD all landed identically (measured
        # 2026-10-02 over the six OpenDDIL modules: zero classified kinds).
        # classify_data_module is the deterministic table, no LLM.
        #
        # BOTH types are emitted on purpose: the kinds are rdfs:subClassOf
        # mil:DataModule in the TBox, but Jena serves these graphs without
        # reasoning, so a consumer querying `?s a mil:DataModule` would stop
        # seeing classified modules if the root were dropped.
        kind_uri = URIRef(classify_data_module(info_code))
        self.graph.add((dmc_uri, RDF.type, self.MIL.DataModule))
        if str(kind_uri) != DATA_MODULE_ROOT:
            self.graph.add((dmc_uri, RDF.type, kind_uri))
        self.graph.add((dmc_uri, RDFS.label, Literal(dmc_string)))

        # 1b. dmRef cross-reference edges.
        #
        # `[not(ancestor::identAndStatusSection)]` is the whole point of this
        # XPath. MEASURED: of the 11 <dmRef> elements across the six mock
        # modules, SIX are identAndStatusSection/dmStatus/brexDmRef/dmRef and
        # in this corpus each one points at its OWN module's info code —
        # harvesting unfiltered //dmRef emits six self-loops and inflates
        # the cross-reference count from 5 to 11. (Same family of error as
        # grepping for a dmRef open-tag and also matching dmRefIdent, which
        # already produced a wrong count once.)
        for dmref_el in root.xpath("//dmRef[not(ancestor::identAndStatusSection)]"):
            # SAME CANONICALIZER BOTH SIDES (see _dmref_target).
            target_uri = self._dmref_target(dmref_el, dmc_uri)
            if target_uri is None:
                continue
            # Do NOT type target_uri: the referenced module types itself
            # when it is ingested, and asserting a type here would fabricate
            # a node for a module that may not exist in the corpus.
            self.graph.add((dmc_uri, self.REFERS_TO_DM, target_uri))

        # 2. Extract SNS & InfoCode
        system_code = dm_code.get("systemCode")

        if system_code:
            self.graph.add((dmc_uri, self.HAS_SNS, Literal(system_code)))
        if info_code:
            self.graph.add((dmc_uri, self.HAS_INFO_CODE, Literal(info_code)))

        scope = self.doc_slug

        # 3. Extract Tools (requiredSupportEquip)
        #
        # The prefix is `tool-`, not `part-`. A tool and a spare with the SAME
        # part number previously coined ONE subject that got both rdf:type
        # mil:Tool and rdf:type mil:Part, so a consumer asking "is this a
        # consumable spare" got yes for a torque wrench. `tool-` also matches
        # what iads_rdf.py:57 and mil_std_40051_rdf.py:166 already use, so
        # S1000D was the sole outlier.
        #
        # Scoped per reqSupportEquip, never a bare `//name`: `name` also
        # occurs under reqSpare/spareDescr and catalogSeqNumber/description
        # (measured: 720A "array module", 941A "connector gasket"), so an
        # unscoped read would label a spare or a catalog item as a tool.
        # The part number sits under partAndSerialNumber, not directly under
        # supportEquipDescr, hence `//partNumber` below the descr.
        # A reqSupportEquip with a name and NO part number has no stable key
        # and is skipped; the corpus has zero such elements (measured), so
        # that is an untested edge, not an impossible one.
        for equip_el in root.xpath("//reqSupportEquip"):
            name_el = equip_el.xpath(".//supportEquipDescr/name")
            tool_name = _collapse_ws(" ".join(name_el[0].itertext())) if name_el else ""
            for tool in equip_el.xpath(".//supportEquipDescr//partNumber"):
                pn = tool.text.strip() if tool.text else None
                if pn:
                    tool_uri = self.MIL[f"tool-{scope}-{_fragment(pn)}"]
                    self.graph.add((tool_uri, RDF.type, self.MIL.Tool))
                    # The bare part number stays on the node as a literal. The
                    # subject is document-scoped, so cross-document identity is
                    # no longer readable off the URI; this predicate is how a
                    # consumer still answers "which documents mention
                    # ODM-SE-0001" (join on the literal), without the subjects
                    # merging.
                    self.graph.add((tool_uri, self.HAS_PART_NUMBER, Literal(pn)))
                    # The label is the authored name when there is one (a
                    # reader asks for "the extraction tool", not a part
                    # number); a nameless tool keeps the part number.
                    self.graph.add((tool_uri, RDFS.label, Literal(tool_name or pn)))
                    if tool_name:
                        self.graph.add((tool_uri, self.MIL.hasName, Literal(tool_name)))
                    self.graph.add((dmc_uri, self.REQUIRES_TOOL, tool_uri))

        # 3b. Warnings (//reqSafety//warningAndCautionPara). The corpus has
        # zero `caution` elements (measured), so no caution predicate is
        # invented.
        #
        # Two shapes on purpose. The ROOT literal mil:hasWarning is the
        # load-bearing one: it matches mil_std_40051_rdf.py and iads_rdf.py (a
        # cross-parser join) and is the only form the chunker's `warning:N`
        # branch can see. The node is the citable form. Keyed on position
        # because the source carries no id= and two modules may carry
        # byte-identical warning text. The chunker deliberately does NOT walk
        # the node: it would emit a second chunk with the same text under a
        # different `section`, and chunk_id includes section, so that is a
        # duplicate retrieval row.
        for pos, warn_el in enumerate(root.xpath("//reqSafety//warningAndCautionPara"), start=1):
            warn_text = _collapse_ws(" ".join(warn_el.itertext()))
            if not warn_text:
                continue
            self.graph.add((dmc_uri, self.MIL.hasWarning, Literal(warn_text)))
            warn_uri = self.MIL[f"warning-{scope}-{pos}"]
            self.graph.add((warn_uri, RDF.type, self.MIL.Warning))
            self.graph.add((warn_uri, RDFS.label, Literal(f"warning {pos}")))
            self.graph.add((warn_uri, self.MIL.hasWarningText, Literal(warn_text)))
            self.graph.add((dmc_uri, self.MIL.hasWarningNode, warn_uri))

        # 4. Extract Parts (requiredSpares). Minted via _part_node so a part
        # cited here AND as an IPD catalog item (section 8 below) is one node.
        part_elements = root.xpath("//reqSpares//partNumber")
        for part in part_elements:
            pn = part.text.strip() if part.text else None
            if pn:
                part_uri = self._part_node(pn, scope)
                self.graph.add((dmc_uri, self.HAS_PART, part_uri))

        # 5. Extract Figures. figure_map records each figure element's
        # decided (fig_id, figure_uri) so section 8 (IPD catalog items) can
        # key an item's identity on its CONTAINING figure without redoing
        # the id-decision logic a second time and risking drift.
        figure_map = {}
        figure_elements = root.xpath("//figure")
        for idx, fig_el in enumerate(figure_elements):
            # Graphic read hoisted ABOVE the id decision: infoEntityIdent is
            # now itself a candidate for fig_id (below), so it must be known
            # before fig_id is decided, not re-read afterward.
            graphic_el = fig_el.find(".//graphic")
            icn = ""
            boardno = ""
            info_entity = ""
            # Hotspot idents authored under this figure's graphic, read ONCE
            # per figure (not per item) so section 8's join is a dict lookup
            # rather than a re-query. Empty on every real-corpus module.
            graphic_hotspot_idents = set()
            if graphic_el is not None:
                # ICN and boardno are DIFFERENT identifiers — an ICN is not a
                # boardno — kept in separate locals so mil:hasICN (below) can
                # never carry a boardno. `info_entity` is the existing
                # combined value that still feeds fig_id and the hasURL
                # fallback below; its meaning is unchanged.
                icn = (graphic_el.get("infoEntityIdent", "") or "").strip()
                boardno = (graphic_el.get("boardno", "") or "").strip()
                info_entity = icn or boardno
                for raw_ident in graphic_el.xpath(".//hotspot/@applicationStructureIdent"):
                    ident = (raw_ident or "").strip()
                    if ident:
                        graphic_hotspot_idents.add(ident)

            # Stable figure identity: @id -> authored infoEntityIdent/boardno
            # -> loop index, in that order. The mock IPD <figure> has NO id,
            # so this used to fall straight to f"fig_{idx}" — a subject named
            # after iteration order that every OTHER id-less figure in the
            # corpus collides on. infoEntityIdent (e.g. ICN-ODMRAD-00001) is
            # an AUTHORED stable identifier; keep the loop index as the last
            # resort so an id-less figure with no graphic still gets a
            # subject.
            fig_id = fig_el.get("id") or info_entity or f"fig_{idx}"

            title_el = fig_el.find(".//title")
            title = title_el.text.strip() if title_el is not None and title_el.text else fig_id

            figure_uri = self.MIL[f"fig-{scope}-{_fragment(fig_id)}"]
            self.graph.add((figure_uri, RDF.type, self.MIL.Figure))
            self.graph.add((figure_uri, RDFS.label, Literal(title)))
            if icn:
                # The ICN is a CONTENT identifier, deliberately NOT used as
                # the Figure subject (fig_id above still prefers @id, then
                # falls back to info_entity): the same ICN legitimately
                # recurs across publications, while the subject must stay
                # per-document (see doc_slug) so two publications' ICN-
                # bearing figures don't collide.
                self.graph.add((figure_uri, self.HAS_ICN, Literal(icn)))
            if info_entity and self.image_prefix:
                full_s3_url = f"{self.image_prefix}{info_entity}.png"
                self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
            # NOTE: the bare-ICN-as-a-URL fallback (`elif info_entity:`) was
            # deleted here. It emitted the bare string (e.g.
            # "ICN-ODMRAD-00001") as a mil:hasURL literal — a fake URL
            # indistinguishable downstream from a real one, the same
            # confabulation already killed in mil_std_40051_rdf.py (see its
            # CONFABULATION-KILL comment and test_parsers_rdf.py's boardno
            # test for that parser). Now that the ICN has its own predicate
            # (above), the branch was redundant as well as confabulating.
            self.graph.add((dmc_uri, self.HAS_FIGURE, figure_uri))

            figure_map[fig_el] = (fig_id, figure_uri, graphic_hotspot_idents)

        # 6. Fault codes (//faultCode). Document-scoped for the same reason
        # parts are (a delete-by-subject rollback must key on the
        # per-document node), with the bare value kept as a literal so
        # cross-document identity stays recoverable by joining on the
        # literal — the pattern already documented on hasPartNumber above.
        for fc_el in root.xpath("//faultCode"):
            value = (fc_el.get("faultCodeValue") or "").strip()
            if not value:
                continue
            fc_uri = self.MIL[f"faultcode-{scope}-{_fragment(value)}"]
            self.graph.add((fc_uri, RDF.type, self.MIL.FaultCode))
            self.graph.add((fc_uri, RDFS.label, Literal(value)))
            self.graph.add((fc_uri, self.MIL.hasFaultCodeValue, Literal(value)))
            text_el = fc_el.find("faultCodeText")
            text = text_el.text.strip() if text_el is not None and text_el.text else ""
            if text:
                self.graph.add((fc_uri, self.MIL.hasFaultCodeText, Literal(text)))
            self.graph.add((dmc_uri, self.HAS_FAULT_CODE, fc_uri))

        # 7. Planning intervals (//limit/threshold). Subject identity must
        # NOT be a loop index (that is the fig_0 defect section 5 just
        # fixed) — key on the nearest ancestor mpSection's title text when
        # there is one, else on {value}{unit}.
        # interval_map: mpSection element -> its interval URI, read by the
        # planning-section block below so the keying is decided once (the
        # figure_map idiom).
        interval_map = {}
        for threshold_el in root.xpath("//limit/threshold"):
            value_el = threshold_el.find("thresholdValue")
            value = value_el.text.strip() if value_el is not None and value_el.text else ""
            if not value:
                continue
            unit = (threshold_el.get("thresholdUnitOfMeasure") or "").strip()
            # ancestor:: is reverse-document-order, so [1] is the NEAREST
            # enclosing mpSection, not the outermost one.
            section_title_matches = threshold_el.xpath("ancestor::mpSection[1]/title")
            section_title = (
                section_title_matches[0].text.strip()
                if section_title_matches and section_title_matches[0].text
                else ""
            )
            key = section_title or f"{value}{unit}"
            iv_uri = self.MIL[f"interval-{scope}-{_fragment(key)}"]
            self.graph.add((iv_uri, RDF.type, self.MIL.PlanningInterval))
            # Ground truth for the 320 module is interval == "180 days", so
            # this label is the load-bearing assertion.
            label = f"{value} {unit}" if unit else value
            self.graph.add((iv_uri, RDFS.label, Literal(label)))
            self.graph.add((iv_uri, self.MIL.hasIntervalValue, Literal(value)))
            if unit:
                self.graph.add((iv_uri, self.MIL.hasIntervalUnit, Literal(unit)))
            self.graph.add((dmc_uri, self.HAS_PLANNING_INTERVAL, iv_uri))
            enclosing = threshold_el.xpath("ancestor::mpSection[1]")
            if enclosing:
                interval_map[enclosing[0]] = iv_uri

        # 7b. Planning sections (//mpSection) and their prose. Until now only
        # the threshold was read, so the paragraphs ("Every 180 days, inspect
        # the array face...", "Replace the array module on a confirmed BIT
        # failure...") were dropped. Keyed on the title, else position.
        for pos, sec_el in enumerate(root.xpath("//mpSection"), start=1):
            title_el = sec_el.find("title")
            sec_title = _collapse_ws(" ".join(title_el.itertext())) if title_el is not None else ""
            key = _fragment(sec_title) if sec_title else str(pos)
            sec_uri = self.MIL[f"mpsection-{scope}-{key}"]
            self.graph.add((sec_uri, RDF.type, self.MIL.PlanningSection))
            if sec_title:
                self.graph.add((sec_uri, RDFS.label, Literal(sec_title)))
            for para_el in sec_el.xpath("./para"):
                para_text = _collapse_ws(" ".join(para_el.itertext()))
                if para_text:
                    self.graph.add((sec_uri, self.MIL.hasPlanningText, Literal(para_text)))
            self.graph.add((dmc_uri, self.MIL.hasPlanningSection, sec_uri))
            if sec_el in interval_map:
                self.graph.add((sec_uri, self.HAS_PLANNING_INTERVAL, interval_map[sec_el]))

        # 8. IPD catalog items (//catalogSeqNumber). Identity includes the
        # containing figure's key (section 5's figure_map) so two figures'
        # item 0001 cannot collide. An item with no containing figure (not
        # present in the mock corpus, but not excludable either) falls back
        # to an explicit "nofig" scope and gets only the dmc_uri edge, never
        # a figure_uri edge.
        for pos, item_el in enumerate(root.xpath("//catalogSeqNumber"), start=1):
            containing_fig_matches = item_el.xpath("ancestor::figure[1]")
            if containing_fig_matches and containing_fig_matches[0] in figure_map:
                fig_key, figure_uri, graphic_hotspot_idents = figure_map[
                    containing_fig_matches[0]
                ]
            else:
                fig_key, figure_uri, graphic_hotspot_idents = "nofig", None, set()

            name_el = item_el.find(".//description/name")
            name = name_el.text.strip() if name_el is not None and name_el.text else ""

            mfr_el = item_el.find(".//identNumber/manufacturerCode")
            mfr = mfr_el.text.strip() if mfr_el is not None and mfr_el.text else ""

            pn_matches = item_el.xpath(".//identNumber//partNumber")
            pn = pn_matches[0].text.strip() if pn_matches and pn_matches[0].text else ""

            item_attr = (item_el.get("item") or "").strip()
            # item_no identity fallback: the authored @item (normally
            # present, e.g. "0001"), then the part number, then this item's
            # own 1-based position — never assume @item is there.
            item_no = item_attr or pn or str(pos)

            it_uri = self.MIL[f"item-{scope}-{_fragment(fig_key)}-{_fragment(item_no)}"]
            self.graph.add((it_uri, RDF.type, self.MIL.CatalogItem))
            self.graph.add((it_uri, RDFS.label, Literal(name or pn)))
            if item_attr:
                self.graph.add((it_uri, self.MIL.hasItemNumber, Literal(item_attr)))
            if pn:
                self.graph.add((it_uri, self.HAS_PART_NUMBER, Literal(pn)))
            if mfr:
                self.graph.add((it_uri, self.MIL.hasManufacturerCode, Literal(mfr)))

            # Hotspot id, precedence order (neither path is exercised by the
            # real MRAD corpus — zero <hotspot> elements in all six modules
            # — only by the authored fixture at tests/fixtures/s1000d/hotspot/):
            #   1. Nested directly in this item — unambiguous, take the first.
            #   2. Under the containing figure's graphic, joined by KEY: the
            #      item's key is <itemSeqNumber> text if present, else @item.
            #      A hotspot whose ident matches NEITHER item is simply not
            #      attached — no guessing by position (the exact defect the
            #      fig_0 fix removed).
            hotspot_id = ""
            nested_hotspot = item_el.xpath(".//hotspot/@applicationStructureIdent")
            if nested_hotspot:
                hotspot_id = (nested_hotspot[0] or "").strip()
            if not hotspot_id:
                item_seq_el = item_el.find("itemSeqNumber")
                item_key = (
                    item_seq_el.text.strip()
                    if item_seq_el is not None and item_seq_el.text
                    else item_attr
                )
                if item_key and item_key in graphic_hotspot_idents:
                    hotspot_id = item_key
            if hotspot_id:
                self.graph.add((it_uri, self.HAS_HOTSPOT_ID, Literal(hotspot_id)))

            qty_el = item_el.find("reqQuantity")
            qty_text = qty_el.text.strip() if qty_el is not None and qty_el.text else ""
            if qty_text:
                try:
                    qty_literal = Literal(int(qty_text))
                except ValueError:
                    qty_literal = Literal(qty_text)
                self.graph.add((it_uri, self.MIL.hasQuantity, qty_literal))

            if figure_uri is not None:
                self.graph.add((figure_uri, self.HAS_CATALOG_ITEM, it_uri))
            # ALWAYS, so a walk need not hop the figure.
            self.graph.add((dmc_uri, self.HAS_CATALOG_ITEM, it_uri))

            if pn:
                # Reuse the EXISTING part-node shape (section 4) so an IPD
                # part and a reqSpares part citing the same PN in the same
                # document are one node, not two.
                part_uri = self._part_node(pn, scope)
                self.graph.add((dmc_uri, self.HAS_PART, part_uri))
                self.graph.add((it_uri, self.HAS_PART, part_uri))

        # 9. Procedure order (//mainProcedure/proceduralStep) as an rdf:List.
        #
        # WHY rdf:List AND NOT mil:stepIndex. The rule was "rdf:List unless
        # mil:stepIndex already exists". It does not: measured against the
        # DEPLOYED vocabulary graph <http://internal/MAINTENANCE> (4959
        # triples), `ASK mil:stepIndex` is False in SUBJECT, PREDICATE AND
        # OBJECT position. Checking all three matters -- an earlier pass of
        # this measurement asked only about predicate position and concluded
        # "no mil: term is declared at all", which is FALSE: the graph carries
        # 16 declared mil: terms plus the ontology header (69 triples, exactly
        # mil_extension.ttl), and a TBox declares its terms as SUBJECTS, so a
        # predicate-position scan cannot see any of them. What is true is
        # narrower and still a gap: 25 of the 41 mil: terms these parsers emit
        # are undeclared, stepIndex among the things nobody ever declared.
        # The 511 rdf:first triples already in that graph are OWL
        # axiom plumbing (owl:intersectionOf 139, owl:unionOf 84,
        # owl:propertyChainAxiom 3) and order ZERO domain content, so they are
        # not precedent either way.
        #
        # WHY THE LIST CELLS ARE URIs AND NOT BLANK NODES. rdflib's
        # Collection mints blank nodes; this must not. The instance-graph
        # write (assets/semantic_assets.py, SECOND WRITE) serializes this
        # graph to N-Triples and sends it as SPARQL INSERT DATA, and INSERT
        # DATA mints a FRESH blank node on every execution. A blank-node list
        # would therefore append an entire second list on re-ingest and break
        # the set-idempotency that write documents and depends on ("the S1000D
        # builder emits no timestamp, no uuid and no prov term"). Deterministic
        # cell URIs keep the retry body byte-identical, which is also what the
        # idempotency proof (re-run one module, count unchanged) rests on.
        #
        # ONLY DIRECT CHILDREN ARE ORDERED. S1000D permits proceduralStep
        # nesting; the six MRAD modules contain none (measured: 520A has 4 and
        # 720A has 5, every one at depth 1), so a sub-list shape would be
        # unexercised code guessing at markup nobody in this corpus has. A
        # nested step is NOT dropped silently -- itertext() folds its text into
        # the enclosing step's text, which is visible in the literal.
        #
        # Cells are deliberately NOT typed rdf:List. A walk reaches them by
        # rdf:rest*/rdf:first, which needs no type, and typing them would add
        # one triple per step to every procedural module to say nothing.
        for proc_pos, proc_el in enumerate(root.xpath("//mainProcedure"), start=1):
            step_elements = proc_el.xpath("./proceduralStep")
            if not step_elements:
                continue
            step_uris = []
            for step_pos, step_el in enumerate(step_elements, start=1):
                # Keying on the ORDINAL here is deliberate, and is not the
                # fig_0 defect of section 5. That defect was a loop index
                # standing in for an identity that EXISTED in the markup. A
                # step has no code, no part number and no title, and two steps
                # in one procedure may carry byte-identical text ("Run BIT."),
                # so its position in its procedure IS its identity -- which is
                # also exactly what this section is asked to record.
                step_uri = self.MIL[f"step-{scope}-{proc_pos}-{step_pos}"]
                text = _collapse_ws(" ".join(step_el.itertext()))
                self.graph.add((step_uri, RDF.type, self.MIL.ProceduralStep))
                # Day 2 declares mil:ProceduralStep an rdfs:subClassOf of the
                # vocabulary's own ProcedureStep class, which carries no
                # ordering predicate. The carrier for that declaration already
                # exists and is NOT a new file in this repo: it is
                # setup/ontologies/mil_extension.ttl in invincible-agent,
                # stamped domain=MAINTENANCE and primed into
                # <http://internal/MAINTENANCE>. Emitting the mil: class now
                # and tying it there later keeps one namespace for everything
                # this builder coins.
                self.graph.add((step_uri, RDFS.label, Literal(f"step {proc_pos}.{step_pos}")))
                if text:
                    self.graph.add((step_uri, self.MIL.hasStepText, Literal(text)))
                step_uris.append(step_uri)

            for idx, step_uri in enumerate(step_uris, start=1):
                cell = self.MIL[f"proclist-{scope}-{proc_pos}-{idx}"]
                self.graph.add((cell, RDF.first, step_uri))
                # rdf:nil terminates the last cell. Without it the list is not
                # a list: a consumer walking rdf:rest cannot tell the end from
                # a gap, and SPARQL's rdf:rest* path silently stops early.
                rest = (
                    self.MIL[f"proclist-{scope}-{proc_pos}-{idx + 1}"]
                    if idx < len(step_uris)
                    else RDF.nil
                )
                self.graph.add((cell, RDF.rest, rest))

            # The head goes on the MODULE subject, so the whole procedure is
            # reachable from the data module without knowing the cell naming.
            self.graph.add((
                dmc_uri,
                self.HAS_PROCEDURE_STEPS,
                self.MIL[f"proclist-{scope}-{proc_pos}-1"],
            ))

        # 10. Fault-isolation tree (//faultIsolation/isolationProcStep).
        #
        # The nesting IS the semantics ("the replace action is the yes-branch
        # of the third test"), so a step is keyed on its positional PATH
        # (1, 1-yes-1, 1-yes-1-yes-1) and the branch it sits in is readable
        # off its URI. Positional for the section-9 reason: no id= in the
        # source, and byte-identical test text can recur. No blank nodes.
        for top_pos, step_el in enumerate(root.xpath("//faultIsolation/isolationProcStep"), start=1):
            top_uri = self._isolation_step(step_el, str(top_pos), scope, dmc_uri)
            self.graph.add((dmc_uri, self.MIL.hasIsolationStep, top_uri))

        return str(dmc_uri)

    def _isolation_step(self, step_el, path: str, scope: str, dmc_uri) -> URIRef:
        step_uri = self.MIL[f"isostep-{scope}-{path}"]
        self.graph.add((step_uri, RDF.type, self.MIL.IsolationStep))
        title_el = step_el.find("title")
        title = _collapse_ws(" ".join(title_el.itertext())) if title_el is not None else ""
        self.graph.add((step_uri, RDFS.label, Literal(title or f"isolation step {path}")))
        test_el = step_el.find("test")
        if test_el is not None:
            test_text = _collapse_ws(" ".join(test_el.itertext()))
            if test_text:
                self.graph.add((step_uri, self.MIL.hasTestText, Literal(test_text)))
        for answer_el in step_el.findall("answer"):
            at = answer_el.get("answerType")
            if at not in ("yes", "no"):
                continue  # only yes/no are expected; do not guess a branch
            ans_uri = self.MIL[f"isoanswer-{scope}-{path}-{at}"]
            self.graph.add((ans_uri, RDF.type, self.MIL.IsolationAnswer))
            self.graph.add((ans_uri, RDFS.label, Literal(f"answer {at} at {path}")))
            self.graph.add((ans_uri, self.MIL.hasAnswerType, Literal(at)))
            self.graph.add((step_uri, self.MIL.hasAnswer, ans_uri))
            for action_el in answer_el.findall("isolationAction"):
                action = _collapse_ws(" ".join(action_el.itertext()))
                if action:
                    self.graph.add((ans_uri, self.MIL.hasActionText, Literal(action)))
            # dmRef descendants of THIS answer; one inside a nested step
            # belongs to that deeper answer, so it is skipped here.
            for dmref_el in answer_el.xpath(".//dmRef"):
                if dmref_el.xpath("ancestor::answer[1]")[0] is not answer_el:
                    continue
                target = self._dmref_target(dmref_el, dmc_uri)
                if target is not None:
                    self.graph.add((ans_uri, self.REFERS_TO_DM, target))
            for nested_pos, nested_el in enumerate(answer_el.findall("isolationProcStep"), start=1):
                child_uri = self._isolation_step(nested_el, f"{path}-{at}-{nested_pos}", scope, dmc_uri)
                self.graph.add((ans_uri, self.MIL.hasNextStep, child_uri))
        return step_uri

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)


def data_module_graph(raw_bytes: bytes, doc_id: str = "") -> str:
    """Dispatcher entry point: parse one data module, return Turtle."""
    # WHAT THIS DOES NOT PROVE. It makes this module REACHABLE from the passes
    # dispatcher (doc_tools/passes/dispatch.py) and nothing more. This is the
    # parser already recorded as scoring 0 content kinds on a real module, with
    # a DMC that was not a DMC. So a green dispatcher test over this function
    # proves the DISPATCHER, not the parser -- and the dispatcher is not wired
    # into any asset yet. Reachability is not correctness.
    builder = S1000dGraphBuilder(doc_id=doc_id)
    builder.parse_data_module(raw_bytes)
    return builder.serialize()
