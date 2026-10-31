# quakeloc

Earthquake detection and location service for the northern Tien Shan (validated on the
open KNET network near Bishkek, ~190 km WSW of Almaty).

A small research-software project built for *Assignment 5 — DevOps and CI/CD:
Automating Processes for Research Projects*. It detects P-wave arrivals (STA/LTA),
picks onsets (AIC) and locates epicentres (Geiger's method) on synthetic and real
seismograms, and ships with a Docker image, a Jenkins CI/CD pipeline and a
Kubernetes (Minikube) deployment.

> Work in progress — see `docs/design/` for the design document.
