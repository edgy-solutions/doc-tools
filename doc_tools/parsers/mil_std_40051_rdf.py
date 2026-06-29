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
        self.graphics_manifest = (graphics_manifest or {}).get("figures", {}) \
            if isinstance(graphics_manifest, dict) and "figures" in graphics_manifest \
            else (graphics_manifest or {})

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
                # from the manifest. The manifest is keyed by figure_basename
                # (the part before the source extension); the XML's
                # `boardno` attribute matches that key. Case-insensitive
                # fallback handles the helmet TM's "MS098897A.cgm" XML ref
                # vs the bundle's lowercase "ms098897a.cgm" entry.
                figure_info = self.graphics_manifest.get(boardno) \
                    or self.graphics_manifest.get(boardno.lower()) \
                    or {}
                actual_filename = figure_info.get(
                    "uploaded_filename", f"{boardno}.png"
                )
                rendering_origin = figure_info.get("rendering_origin", "")

                if self.image_prefix:
                    full_s3_url = f"{self.image_prefix}{actual_filename}"
                    self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
                else:
                    self.graph.add((figure_uri, self.MIL.hasURL, Literal(actual_filename)))

                # Emit rendering_origin as a property — the chunker reads
                # it to decide whether to inline image markdown (renderable)
                # or fall back to a text-only mention (format_not_supported).
                # The cortex-ui slide-in reads it too to choose the
                # three-state render path.
                if rendering_origin:
                    self.graph.add((
                        figure_uri,
                        self.MIL.renderingOrigin,
                        Literal(rendering_origin),
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
                    info_entity = nested_graphic.get("boardno", "") or nested_graphic.get("infoEntityIdent", "")
                    if info_entity:
                        nested_info = self.graphics_manifest.get(info_entity) \
                            or self.graphics_manifest.get(info_entity.lower()) \
                            or {}
                        actual_filename = nested_info.get(
                            "uploaded_filename", f"{info_entity}.png"
                        )
                        rendering_origin = nested_info.get("rendering_origin", "")
                        if self.image_prefix:
                            full_s3_url = f"{self.image_prefix}{actual_filename}"
                            self.graph.add((figure_uri, self.MIL.hasURL, Literal(full_s3_url)))
                        else:
                            self.graph.add((figure_uri, self.MIL.hasURL, Literal(actual_filename)))
                        if rendering_origin:
                            self.graph.add((
                                figure_uri,
                                self.MIL.renderingOrigin,
                                Literal(rendering_origin),
                            ))
                self.graph.add((node_uri, self.MIL.hasFigure, figure_uri))

        return str(node_uri)

    def serialize(self, format: str = "turtle") -> str:
        """Serializes the current graph to a string."""
        return self.graph.serialize(format=format)
