---
name: check-part-sustainment
description: Use this skill when a user asks about a part's health, lifecycle, obsolescence, or sustainment status. It queries the Neo4j graph for sustainment notices (like PCN or PDN) and replacement parts.
---

# Check Part Sustainment

When a user asks about a part's health or lifecycle, execute the following steps:

1. Query the Neo4j graph for `[:SUBJECT_TO]` relationships linking the part to `SustainmentNotice` nodes.
2. Check for any PDN (Product Discontinuation Notice) types.
3. Check if there is an `ltb_date` (Last Time Buy Date) in the past or approaching.
4. Check if there are any replacement parts available via the `[:REPLACED_BY]` relationship.

## Example Cypher Query

```cypher
MATCH (c:Component {mpn: $part_number})-[:SUBJECT_TO]->(n:SustainmentNotice)
OPTIONAL MATCH (c)-[r:REPLACED_BY]->(alt:Component)
RETURN n.type AS notice_type, n.pub_date AS published_date, n.mfr AS manufacturer, 
       r.ltb_date AS last_time_buy, alt.mpn AS replacement_part
```

Analyze the results to inform the user about the part's current sustainment status and whether action is needed (e.g., finding a replacement or securing a last time buy).