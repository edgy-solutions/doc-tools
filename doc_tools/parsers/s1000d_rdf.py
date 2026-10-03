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

# Used when a builder is constructed with no doc_id (the bare
# `S1000dGraphBuilder()` form the unit tests use). Explicit, so an unscoped
# subject is READABLE AS unscoped in the graph rather than looking like a
# document called "". Nothing on the ingest path hits this: xml_ingestion.py
# always derives doc_id from the S3 key.
UNSCOPED_DOC_SLUG = "nodoc"


def _fragment(value: str) -> str:
    """Make `value` safe to splice into a URI local name."""
    return _FRAGMENT_UNSAFE.sub("_", value.strip())


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
            ref_code_list = dmref_el.xpath(".//dmCode")
            if not ref_code_list:
                continue
            # SAME CANONICALIZER BOTH SIDES: a target assembled any other
            # way cannot connect to the referenced module's own subject
            # (the one `parse_data_module` mints when IT is ingested), and
            # the cross-document walk silently returns nothing.
            target_string = self._dmc_string_from_code(ref_code_list[0])
            target_uri = self.MIL[f"dmc-{target_string}"]
            if target_uri == dmc_uri:
                continue  # a self-reference is not a cross-reference
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
        tool_elements = root.xpath("//reqSupportEquip//partNumber")
        for tool in tool_elements:
            pn = tool.text.strip() if tool.text else None
            if pn:
                tool_uri = self.MIL[f"tool-{scope}-{_fragment(pn)}"]
                self.graph.add((tool_uri, RDF.type, self.MIL.Tool))
                # The bare part number stays on the node as a literal. The
                # subject is document-scoped, so cross-document identity is
                # no longer readable off the URI; this predicate is how a
                # consumer still answers "which documents mention ODM-SE-0001"
                # (join on the literal), without the subjects merging.
                self.graph.add((tool_uri, self.HAS_PART_NUMBER, Literal(pn)))
                self.graph.add((tool_uri, RDFS.label, Literal(pn)))
                self.graph.add((dmc_uri, self.REQUIRES_TOOL, tool_uri))

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
            info_entity = ""
            if graphic_el is not None:
                info_entity = graphic_el.get("infoEntityIdent", "") or graphic_el.get("boardno", "")

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
            if info_entity and self.image_prefix:
                full_s3_url = f"{self.image_prefix}{info_entity}.png"
                self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
            elif info_entity:
                self.graph.add((figure_uri, self.MIL.hasURL, Literal(info_entity)))
            self.graph.add((dmc_uri, self.HAS_FIGURE, figure_uri))

            figure_map[fig_el] = (fig_id, figure_uri)

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

        # 8. IPD catalog items (//catalogSeqNumber). Identity includes the
        # containing figure's key (section 5's figure_map) so two figures'
        # item 0001 cannot collide. An item with no containing figure (not
        # present in the mock corpus, but not excludable either) falls back
        # to an explicit "nofig" scope and gets only the dmc_uri edge, never
        # a figure_uri edge.
        for pos, item_el in enumerate(root.xpath("//catalogSeqNumber"), start=1):
            containing_fig_matches = item_el.xpath("ancestor::figure[1]")
            if containing_fig_matches and containing_fig_matches[0] in figure_map:
                fig_key, figure_uri = figure_map[containing_fig_matches[0]]
            else:
                fig_key, figure_uri = "nofig", None

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

        return str(dmc_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
