{{/*
Expand the name of the chart.
*/}}
{{- define "doc-tools.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "doc-tools.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "doc-tools.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "doc-tools.labels" -}}
helm.sh/chart: {{ include "doc-tools.chart" . }}
{{ include "doc-tools.selectorLabels" . }}
{{/*
  VERSION COMES FROM THE DEPLOYED IMAGE, NOT FROM .Chart.AppVersion.

  This label previously read .Chart.AppVersion, which was untouched `helm create`
  scaffolding ("1.16.0") — so every doc-tools pod in the namespace has been
  asserting a version that has never existed and cannot be built, since the chart
  was scaffolded. That is not a harmless leftover: app.kubernetes.io/version is a
  standard label read by inventory tooling, dashboards and selectors, so the
  cluster has been carrying a false statement about what is running.

  Any STATIC replacement would have been false again on the next build — a
  chart-level constant cannot track a per-commit image. Deriving it from
  image.tag makes the label true by construction: it is exactly the identifier
  the pod is running. Same law as pinning the tag itself — the declaration has
  to be the fact, not a restatement of intent.

  SAFE TO CHANGE: this lives in the common labels only. selectorLabels (below) is
  name + instance, so the Deployment's immutable spec.selector is untouched and
  an upgrade does not hit a field-is-immutable error.
*/}}
{{- if .Values.image.tag }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
{{- else if .Values.image.digest }}
{{/* A digest-pinned release still has to answer "which code is this?". The
     label is 63 chars max and a full digest is 71, so it carries the first 12
     hex of the digest — the same prefix the registry UI and `docker images`
     show, and enough to look up. Prefixed to keep it unmistakable: nobody
     should read this as a commit sha, because it is not one. */}}
app.kubernetes.io/version: {{ printf "sha256-%s" (.Values.image.digest | trimPrefix "sha256:" | trunc 12) | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
THE IMAGE REFERENCE, AND THE REFUSAL ATTACHED TO IT.

A TAG IS GUESSABLE FROM GIT; A DIGEST IS NOT. That single asymmetry is the whole
reason this helper exists. `image.tag: <sha>` can be written by reading `git log`,
which is exactly how a never-built image gets pinned: on 2026-09-25 the #11 merge
(d7434d6) corrected the ground-truth denominator but left a test asserting the old
one, so its `main` build failed the `tests` job, `build-and-push` never ran, and NO
`:d7434d6` image was ever pushed. That sha was nevertheless a perfectly plausible
thing to copy out of the git log. A digest cannot be produced that way — it exists
only as the output of a real push — so a digest pin CARRIES ITS OWN PROOF OF BUILD.

WHAT THE OLD `required` DID AND DID NOT CATCH. `required "image.tag is required"`
refuses an ABSENT tag. It cannot refuse a PRESENT tag that was never built: that
renders perfectly, Helm reports the release successful, and the failure surfaces
minutes later as ImagePullBackOff on a manifest-unknown — attributed to the
cluster, not to the pin. Absent and never-built are different facts and only the
first one had a guard.

WHAT THIS CANNOT DO, stated so nobody mistakes the guard for more than it is:
Helm does not reach the registry at render time, so NOTHING here can confirm an
image exists. There is exactly one honest move available — make the pin that
cannot lie (the digest) the default path, and make the pin that can lie (the tag)
require someone to say out loud, in a tracked file, that they checked. That turns
an invisible assumption into a reviewable claim. It does not turn it into a
verified one; only a registry query can do that, and that belongs in CI.

  image.digest: sha256:<64 hex>   -> preferred. Rendered as repo@digest.
  image.tag:    <sha>             -> allowed ONLY with image.unverifiedTagAck set
                                     to a non-empty statement of what was checked
                                     (paste the workflow run URL that pushed it).

The digest of every build is printed in the build-and-push job summary.
*/}}
{{- define "doc-tools.image" -}}
{{- $repo := required "image.repository is required." .Values.image.repository -}}
{{- $digest := .Values.image.digest | default "" | toString -}}
{{- $tag := .Values.image.tag | default "" | toString -}}
{{- if $digest -}}
{{- if not (hasPrefix "sha256:" $digest) -}}
{{- fail (printf "image.digest must start with \"sha256:\" — got %q. Copy it verbatim from the build-and-push job summary; a bare hex string is not a digest reference." $digest) -}}
{{- end -}}
{{- if ne (len $digest) 71 -}}
{{- fail (printf "image.digest must be \"sha256:\" followed by 64 hex characters (71 total) — got %d characters. A truncated digest fails at the kubelet, which is the failure mode pinning by digest exists to remove." (len $digest)) -}}
{{- end -}}
{{- printf "%s@%s" $repo $digest -}}
{{- else -}}
{{- if not $tag -}}
{{- fail "Neither image.digest nor image.tag is set, so this release does not say which code it runs. Prefer image.digest (see values.yaml); the chart has no default because an unset tag used to fall back to the scaffold appVersion, which is not a publishable image." -}}
{{- end -}}
{{- if not (.Values.image.unverifiedTagAck | default "" | toString) -}}
{{- fail (printf "REFUSING to pin by tag alone: image.tag=%q has not been shown to exist. A tag is copied out of git, so a commit whose build FAILED or was SKIPPED yields a pin that renders cleanly here and then dies at the kubelet with ImagePullBackOff, on a release Helm has already reported as successful (this happened on 2026-09-25 with d7434d6). Do one of these:\n  1. PREFERRED — pin the digest instead: set image.digest to the sha256:... printed in that commit's build-and-push job summary, and unset image.tag. A digest cannot name an image that was never pushed.\n  2. Confirm the tag exists in the registry, then record that you did: set image.unverifiedTagAck to the URL of the workflow run that pushed it. Helm cannot check the registry itself, so that string is the only evidence a reviewer gets." $tag) -}}
{{- end -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "doc-tools.selectorLabels" -}}
app.kubernetes.io/name: {{ include "doc-tools.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "doc-tools.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "doc-tools.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
