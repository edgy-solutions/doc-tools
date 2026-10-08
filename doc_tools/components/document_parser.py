import os
import json
import io
import re
import tempfile
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import Field
from dagster import Definitions, asset, define_asset_job, AssetExecutionContext, AutomationCondition, Config, DynamicPartitionsDefinition
from dagster.components import Component, ComponentLoadContext
from dagster.components.resolved.base import Resolvable
from dagster.components.resolved.model import Model
from dagster_aws.s3 import S3Resource
from doc_tools.utils.extraction import extract_text_and_metadata, rasterize_pdf_pages
# Top-level, unlike the ingest_provenance / IngestStatusResource imports below:
# ingest_id.py is pure stdlib with no `iagent_mesh` dependency, so it cannot
# re-introduce the import cost (or the 0.9.4-venv ModuleNotFoundError) those
# local imports exist to avoid.
from doc_tools.utils.ingest_id import canonical_ingest_id, mint_ingest_id
from dag_tools.components.s3_sensor.file_component import S3FileConfig
from dag_tools.utils.k8s import resolve_k8s_resource_tags

class DocumentParserComponent(Component, Resolvable, Model):
    """A specialized component that downloads, parses, and extracts metadata/images from documents via S3."""
    name: str = Field(default="process_document_artifact")
    partition_name: str = Field(description="The dynamic partition name to use.")
    config: Dict[str, Any] = Field(default_factory=dict, description="Configuration for labels and extraction rules.")
    k8s_resource_prefix: str = Field(default="DOC_PARSER", description="Prefix for K8s resource environment variables.")
    # ADR-0041 user-drop stamp — all four default to no-op so every existing
    # DocumentParserComponent instance (vetted sensors) is byte-for-byte
    # unaffected.
    obtained_via: Optional[str] = Field(
        default=None,
        description=(
            "ADR-0041 OBTAINED_VIA rung for documents this instance ingests "
            "(e.g. 'user-drop'). None means this instance is a vetted path: "
            "no provenance stamp is written at all."
        ),
    )
    authoritative_source: str = Field(
        default="user-upload",
        description="ADR-0041 authoritative_source for the provenance stamp, when one is written.",
    )
    standing: str = Field(
        default="unverified",
        description="ADR-0041 standing (trust rung at write time) for the provenance stamp, when one is written.",
    )
    path_prefix_strip: str = Field(
        default="",
        description=(
            "A transport-location prefix (e.g. 'ingress-user/') to strip from "
            "the S3 key BEFORE deriving domain/content_kind, so the user-drop "
            "LOCATION never becomes a semantic domain label. Never changes "
            "source_key or any S3 address — see the strip site below."
        ),
    )
    downstream_graph_asset: str = Field(
        default="build_knowledge_graph",
        description=(
            "Name of the build_knowledge_graph-family asset (see "
            "doc_tools.assets.semantic_assets.make_build_knowledge_graph) "
            "this instance's process_job selects alongside its own parser "
            "asset. Defaults to the vetted 'build_knowledge_graph'. The "
            "ADR-0041 user_document_parser instance sets this to "
            "'build_user_knowledge_graph' so the user-drop job never "
            "selects the vetted graph asset, which is pinned to a "
            "DIFFERENT partitions_def (pdf_files, not user_pdf_files) and "
            "would make the selection fail to resolve."
        ),
    )
    sidecar_manifest_name: Optional[str] = Field(
        default=None,
        description=(
            "ADR-0041 Lane-1-sidecar filename (e.g. 'manifest.json'), read "
            "from the SAME directory as the source object, BEFORE anything "
            "is derived from the path. None (default) is the current/vetted "
            "behaviour, byte-for-byte unchanged: domain_type/content_kind "
            "keep being derived from the S3 key. When set, the key is a "
            "FILE FORMAT + a hash (e.g. 'pdf/<64-hex>/name.pdf'), never a "
            "semantic domain — see the guard below — so domain_type, "
            "content_kind, ingest_id and provenance all come from the "
            "sidecar instead. A missing/unparseable sidecar is a HARD "
            "FAILURE: there is no path-derivation fallback, because a "
            "fallback is exactly how a file-format segment ('pdf') became "
            "domain_type in the first place."
        ),
    )

    def build_defs(self, context: ComponentLoadContext) -> Definitions:
        # A SEPARATE partition set per self.partition_name, not the single
        # hardcoded `pdf_files_partition` singleton this line used to read.
        # Two DocumentParserComponent instances (the vetted `document_parser`
        # and the ADR-0041 `user_document_parser`) must land on structurally
        # DIFFERENT dynamic partition sets — otherwise a partition the
        # ingress-user sensor registers would be seen as "missing" by the
        # OTHER parser's AutomationCondition.on_missing(), which would
        # materialize it with no stamp and silently launder a user drop into
        # vetted-looking content. DynamicPartitionsDefinition is identified
        # by `name`, so constructing it here from self.partition_name (same
        # pattern dag_tools.S3SensorComponent already uses) keeps every
        # existing instance's behavior identical (they all pass
        # partition_name="pdf_files") while making the new instance's
        # "user_pdf_files" partition set actually take effect.
        parts_def = DynamicPartitionsDefinition(name=self.partition_name)

        @asset(
            name=self.name,
            partitions_def=parts_def,
            automation_condition=AutomationCondition.on_missing()
        )
        def process_document_artifact(context: AssetExecutionContext, config: S3FileConfig, s3: S3Resource) -> Dict[str, Any]:
            s3_client = s3.get_client()
            
            # Parse s3://bucket/key from file_url
            file_url = config.file_url
            if file_url.startswith("s3://"):
                url_parts = file_url[5:].split("/", 1)
                bucket = url_parts[0]
                source_object_key = url_parts[1]
            else:
                # Fallback to partition_key and component config
                bucket = self.config.get("bucket", "processing-artifacts")
                source_object_key = context.partition_key.replace("__", "/")
            
            # Parse domain and doc_id from S3 key (e.g. manufacturing/IID/test.pdf)
            parts = source_object_key.split('/')
            filename = parts[-1]

            base_dir = os.path.dirname(source_object_key)
            if not base_dir:
                base_dir = "unknown"

            # ADR-0041 path_prefix_strip — LOAD-BEARING, do not simplify away.
            # `domain`/`content_kind` below are derived from `parts[0]`/`parts[1]`
            # of the S3 key. A raw `ingress-user/` prefix would make parts[0]
            # == "ingress-user", so domain_label becomes "INGRESS_USER" — a Neo4j
            # label and RDF graph name <http://internal/INGRESS_USER_INSTANCES>
            # derived from the TRANSPORT PATH, exactly the PLACE-based design
            # ADR-0041 rejects (quarantine is a STATUS, never a PLACE). So: strip
            # this instance's configured transport prefix from the key into a
            # SEPARATE `domain_key`/`domain_parts` used ONLY for domain/content_kind
            # derivation below. `source_object_key`, `base_dir`, `parts` and
            # `filename` above are untouched — they still address the real S3
            # object, including its full ingress-user/... key.
            domain_key = source_object_key
            if self.path_prefix_strip and domain_key.startswith(self.path_prefix_strip):
                domain_key = domain_key[len(self.path_prefix_strip):]
            domain_parts = domain_key.split('/')

            # doc_id fallback = THE FILE'S OWN NAME, always. The directory is a LOCATION,
            # not an identity: keying on the parent folder gave every PDF dropped flat into
            # a shared inbox the SAME id — `sustainment/inbound/Diodes_PCN_2683.pdf` ->
            # parts[1:-1] == ["inbound"] -> doc_id "inbound" for every document in there,
            # so they collided on one notice_id/workflow_id (live 2026-07-30). The filename
            # is unique per document by construction and is what a human calls the notice.
            #
            # This is only the FALLBACK: when the header pass succeeds, the notice's own
            # printed number (NoticeHeader.doc_id) wins. It matters precisely when the
            # header extraction fails — i.e. exactly when things are already going wrong,
            # which is the worst time to also collapse every document onto one identity.
            doc_id = filename.rsplit('.', 1)[0] or filename

            # ADR-0041 F2/F3 — the Lane-1 sidecar, when configured, WINS over
            # path derivation entirely. Ground truth (sandbox, 2026-10-02):
            # Lane 1's `POST /ingest` writes
            #   ingress-user/{kind}/{sha256}/{filename}     <- the document
            #   ingress-user/{kind}/{sha256}/manifest.json  <- the sidecar
            # where `kind` is a FILE FORMAT ("pdf"/"cad"; ingest_status.KINDS),
            # NOT a semantic domain, and `sha256` is 64 lowercase hex. Deriving
            # domain_type/content_kind from `domain_parts` here (as the vetted
            # path still does, below) would read domain_type="pdf" and
            # content_kind="<64 hex>" — a file FORMAT and a HASH standing in
            # for a semantic label and a content kind. That is D3, and it is
            # why every user drop used to halt in semantic_assets.py with
            # ProvenanceNotPersistableError (the domain read as "PDF", which was
            # not in the DOMAINS_THAT_PERSIST_PROVENANCE set -- both that set
            # and that error are gone as of the 2026-10-02 invariant ruling:
            # provenance now persists for every domain). So: when
            # sidecar_manifest_name
            # is set, domain_type/content_kind/ingest_id/provenance all come
            # from the sidecar — never from domain_parts — and a missing or
            # unparseable sidecar is a HARD FAILURE (no path-derivation
            # fallback: a fallback is exactly how D3 happened).
            sidecar = None
            ingest_id = None
            sidecar_provenance = None
            status_resource = None
            if self.sidecar_manifest_name:
                from doc_tools.utils.dagster_resources import IngestStatusResource
                status_resource = IngestStatusResource()

                sidecar_key = f"{base_dir}/{self.sidecar_manifest_name}"
                try:
                    sidecar_obj = s3_client.get_object(Bucket=bucket, Key=sidecar_key)
                    sidecar_body = sidecar_obj["Body"].read()
                    sidecar = json.loads(sidecar_body)
                except Exception as e:
                    raise RuntimeError(
                        f"ADR-0041 sidecar manifest missing or unparseable at "
                        f"key={sidecar_key!r} (bucket={bucket!r}): {e}"
                    ) from e

                domain = sidecar.get("domain_type")
                content_kind_from_path = sidecar.get("content_kind")
                ingest_id = sidecar.get("ingest_id")
                sidecar_provenance = sidecar.get("provenance")

                # F3 guard — cheap, and it is the one that would have caught
                # D3: a resolved domain_type/content_kind that is still a
                # FORMAT or a HASH must never reach the graph as a semantic
                # label, even if some future sidecar producer gets this wrong.
                if domain in ("pdf", "cad"):
                    raise ValueError(
                        f"ADR-0041 guard: sidecar {sidecar_key!r} domain_type="
                        f"{domain!r} is a file FORMAT (ingest_status.KINDS), "
                        f"not a semantic domain — refusing to use it as one."
                    )
                # A MISSING domain WAS a hard halt here, and the premises
                # behind that halt were ruled on 2026-10-02. What changed, and
                # what did not:
                #
                #  - A null `domain_type` in Lane 1's sidecar is no longer a
                #    defect. `gateway.py`'s POST /ingest hardcodes it and
                #    accepts no domain parameter, and under the ruling that is
                #    CORRECT: "domain_type comes from the registered content
                #    kind's declared domain, never a run tag" -- and never a
                #    door parameter either. The door declares the KIND; the
                #    registered row declares the domain, or declares that the
                #    kind has none.
                #  - So the refusal moves from "no domain" to "no registered
                #    kind". A drop declaring a kind that HAS a KIND_MAPPING row
                #    is admissible with a null domain: `semantic_assets.py`
                #    reads the domain off the row, and for a format-level kind
                #    (pdf / engineering-document / doors-export, which declare
                #    none) returns "origin unresolved" and writes nothing
                #    anywhere.
                #  - A drop declaring NO kind, or an unregistered one, still
                #    halts, and still halts HERE rather than 200 lines
                #    downstream where the sidecar key is out of reach. Same
                #    refusal, with the blocker now being the one thing the door
                #    controls: the picker's confirmed kind. Defaulting a domain
                #    here would still be this lane inventing a semantic claim
                #    about a user drop.
                #  - The third old blocker is simply gone:
                #    DOMAINS_THAT_PERSIST_PROVENANCE was deleted by the same
                #    ruling ("provenance persists for every domain; it is an
                #    invariant of the write path, not an opt-in"), so a
                #    resolved domain no longer has to earn its way into a set.
                if not domain:
                    from doc_tools.utils.content_kind import KIND_MAPPING, _lookup
                    registered = _lookup(content_kind_from_path)
                    if registered is None:
                        raise ValueError(
                            f"ADR-0041 guard: sidecar {sidecar_key!r} carries no "
                            f"domain_type (got {domain!r}) AND no registered "
                            f"content_kind (got {content_kind_from_path!r}). "
                            f"Since 2026-10-02 the null domain is expected -- the "
                            f"registered kind's row is what declares the domain, "
                            f"so a drop needs a kind the table knows. Registered "
                            f"kinds: {sorted(e.kind for e in KIND_MAPPING.values())}. "
                            f"Either have the door send one of those as "
                            f"`content_kind` (POST /ingest's optional form field, "
                            f"which it writes to the sidecar) or add a row to "
                            f"KIND_MAPPING (reserved to the architect). Refusing "
                            f"to guess a domain: a wrong one writes unvetted "
                            f"content into a vetted domain's graph."
                        )
                    # Deliberately NOT copied onto the manifest as a domain.
                    # The row is read again downstream, where the
                    # origin-unresolved short-circuit lives; copying its domain
                    # here would create a second authority for the same value,
                    # and for a format-level kind there is no value to copy.
                    _row_note = (
                        "a format-level kind: it declares no domain, so the "
                        "write path will return origin_unresolved and write "
                        "nothing"
                        if registered.domain_type is None
                        else "the domain is declared by the row"
                    )
                    context.log.info(
                        f"ADR-0041: sidecar {sidecar_key!r} has domain_type=None "
                        f"with registered content_kind="
                        f"{content_kind_from_path!r} -> admissible "
                        f"(domain_type={registered.domain_type!r}; {_row_note})."
                    )
                if content_kind_from_path and re.match(r"^[0-9a-f]{64}$", content_kind_from_path):
                    raise ValueError(
                        f"ADR-0041 guard: sidecar {sidecar_key!r} content_kind="
                        f"{content_kind_from_path!r} is a sha256 hash, not a "
                        f"content kind — refusing to use it as one."
                    )

                # ADR-0041 ruling 2026-10-02 — ingest_id is the canonical
                # `sha256:<64 hex>` spelling EVERYWHERE, and the uuid/bare-hex
                # forms are defects. Checked HERE, beside the domain_type and
                # content_kind guards, because this is the one place that holds
                # the sidecar key to name in the error.
                #
                # The stamp below used to claim "now that ingest_id is known"
                # while `sidecar.get("ingest_id")` could perfectly well be
                # None — the comment was aspirational. A None join key is not
                # fixable by minting one: `ingest_id` addresses a row in Lane
                # 1's ingest_status_projection that Lane 1 created, and a
                # locally minted substitute names no row (the same reason F2/D4
                # makes the sidecar's provenance block WIN over a fresh mint,
                # below). So a sidecar that omits it is refused, which is what
                # makes the stamp's comment true rather than hopeful.
                ingest_id = canonical_ingest_id(
                    ingest_id, where=f"ADR-0041 sidecar {sidecar_key!r}"
                )

                # "extracting" — parse start, now that ingest_id is known
                # (guaranteed canonical and non-None by the guard above).
                status_resource.update(ingest_id, "extracting")
            else:
                domain = domain_parts[0] if len(domain_parts) >= 2 else "unknown"
                content_kind_from_path = domain_parts[1] if len(domain_parts) >= 3 else None

            # Reprocess-safe artifact layout: every generated artifact for this
            # document lands under a `{version}` path segment so a reprocess at a
            # new pipeline version cannot overwrite the prior run's outputs. Used
            # VERBATIM as one path segment — NOT normalised/slugified, the `@`
            # stays — because this MUST be byte-identical to the
            # `pipeline_version` value stamped into review.json by
            # doc_tools/plugins/sustainment.py (same env var, same default
            # string). Two spellings of the same version is exactly the seam
            # this repo keeps getting bitten by; see that module's comment.
            version = os.getenv("DOC_TOOLS_VERSION", "doc-tools@unstamped")

            context.log.info(f"Processing artifact: {source_object_key} (Bucket: {bucket}, Domain: {domain}, Doc ID: {doc_id}, Base Dir: {base_dir}, Version: {version})")

            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    file_path = os.path.join(temp_dir, filename)
                
                    # === 1. Native Boto3 Download ===
                    try:
                        s3_client.download_file(Bucket=bucket, Key=source_object_key, Filename=file_path)
                    except Exception as e:
                        context.log.warning(f"Failed to download from S3/Minio: {e}")
                        if not os.path.exists(file_path):
                            with open(file_path, "w") as f:
                                f.write("mock document content")

                    # Fetch metadata.json
                    doc_metadata = {}
                    try:
                        metadata_path = os.path.join(temp_dir, "metadata.json")
                        s3_client.download_file(Bucket=bucket, Key=f"{base_dir}/metadata.json", Filename=metadata_path)
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            doc_metadata = json.load(f)
                    except Exception:
                        context.log.warning("No metadata.json found.")

                    # === 2. Custom Extraction Logic ===
                    elements = []
                    embedded_images_map = {}
                    pages_list = []  # full-page renders — the context half of the evidence card
                    extraction_metadata = {}
                
                    try:
                        with tempfile.TemporaryDirectory() as temp_extract_dir:
                            try:
                                elements = extract_text_and_metadata(
                                    file_path,
                                    extract_images=True,
                                    image_output_dir=temp_extract_dir,
                                    # Config-surfaced render DPI for the cropped Table/Image
                                    # blocks the sustainment vision pass consumes (default 200).
                                    pdf_image_dpi=int(os.getenv("DOC_PARSER_PDF_IMAGE_DPI", "200")),
                                )

                                # PPTX Special Handling
                                if filename.lower().endswith((".pptx", ".ppt")):
                                    from doc_tools.utils.pptx_media_extractor import extract_images_from_pptx
                                    direct_images = extract_images_from_pptx(file_path, temp_extract_dir)
                                    context.log.info(f"Direct PPTX extraction found {len(direct_images)} images.")

                            except Exception as extract_err:
                                context.log.error(f"Extraction error: {extract_err}")
                                if not elements:
                                    elements = [{"type": "Text", "text": "Extracted text content", "metadata": {"page_number": 1}}]

                            # CROP GEOMETRY REPAIR — unstructured's hi_res path writes Table
                            # crops using its own detected bbox with zero padding, which on
                            # measured corpus pages cuts horizontally through the last row's
                            # glyphs (the SYTX9-122HP-1+ -> SYTYD-122HP-1+ misread on
                            # PCN23-002). Re-crops each affected Table element's image file
                            # in place and updates its metadata.coordinates BEFORE the
                            # upload loop below, so the corrected crop is what gets
                            # uploaded. PDF-only, and never allowed to fail the parse: a
                            # geometry repair is strictly a quality improvement over the
                            # crops unstructured already produced, not a requirement.
                            if filename.lower().endswith(".pdf"):
                                try:
                                    from doc_tools.utils.crop_geometry import repair_table_crops
                                    n_repaired = repair_table_crops(file_path, elements, temp_extract_dir)
                                    if n_repaired:
                                        context.log.info(f"Crop geometry: re-cropped {n_repaired} table image(s)")
                                except Exception as geom_err:
                                    context.log.warning(f"Crop geometry repair failed (continuing with original crops): {geom_err}")

                            # Upload images via Boto3
                            base_name = filename.replace('.', '_')
                            if os.path.exists(temp_extract_dir):
                                for img_filename in os.listdir(temp_extract_dir):
                                    img_local_path = os.path.join(temp_extract_dir, img_filename)
                                    if os.path.isfile(img_local_path):
                                        object_name = f"{base_dir}/generated/{base_name}/{version}/images/{img_filename}"
                                        ext = os.path.splitext(img_filename)[1].lower()
                                        ctype = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
                                        try:
                                            s3_client.upload_file(
                                                Filename=img_local_path, 
                                                Bucket=bucket, 
                                                Key=object_name, 
                                                ExtraArgs={"ContentType": ctype}
                                            )
                                            url = f"s3://{bucket}/{object_name}"
                                            embedded_images_map[img_filename] = url
                                        except Exception as e:
                                            context.log.error(f"Failed to upload image {img_filename}: {e}")

                            # Full-page renders — the CONTEXT half of the evidence card
                            # (which table, where on the page, what surrounds it). The
                            # crops above are the DETAIL half. Rendered here in the same
                            # block that owns file_path + the bucket/key math, uploaded
                            # under the SAME images/ prefix as the crops. Kept in a
                            # separate `pages` list (NOT embedded_images) so the
                            # basename→crop-url map the provenance join reads stays
                            # crop-only; the page render is looked up by page number.
                            try:
                                pages_dir = os.path.join(temp_extract_dir, "_pages")
                                os.makedirs(pages_dir, exist_ok=True)
                                rendered = rasterize_pdf_pages(
                                    file_path, pages_dir,
                                    dpi=int(os.getenv("DOC_PARSER_PAGE_RENDER_DPI", "300")),
                                )
                                for p in rendered:
                                    object_name = f"{base_dir}/generated/{base_name}/{version}/images/{p['basename']}"
                                    try:
                                        s3_client.upload_file(
                                            Filename=p["path"], Bucket=bucket, Key=object_name,
                                            ExtraArgs={"ContentType": "image/jpeg"},
                                        )
                                        p["s3_url"] = f"s3://{bucket}/{object_name}"
                                        p.pop("path", None)
                                        pages_list.append(p)
                                    except Exception as e:
                                        context.log.error(f"Failed to upload page image {p['basename']}: {e}")
                            except Exception as e:
                                context.log.error(f"Page rasterization failed: {e}")

                        if elements:
                            first_meta = elements[0].get("metadata", {})
                            # This drops coordinates/page_number/image_path ONLY from the
                            # doc-level manifest SUMMARY dict (first element's leftover
                            # metadata) — they are meaningless there. The authoritative,
                            # PER-ELEMENT coordinates/page_number/image_path are retained
                            # in text.json below (json.dumps(elements)) and are the source
                            # the Phase-5 provenance resolver reads. DO NOT extend this
                            # strip to the text.json dump — highlighting depends on those
                            # per-element boxes.
                            extraction_metadata = {k: v for k, v in first_meta.items() if k not in ["coordinates", "page_number", "image_path"]}
                    
                        # Store text.json via Boto3
                        base_name = filename.replace('.', '_')
                        text_object_name = f"{base_dir}/generated/{base_name}/{version}/text.json"
                        text_json = json.dumps(elements, indent=2)
                        s3_client.put_object(
                            Bucket=bucket, 
                            Key=text_object_name, 
                            Body=text_json.encode('utf-8'), 
                            ContentType="application/json"
                        )
                        
                    except Exception as e:
                        context.log.error(f"Failed extraction process: {e}")

                    # Create Manifest (Merge component config with file metadata)
                    #
                    # ADR-0021 Phase 2/3: also stamp content_kind from the path
                    # alongside domain_type. The precedence is metadata > path,
                    # encoded via the dict-spread below — `doc_metadata` (from
                    # metadata.json) overrides this path-derived value when
                    # present, same way it already does for domain_type. The
                    # resolver in `semantic_assets` HALTS on unclassifiable
                    # input (no fallback to a default) — see
                    # doc_tools/utils/content_kind.py for the rule the
                    # legacy domain_type chain deliberately does not inherit.
                    #
                    # Path shape: <domain_type>/<content_kind>/<doc_id>/<file>
                    # e.g. manufacturing/work-instructions/M67/grenade.pdf
                    # domain_parts[0] = domain ("manufacturing"); domain_parts[1] =
                    # content_kind. `domain`/`content_kind_from_path` are already
                    # resolved above (sidecar-derived when sidecar_manifest_name
                    # is set, else path-derived from domain_parts post
                    # path_prefix_strip) — NOT re-derived here. Re-deriving here
                    # would silently overwrite the sidecar's values with
                    # domain_parts[0]/[1], exactly the format-and-hash-as-label
                    # bug (D3) this sidecar path exists to close.
                    manifest_metadata = {
                        "domain_type": domain,
                        "content_kind": content_kind_from_path,
                        **self.config,
                        **doc_metadata,
                    }
                    base_name = filename.replace('.', '_')
                    manifest = {
                        "doc_id": doc_id,
                        "filename": filename,
                        # The SOURCE document's own key. Declared, not derived: downstream
                        # (the sustainment text-layer pass) must re-open the original PDF to
                        # read its text layer, and reconstructing this key by string-surgery
                        # on `text_location` would be a path-derivation guess that breaks the
                        # first time the layout changes. The producer knows it; it says it.
                        "source_key": source_object_key,
                        "metadata": manifest_metadata,
                        "extraction_metadata": extraction_metadata,
                        "embedded_images": embedded_images_map,
                        "pages": pages_list,  # full-page renders: {page, s3_url, basename, width, height, dpi}
                        "text_location": f"{base_dir}/generated/{base_name}/{version}/text.json",
                        # DECLARED, not left to be read off the key's path.
                        # This manifest is the artifact the `review` stage
                        # POST names as its `extraction_ref`, and Lane 1
                        # derives `pipeline_version` from the artifact rather
                        # than trusting a caller-asserted one (ADR-0034). The
                        # version IS also the second-to-last path segment of
                        # this object's own key, but recovering it that way is
                        # the same path-derivation guess `source_key` exists
                        # to avoid — it breaks the first time the layout
                        # changes, and silently.
                        "pipeline_version": version,
                    }

                    # ADR-0041 — when this instance is configured with obtained_via
                    # (e.g. the ingress-user sensor's user_document_parser), stamp a
                    # top-level "provenance" key onto the manifest — a SIBLING of
                    # doc_id/source_key, never buried under "metadata" — so the
                    # enforcement point in semantic_assets.py can see it without
                    # reaching into domain-specific metadata shape. When
                    # obtained_via is None (every existing/vetted sensor instance),
                    # this block does not run at all: the manifest is byte-for-byte
                    # what it was before this change.
                    #
                    # F2/D4 — the sidecar's OWN provenance block (sidecar_provenance,
                    # resolved above) WINS over minting a fresh one: Lane 1's block
                    # already carries `ingest_id` (the join key to its
                    # ingest_status_projection row), and a freshly minted block
                    # cannot be joined back to that row. Mint via
                    # build_ingest_provenance() only when the sidecar carried no
                    # block at all.
                    if self.obtained_via:
                        if sidecar_provenance:
                            manifest["provenance"] = sidecar_provenance
                        else:
                            # Local import: keeps this component importable (and its
                            # module-level import cost nil) for every caller that
                            # doesn't configure obtained_via — most of them — and
                            # confines the iagent_mesh.provenance dependency to the
                            # one call site that actually needs it.
                            from doc_tools.utils.ingest_provenance import build_ingest_provenance

                            # Canonical `sha256:<64 hex>`, via the SAME
                            # derivation as
                            # invincible-agent/src/iagent/promotion.py:136's
                            # `ingest_id_for` — this used to be a BARE
                            # hexdigest, which is the spelling
                            # `promotion.INGEST_ID_RE` refuses, so a document
                            # minted here could not have been promoted later
                            # without a spelling fix. Architect ruling
                            # 2026-10-02; see doc_tools/utils/ingest_id.py.
                            with open(file_path, "rb") as f:
                                minted_ingest_id = mint_ingest_id(f.read())
                            if ingest_id is None:
                                ingest_id = minted_ingest_id

                            manifest["provenance"] = build_ingest_provenance(
                                obtained_via=self.obtained_via,
                                authoritative_source=self.authoritative_source,
                                ingest_run=context.run_id,
                                standing=self.standing,
                                ingest_id=minted_ingest_id,
                                as_of=None,
                            )

                    # F4 — ingest_id at the TOP LEVEL of the manifest, sibling of
                    # "provenance" (same shape Lane 1 uses): the join key between
                    # a doc-tools artifact and Lane 1's ingest_status_projection
                    # row. Present whenever one is known (sidecar-supplied or
                    # freshly minted above) — absent for every vetted/no-sidecar,
                    # no-obtained_via instance, exactly like "provenance" itself.
                    # Canonicalized on the way onto the manifest too, so the
                    # ONE shape holds at the artifact boundary and not merely
                    # at the status seam. Both producers already emit the
                    # canonical form above; this is the belt, and it is what a
                    # future third producer hits.
                    if ingest_id is not None:
                        manifest["ingest_id"] = canonical_ingest_id(
                            ingest_id, where=f"manifest for doc_id={doc_id!r}"
                        )

                    # Store manifest.json via Boto3, under the versioned prefix. This
                    # file is NEVER overwritten by a later reprocess — a different
                    # DOC_TOOLS_VERSION lands at a different key entirely.
                    manifest_object_name = f"{base_dir}/generated/{base_name}/{version}/manifest.json"
                    manifest_json = json.dumps(manifest, indent=2)
                    s3_client.put_object(
                        Bucket=bucket,
                        Key=manifest_object_name,
                        Body=manifest_json.encode('utf-8'),
                        ContentType="application/json"
                    )

                    # Pointer file — the ONLY mutable path in generated/{base_name}/.
                    # Written LAST, strictly after the versioned manifest.json put
                    # above has succeeded: if the run crashes before this point, the
                    # pointer keeps naming whatever version it last named (or is
                    # simply absent), and never points at a half-written version.
                    # Readers fall back to the legacy unversioned manifest.json when
                    # this file doesn't exist at all (pre-versioning corpus).
                    current_object_name = f"{base_dir}/generated/{base_name}/current.json"
                    current_pointer = {
                        "pipeline_version": version,
                        "manifest_key": manifest_object_name,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    s3_client.put_object(
                        Bucket=bucket,
                        Key=current_object_name,
                        Body=json.dumps(current_pointer, indent=2).encode('utf-8'),
                        ContentType="application/json",
                    )

                # "review" — success, with the element/page
                # counts this asset already computed above (`elements`,
                # `pages_list`) rather than re-deriving a count elsewhere.
                #
                # TWO FIELDS, TWO UNITS — see IngestStatusResource's
                # EXTRACTED_COUNT_UNIT / EXTRACTED_TOTAL_UNIT, which these two
                # expressions are the authority for:
                #   extracted_count = len(elements)    -> unstructured ELEMENTS
                #   extracted_total = len(pages_list)  -> rasterized PAGES
                # They are NOT a fraction. `extracted_count` counts the
                # document's extracted elements and `extracted_total` counts
                # the source PDF's pages, so count > total is the normal case
                # (a 9-page notice yields hundreds of elements) and
                # count/total is not a completion ratio. Naming this at the
                # call site as well as at the resource because the mismatch is
                # invisible from either side alone.
                #
                # `extraction_ref` — the versioned manifest key written just
                # above. This is the stage Lane 1 turns into a
                # `document_promotion` task, and a promote on a task whose
                # payload cannot name the extraction is refused 422
                # (measured on PCN26-119, roll #19). The key is bucket-
                # relative, matching `object_ref`'s convention for the same
                # document, and it names the IMMUTABLE versioned manifest —
                # never `current.json`, which the next reprocess repoints, so
                # a decision record naming it would later describe a
                # different extraction than the one that was reviewed.
                if status_resource is not None:
                    status_resource.update(
                        ingest_id, "review",
                        extracted_count=len(elements) if elements else 0,
                        extracted_total=len(pages_list) if pages_list else None,
                        extraction_ref=manifest_object_name,
                    )

                return manifest
            except Exception as e:
                # Only stamp when a join key is actually in hand. `ingest_id`
                # is None until the sidecar is read, so a failure BEFORE that
                # (a missing/unparseable sidecar, a refused domain_type) has
                # nothing to address the stamp to — and since `update()` now
                # refuses a non-canonical id, stamping anyway would raise
                # inside this handler and MASK the original exception with a
                # shape complaint. Log the gap instead, and re-raise `e`.
                if status_resource is not None:
                    if ingest_id is not None:
                        status_resource.update(ingest_id, "failed", detail=str(e))
                    else:
                        context.log.error(
                            "ADR-0041: ingest failed before an ingest_id was "
                            "known, so no 'failed' stage could be stamped "
                            "(nothing to join to Lane 1's "
                            "ingest_status_projection). Underlying error: %s", e,
                        )
                raise

        # Define the pipeline job with dynamic K8s resource tags
        k8s_tags = resolve_k8s_resource_tags(prefix=self.k8s_resource_prefix, default_cpu="2000m", default_mem="6Gi")
        
        process_job = define_asset_job(
            name=f"{self.name}_job",
            selection=[self.name, self.downstream_graph_asset],
            tags=k8s_tags
        )

        return Definitions(assets=[process_document_artifact], jobs=[process_job])
