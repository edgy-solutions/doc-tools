# Draft issue text for the DPP repo — three gaps

**Status:** DRAFT, for Chris to post under his name on the DPP repo. Not posted by
this lane. Ruling item 4 of the 2026-10-29 packet: *"Draft the three upstream
findings (two-correct-readings, header offset, coordinate space) as one issue text,
synthetic examples only."*

**Disclosure check before posting.** Every example below is synthetic and was
written for this issue. No document name, no part number, no manufacturer, no
customer, no filename, no host and no site identifier appears. The part numbers are
invented (`AB1234-5`); the manufacturer is invented (`Northwind Components`); the
coordinates are invented. What *is* real is the *shape* of each defect and the
counts of our own corpus (ten notices, nine, three) — those name nothing. If the
posting account's name or affiliation is itself sensitive for this, that is Chris's
call, not a redaction this text can make.

Everything below the rule is the issue body, ready to paste.

---

## Three places the draft is silent, found by tabling an implementation against it

We tabled an existing document-parsing implementation against this draft rule by
rule, across the table rules, the form rules, traceability and the principles. Most
of it agreed — eleven rules agree with what we independently built, and two of those
we had arrived at from the never-invent principle without having seen the draft,
which is the strongest thing we can say about it.

Three places the draft is silent, and in each one our corpus has already paid for
the knowledge. They share a shape: the draft names the right obligation and leaves
the *representation* under-specified, so a conforming producer and a conforming
consumer can disagree without either of them breaking a rule.

Examples are synthetic. They reproduce the shape of each defect, not any document.

### 1. Two verbatim-correct readings of one field

`principles-the-page-is-the-ground-truth` requires text transcribed verbatim, typos
included. `forms-values-are-verbatim` repeats it for field values. Neither says what
happens when one page prints the same field twice, in two different forms, and
**both are verbatim-correct**.

Synthetic case. A one-page change notice whose footer band reads

```
Northwind Components Incorporated · 1 Example Way · support@example.invalid
```

and whose logo wordmark, at the top of the same page, reads

```
NORTHWIND COMPONENTS
```

Asked for the issuing manufacturer, one extractor returns `Northwind Components
Incorporated`; another returns `NORTHWIND COMPONENTS`. Both transcribed what the
page prints, character for character, from a region the page intends as the issuer's
name. A conformance checker that compares a parse against a single expected string
marks one of them wrong.

This is not hypothetical for us. A raw-string comparison against one expected value
scored a *correct* extractor **0 of 3** on a three-field header: one reader took the
logo wordmark, another took a heading whose text layer was damaged, and the
comparator reported two correct readings as a disagreement. The measurement was
lost, not the extraction.

What we do instead: the expected value of a verbatim field is an **accepted-verbatim
set**, not a string. One member is the canonical form; every other member is a
reading the page itself supports. Comparison canonicalizes, then tests membership.

Proposed for the draft:

1. A principle-level clause: where a page prints one field's value more than once in
   more than one form, **every printed form is verbatim-correct**; a protocol that
   says "verbatim" and stops cannot say which one a parser owes.
2. A conformance clause: expected values for verbatim fields are **sets**, and
   comparison is canonical-then-membership.

Without this, two conforming parsers can disagree while both conform, and the draft
has no vocabulary to say so.

### 2. A header label offset from its data column

`tables-header-body-column-count-mismatch` covers a **count** mismatch: pad the
short side with empty cells, and never pad with a duplicated or invented value. The
failure we actually measured is not a count mismatch. The counts agree; the header
labels are **shifted one column** from the data they name.

Synthetic case:

```
                  Part Number        Qual Vehicle
  AB1234-5         CD6789-0           EF2345-6
  AB1235-5         CD6780-0           EF2346-6
  AB1236-5         CD6781-0           EF2347-6
```

Three data columns, three header labels — but `Part Number` sits over column 1 while
the part numbers are in column 0, because the header row rendered with a leading
empty cell. Padding cannot help: nothing is short. And the defect is not benign,
because columns 0 and 2 both hold part-number-shaped values, so a one-column shift
is exactly as likely to publish the qualification-vehicle column as the affected
parts.

What we do instead: we detect that the label does not sit over the column whose
values it names, and we **decline the table** rather than emit a guess. We prefer
returning nothing to returning the wrong column, because a wrongly asserted
identifier in our output cannot be withdrawn by re-running the extractor — the
identifier is shared with other documents, so a correction has nothing to key on.

Proposed for the draft: a rule for a header label whose horizontal extent does not
overlap the data column at the same index. Either

- (a) associate labels to columns by **printed x-extent**, not by index; or
- (b) require that an unresolvable association be **marked** rather than guessed —
  which is the never-invent principle applied to the header row rather than to a
  cell.

Worth knowing how common this is: header-to-column misalignment was one of **three
distinct causes** of silent-zero extractions we found across nine notices. It is not
a rare shape, and a checker built on the draft as written would pass a producer that
publishes the wrong column.

### 3. A declared coordinate space for boxes

`principles-traceability` requires every element to carry a box and every box to
cover exactly the printed content of its element. We agree and are sealed to it. The
draft never says what space those numbers are in.

Synthetic case — the same element, on the same page, from two producers:

```
Producer A:  {"page": 2, "bbox": [72.0, 108.0, 180.0, 122.0]}
Producer B:  {"page": 2, "bbox": [300, 450, 750, 508]}
```

A is PDF points with the origin at the bottom-left. B is pixels of a 300-DPI render
with the origin at the top-left. **Both satisfy the rule exactly as written.** A
consumer that crops the region, or tests two boxes for overlap, is wrong for one of
them and has no way to tell which — the numbers alone do not say, and neither does
the sidecar.

We hit this. One source's row boxes were in image-pixel space while another's were
in PDF points, and the only thing that made the two comparable was carrying the
**page's own dimensions** beside every box, so a consumer can reduce to a fraction
of the page (`fraction = bbox / page_dims`), which is unit-agnostic. We since
narrowed our own box type to `{page, bbox, note?}` on exactly that reasoning.

Proposed for the draft: require a box either to **declare its space** (units and
origin corner) or to be accompanied by the **page dimensions in the same units**.
Either one makes a sidecar self-describing. Without it, a conforming sidecar is one
producer change away from silently meaning something else, with nothing in the file
to record that it changed.

### Why these three and not the rest

We differ from the draft in other places too, and most of those differences are
*ours* to defend — we are a field extractor, not a document renderer, so we drop
content the draft requires kept, and we join table fragments across pages the draft
requires kept separate. Those are our trade-offs and we are not asking the draft to
move.

These three are different: in each one the draft's obligation is right and its
representation is incomplete, and in each one we have a measurement showing what the
incompleteness costs. Happy to expand on any of them.
