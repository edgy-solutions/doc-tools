import lxml.etree as etree
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, RDFS
import re

class MilStd40051GraphBuilder:
    """
    Parser for US Army MIL-STD-40051 XML technical manuals.
    Maps Army Work Packages to a unified military ontology.

    Figure URLs are sourced from a per-bundle `graphics_manifest.json`
    written by the IADS extractor (see
    `doc_tools/assets/iads_ingestion.py`). The manifest maps each
    `<graphic boardno="..."/>` to the actual uploaded filename in S3
    AND the rendering-origin discipline state (pipeline /
    supplied_override / format_not_supported). Without a manifest the
    parser falls back to the legacy `<boardno>.png` prediction — kept
    for backward compatibility with manually-launched single-XML
    ingests, but the cluster's IADS path always provides one.
    """

    def __init__(
        self,
        bucket: str = "",
        doc_id: str = "",
        image_prefix: str = "",
        graphics_manifest: dict | None = None,
    ):
        self.graph = Graph()
        self.MIL = Namespace("http://edgy-solutions.com/ontology/mil#")
        self.graph.bind("mil", self.MIL)
        self.root_node = None
        self.bucket = bucket
        self.doc_id = doc_id
        self.image_prefix = image_prefix
        # graphics_manifest["figures"][boardno] -> {uploaded_filename,
        # rendering_origin, source_format, source_s3, ...}. See
        # iads_ingestion.extract_iads_bundle for the writer.
        raw_figures = (graphics_manifest or {}).get("figures", {}) \
            if isinstance(graphics_manifest, dict) and "figures" in graphics_manifest \
            else (graphics_manifest or {})
        # Build a normalization-tolerant alias index for boardno lookup.
        # Reason: the IADS extractor writes manifest keys derived from the
        # actual uploaded filename (which often has spaces, mixed case),
        # while the 40051 XML's `<graphic boardno="X"/>` element typically
        # strips spaces and changes case ("tab navigation drop down menu"
        # in S3 → boardno="tabnavigationdropdownmenu" in XML). The two
        # pipeline stages don't enforce a canonical key shape, so the
        # reader (this parser) is tolerant of mismatch. CAVEAT: this is
        # READER-SIDE tolerance for a producer/consumer contract nobody
        # enforces — durable fix is boundary-normalization at BOTH stages
        # to a canonical shape. When the next mismatch appears (different
        # punctuation, etc.), the right answer is to enforce the contract,
        # not add another variant here. 2026-06-29 investigation w/
        # architect-friend's framing: "reader-tolerance is the patch;
        # boundary-normalization is the fix."
        self._fig_lookup: dict[str, dict] = {}
        for k, v in raw_figures.items():
            for variant in {
                k,
                k.lower(),
                k.replace(' ', ''),
                k.replace(' ', '').lower(),
                k.replace('-', '').replace(' ', ''),
                k.replace('-', '').replace(' ', '').lower(),
                k.replace('_', '').replace(' ', ''),
                k.replace('_', '').replace(' ', '').lower(),
            }:
                self._fig_lookup.setdefault(variant, v)
        # Keep raw_figures accessible too for any callers reading
        # graphics_manifest directly (e.g., tests inspecting the dict).
        self.graphics_manifest = raw_figures

    def _lookup_figure(self, boardno: str) -> dict | None:
        """Return the manifest entry for a 40051 `<graphic boardno>` value
        or None if no key variant matches. Tries: as-is, lowercase, with
        spaces/punctuation stripped. On miss, the caller MUST emit
        rendering_origin="unresolved" and OMIT mil:hasURL — see [[fix the
        writer]]: a parser that confabulates a URL on miss
        (`f"{boardno}.png"`) flows optimistic-falsehood downstream
        indistinguishably from truth. This investigation's load-bearing
        finding was that the previous fallback masked which figures had
        no manifest entry; now misses are honestly visible.
        """
        if not boardno:
            return None
        candidates = [
            boardno,
            boardno.lower(),
            boardno.replace(' ', ''),
            boardno.replace(' ', '').lower(),
            boardno.replace('-', '').replace(' ', ''),
            boardno.replace('-', '').replace(' ', '').lower(),
            boardno.replace('_', '').replace(' ', ''),
            boardno.replace('_', '').replace(' ', '').lower(),
        ]
        for c in candidates:
            hit = self._fig_lookup.get(c)
            if hit:
                return hit
        return None

    def parse_data_module(self, xml_content: bytes) -> str:
        """
        Parses a 40051 Work Package and extracts semantic entities.
        """
        parser = etree.XMLParser(recover=True, remove_blank_text=True)
        tree = etree.fromstring(xml_content, parser=parser)
        
        # 1. Identity Extraction (Work Package Number)
        # Per MIL-STD-40051E DTD: the wpno is the wp-root element's ATTRIBUTE
        # (e.g. `<maintwp wpno="m0004-1-1680-TNG">`, `<tswp wpno="...">`),
        # NOT a child element. The original `//wpno/text()` XPath missed every
        # real 40051 file — confirmed against helmet TM fixtures M0004 / T0003
        # (corpus-ingest investigation 2026-06-28). Both helmet WPs fell
        # through to "unknown_wp", causing every chunk to write under the same
        # synthetic doc_id and collide in Weaviate.
        wp_id_attr = tree.get("wpno")
        if wp_id_attr:
            wp_id = str(wp_id_attr).strip()
        else:
            # Legacy XPath fallbacks for non-conformant or partial inputs.
            xpath_match = (
                tree.xpath("//wpno/text()")
                or tree.xpath("//wpid/@wpno")
                or tree.xpath("/@id")
            )
            if xpath_match:
                wp_id = str(xpath_match[0]).strip()
            elif self.doc_id:
                # Per-file fallback: the constructor's doc_id (derived from
                # the S3 key, unique per file) is strictly better than the
                # static "unknown_wp" which causes cross-file URI collision.
                wp_id = self.doc_id
            else:
                wp_id = "unknown_wp"

        node_uri = URIRef(self.MIL[f"wpn-{wp_id}"])
        self.root_node = node_uri

        # Classify as DataModule and WorkPackage
        self.graph.add((node_uri, RDF.type, self.MIL.DataModule))
        self.graph.add((node_uri, RDF.type, self.MIL.WorkPackage))

        # Use the actual document title from <wpidinfo>/<title> when present
        # (e.g. "MICROPHONE BOOM REMOVAL/INSTALLATION"), falling back to
        # "Work Package {wp_id}". The real title produces a vastly more
        # searchable label-chunk: BM25 matches a query like "microphone boom"
        # against the real title but not against the generic placeholder.
        # Confirmed against the helmet TM fixtures.
        title_elements = tree.xpath("//wpidinfo/title/text()") or tree.xpath("//title/text()")
        if title_elements:
            title_text = " ".join(str(t).strip() for t in title_elements if str(t).strip())
        else:
            title_text = ""
        label_text = f"{title_text} ({wp_id})" if title_text else f"Work Package {wp_id}"
        self.graph.add((node_uri, RDFS.label, Literal(label_text)))

        # 2. Tools & Support Equipment
        # Looking for //supportreqs//name or //reqtools
        tools = tree.xpath("//supportreqs//name/text()") or tree.xpath("//reqtools/text()")
        for tool in set(tools):
            tool_name = str(tool).strip()
            if tool_name:
                clean_tool_name = re.sub(r'[^a-zA-Z0-9_]', '', tool_name.replace(' ', '_'))
                tool_uri = URIRef(self.MIL[f"tool-{clean_tool_name}"])
                self.graph.add((tool_uri, RDF.type, self.MIL.Tool))
                self.graph.add((tool_uri, RDFS.label, Literal(tool_name)))
                self.graph.add((node_uri, self.MIL.requiresTool, tool_uri))

        # 3. Spare Parts & Materials
        # Looking for //sparesreq//name or //partno
        parts = tree.xpath("//sparesreq//name/text()") or tree.xpath("//partno/text()")
        for part in set(parts):
            part_name = str(part).strip()
            if part_name:
                clean_part_name = re.sub(r'[^a-zA-Z0-9_]', '', part_name.replace(' ', '_'))
                part_uri = URIRef(self.MIL[f"part-{clean_part_name}"])
                self.graph.add((part_uri, RDF.type, self.MIL.Part))
                self.graph.add((part_uri, RDFS.label, Literal(part_name)))
                self.graph.add((node_uri, self.MIL.hasPart, part_uri))

        # 4. Warnings and Cautions
        warnings = tree.xpath("//warning//para/text()") or tree.xpath("//warning/text()")
        cautions = tree.xpath("//caution//para/text()") or tree.xpath("//caution/text()")
        
        for msg in set(warnings + cautions):
            text = str(msg).strip()
            if text:
                self.graph.add((node_uri, self.MIL.hasWarning, Literal(text)))

        # 5. Instructions (Procedures)
        # Extract step text (e.g., //step1/para or //proc//para)
        steps = tree.xpath("//step1//para/text()") or tree.xpath("//proc//para/text()")
        for step in steps:
            text = str(step).strip()
            if text:
                self.graph.add((node_uri, self.MIL.hasInstructionText, Literal(text)))

        # 6. Extract Figures & Graphics
        # 40051 uses <graphic boardno="..."> and <figure> tags. URL +
        # rendering_origin come from the per-bundle graphics manifest
        # (see class docstring); fall back to `<boardno>.png` only when
        # no manifest is available (legacy single-file ingest path).
        seen_figs = set()

        # Primary: <graphic boardno="..."> elements
        graphic_elements = tree.xpath("//graphic[@boardno]")
        for g in graphic_elements:
            boardno = g.get("boardno", "").strip()
            if boardno and boardno not in seen_figs:
                seen_figs.add(boardno)
                clean_boardno = re.sub(r'[^a-zA-Z0-9_-]', '', boardno.replace(' ', '_'))
                figure_uri = URIRef(self.MIL[f"fig-{clean_boardno}"])
                self.graph.add((figure_uri, RDF.type, self.MIL.Figure))
                self.graph.add((figure_uri, RDFS.label, Literal(boardno)))

                # Look up the actual uploaded filename + rendering origin
                # from the manifest. The manifest is keyed by figure
                # basename (the part before the source extension); the
                # XML's `boardno` attribute often differs in shape
                # (spaces stripped, case changed). `_lookup_figure` tries
                # a small alias set to bridge.
                figure_info = self._lookup_figure(boardno)
                if figure_info:
                    actual_filename = figure_info.get("uploaded_filename")
                    rendering_origin = figure_info.get("rendering_origin", "")
                    if actual_filename and self.image_prefix:
                        full_s3_url = f"{self.image_prefix}{actual_filename}"
                        self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
                    elif actual_filename:
                        self.graph.add((figure_uri, self.MIL.hasURL, Literal(actual_filename)))
                    if rendering_origin:
                        self.graph.add((
                            figure_uri,
                            self.MIL.renderingOrigin,
                            Literal(rendering_origin),
                        ))
                else:
                    # CONFABULATION-KILL: no manifest entry → emit
                    # rendering_origin="unresolved" and OMIT mil:hasURL.
                    # The previous fallback (`f"{boardno}.png"`) was a
                    # writer manufacturing optimistic falsehood,
                    # indistinguishable downstream from a real URL.
                    # Honest unresolved-origin makes the miss visible:
                    # the slide-in renders an "unresolved" placeholder
                    # card (not a 404 that looks like a broken pipeline).
                    # Class-cousin of [[optimistic-defaults-are-dishonest]]
                    # applied to URLs instead of status enums.
                    self.graph.add((
                        figure_uri,
                        self.MIL.renderingOrigin,
                        Literal("unresolved"),
                    ))

                self.graph.add((node_uri, self.MIL.hasFigure, figure_uri))

        # Fallback: <figure> tags
        figure_elements = tree.xpath("//figure")
        for idx, fig_el in enumerate(figure_elements):
            fig_id = fig_el.get("id", f"fig_{idx}")
            if fig_id not in seen_figs:
                seen_figs.add(fig_id)
                title_el = fig_el.find(".//title")
                title = title_el.text.strip() if title_el is not None and title_el.text else fig_id
                clean_id = re.sub(r'[^a-zA-Z0-9_-]', '', fig_id.replace(' ', '_'))
                figure_uri = URIRef(self.MIL[f"fig-{clean_id}"])
                self.graph.add((figure_uri, RDF.type, self.MIL.Figure))
                self.graph.add((figure_uri, RDFS.label, Literal(title)))
                # Check for nested graphic — same manifest lookup as the
                # primary <graphic boardno> path so URL extension matches
                # what the extractor actually uploaded, and the
                # rendering_origin property flows through.
                nested_graphic = fig_el.find(".//graphic")
                if nested_graphic is not None:
                    info_entity = (
                        nested_graphic.get("boardno", "")
                        or nested_graphic.get("infoEntityIdent", "")
                    )
                    if info_entity:
                        nested_info = self._lookup_figure(info_entity)
                        if nested_info:
                            actual_filename = nested_info.get("uploaded_filename")
                            rendering_origin = nested_info.get("rendering_origin", "")
                            if actual_filename and self.image_prefix:
                                full_s3_url = f"{self.image_prefix}{actual_filename}"
                                self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
                            elif actual_filename:
                                self.graph.add((figure_uri, self.MIL.hasURL, Literal(actual_filename)))
                            if rendering_origin:
                                self.graph.add((
                                    figure_uri,
                                    self.MIL.renderingOrigin,
                                    Literal(rendering_origin),
                                ))
                        else:
                            # CONFABULATION-KILL: same rule as the primary
                            # path. No manifest entry → unresolved + no URL.
                            self.graph.add((
                                figure_uri,
                                self.MIL.renderingOrigin,
                                Literal("unresolved"),
                            ))
                self.graph.add((node_uri, self.MIL.hasFigure, figure_uri))

        return str(node_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
