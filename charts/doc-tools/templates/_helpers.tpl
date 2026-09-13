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
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
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
