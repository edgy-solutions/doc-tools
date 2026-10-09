# MRAD mock S1000D data modules

Six synthetic S1000D data modules (a mock MRAD radar maintenance set, DMC
`ODMRAD-A-34-10-01-00A-{040A,320A,421A,520A,720A,941A}-A`). They are invented
test data, not a real publication.

Used by `tests/test_ingress_user_xml_route.py` to drive the user-drop XML route
(`ingress-user/xml/<sha256>/<name>.xml` -> `extract_rdf_from_xml`) against a
stubbed S3. Drops of these same modules are PRESENT-AND-UNPROCESSED in the
sandbox MinIO; the route is proven here against the fixtures only, not against
live MinIO.

**Merge note:** the identical six files also sit in open PR #63
(`feat/s1000d-week2-walk-seal`), which adds a walk seal over them. Whoever
merges second should expect a trivial same-content add/add conflict.
